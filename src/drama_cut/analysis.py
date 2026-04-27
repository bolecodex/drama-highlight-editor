from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .config import Settings
from .ffmpeg_utils import get_duration_seconds, require_binary, seconds_to_hms
from .provider.ark import ArkClient
from .review import refine_analysis_data
from .schemas import HighlightAnalysis
from .templates import load_template
from .utils import list_video_files, parse_json_maybe_fenced, sanitize_name, write_json

DEFAULT_MAX_MB = 12.0
MULTI_MAX_MB = 8.0
MAX_VIDEOS_PER_BATCH = 3


def encode_file_base64(path: Path) -> str:
    with path.open("rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def compress_video_for_api(video_path: Path, target_mb: float, temp_dir: Path) -> Path:
    size_mb = video_path.stat().st_size / (1024 * 1024)
    if size_mb <= target_mb:
        return video_path
    require_binary("ffmpeg")
    duration = max(get_duration_seconds(video_path), 30.0)
    target_bitrate_kbps = int((target_mb * 8 * 1024) / duration * 0.85)
    audio_bitrate = 48 if target_mb >= 8 else 32
    video_bitrate = max(target_bitrate_kbps - audio_bitrate, 180)
    out = temp_dir / f"{video_path.stem}_api.mp4"
    scale = "scale='min(480,iw)':-2" if target_mb <= 8 else "scale='min(720,iw)':-2"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vf",
        scale,
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-b:v",
        f"{video_bitrate}k",
        "-c:a",
        "aac",
        "-b:a",
        f"{audio_bitrate}k",
        "-ac",
        "1",
        "-movflags",
        "+faststart",
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"警告：{video_path.name} 压缩失败，将使用原文件上传")
        return video_path
    return out


def load_asr_context(video_paths: list[Path], output_dir: Path, max_chars: int = 24000) -> str:
    sections: list[str] = []
    for video in video_paths:
        candidates = [
            output_dir / f"asr_{video.stem}.json",
            output_dir / f"{video.stem}_asr.json",
            output_dir / f"asr_{video.stem}.txt",
            output_dir / f"asr_{video.stem}.srt",
            video.parent / f"asr_{video.stem}.json",
            video.parent / f"asr_{video.stem}.srt",
        ]
        for candidate in candidates:
            if not candidate.exists():
                continue
            text = candidate.read_text(encoding="utf-8")
            if candidate.suffix == ".json":
                try:
                    data = json.loads(text)
                    utterances = data.get("utterances", data if isinstance(data, list) else [])
                    lines = []
                    for item in utterances:
                        start = item.get("start_time", item.get("start", "?"))
                        end = item.get("end_time", item.get("end", "?"))
                        lines.append(f"[{start}-{end}] {item.get('text', '')}")
                    text = "\n".join(lines)
                except (json.JSONDecodeError, AttributeError):
                    pass
            sections.append(f"### {video.name}\n{text[:max_chars]}")
            break
    if not sections:
        return ""
    return "\n\n## ASR 台词参考\n" + "\n\n".join(sections)


def build_user_prompt(video_paths: list[Path], template_text: str, output_dir: Path, multi_version: bool) -> str:
    lines = []
    total_duration = 0.0
    for video in video_paths:
        duration = get_duration_seconds(video)
        total_duration += duration
        lines.append(f"- {video.name}: {seconds_to_hms(duration)}")
    prompt = (
        f"以下是 {len(video_paths)} 集连续短剧视频，请作为一个完整故事跨集分析。\n"
        f"{chr(10).join(lines)}\n"
        f"总时长约 {int(total_duration)} 秒。\n\n"
        "重要：source_file 必须使用上面列出的文件名，含扩展名，不要写绝对路径。\n"
        "除一个可选全局 hook 外，其余 segments_to_keep 必须保持跨集故事顺序。\n"
        "第 2 集及以后绝不能默认从 00:00:00 开始；必须先判断开头是否为前情回顾、上集尾段重复、片头或转场。\n"
        "如果保留第 2 集及以后开头，必须在 why_keep 中说明它不是前情回顾。\n"
        "重复上一集尾段、黑屏、闪白、强转场残留必须写入 segments_to_remove。\n"
        "每个 start_time/end_time 必须落在完整台词或人物反应边界，最后一段不得在哭喊、质问、道歉、揭露等台词中间结束。\n"
    )
    asr_context = load_asr_context(video_paths, output_dir)
    if asr_context:
        prompt += asr_context + "\n\n请结合 ASR 台词边界精修切点，不要切断台词。\n"
    if multi_version:
        prompt += (
            "\n请额外输出 versions 数组，包含 aggressive、standard、conservative 三个版本。"
            "顶层方案仍为 standard 默认版本。\n"
        )
    return prompt + "\n\n" + template_text


def _call_analysis_batch(
    client: ArkClient,
    video_paths: list[Path],
    template_text: str,
    output_dir: Path,
    multi_version: bool,
    batch_label: str = "",
) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="drama_cut_api_") as td:
        temp_dir = Path(td)
        per_video_mb = MULTI_MAX_MB if len(video_paths) > 1 else DEFAULT_MAX_MB
        for video in video_paths:
            upload = compress_video_for_api(video, per_video_mb, temp_dir)
            video_b64 = encode_file_base64(upload)
            content.append({"type": "video_url", "video_url": {"url": f"data:video/mp4;base64,{video_b64}"}})
        content.append({"type": "text", "text": build_user_prompt(video_paths, template_text, output_dir, multi_version)})
        label = f" ({batch_label})" if batch_label else ""
        print(f"正在使用 {client.model} 分析 {len(video_paths)} 个视频{label}...")
        started = time.time()
        text = client.complete(content, max_tokens=32768 if multi_version else 16384, temperature=0.1)
        print(f"本批次分析完成，耗时 {time.time() - started:.1f} 秒")
        data = parse_json_maybe_fenced(text)
        if not isinstance(data, dict):
            raise RuntimeError("模型分析结果不是 JSON 对象")
        return data


def deterministic_merge(batch_results: list[dict[str, Any]], episodes: list[str]) -> dict[str, Any]:
    merged: dict[str, Any] = {
        "drama_name": batch_results[0].get("drama_name", "短剧"),
        "episodes": episodes,
        "total_source_duration_seconds": sum(float(r.get("total_source_duration_seconds") or 0) for r in batch_results),
        "summary": " ".join(str(r.get("summary", "")) for r in batch_results).strip(),
        "hook": {"enabled": False},
        "segments_to_keep": [],
        "segments_to_remove": [],
            "final_structure": {"description": "跨批次合并方案", "estimated_duration_seconds": 0, "segment_order": []},
    }
    next_id = 1
    for result in batch_results:
        if not merged["hook"].get("enabled") and (result.get("hook") or {}).get("enabled"):
            merged["hook"] = result["hook"]
        for segment in result.get("segments_to_keep", []):
            new_segment = dict(segment)
            new_segment["id"] = next_id
            merged["segments_to_keep"].append(new_segment)
            next_id += 1
        merged["segments_to_remove"].extend(result.get("segments_to_remove", []))
    order = []
    if merged["hook"].get("enabled"):
        order.append({"type": "hook"})
    order.extend({"type": "keep", "id": segment["id"]} for segment in merged["segments_to_keep"])
    merged["final_structure"]["segment_order"] = order
    merged["final_structure"]["estimated_duration_seconds"] = sum(
        float(s.get("duration_seconds") or 0) for s in merged["segments_to_keep"]
    )
    return merged


def model_merge_batches(client: ArkClient, batch_results: list[dict[str, Any]], episodes: list[str]) -> dict[str, Any]:
    prompt = (
        "你是短剧投流剪辑总编。下面是多个视频批次各自的分析 JSON。"
        "请合并成一个最终跨集剪辑 JSON：只能有一个全局 hook；segments_to_keep 重新编号；"
        "除 hook 外保持 episode/story 顺序；删除重复片段；只返回最终 JSON。\n\n"
        f"episodes: {episodes}\n\n"
        f"{json.dumps(batch_results, ensure_ascii=False, indent=2)}"
    )
    text = client.complete([{"type": "text", "text": prompt}], max_tokens=16384, temperature=0.05)
    data = parse_json_maybe_fenced(text)
    if not isinstance(data, dict):
        raise RuntimeError("模型合并结果不是 JSON 对象")
    return data


def analyze(
    input_path: Path,
    output_dir: Path,
    template_id: str = "default",
    name: str | None = None,
    model: str | None = None,
    multi_version: bool = False,
    max_videos_per_batch: int = MAX_VIDEOS_PER_BATCH,
    auto_refine: bool = True,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    video_paths = list_video_files(input_path)
    if not video_paths:
        raise RuntimeError(f"在 {input_path} 下没有找到视频文件")
    template_text = load_template(template_id)
    client = ArkClient(Settings.load(input_path), model=model)
    episodes = [p.name for p in video_paths]
    if len(video_paths) <= max_videos_per_batch:
        data = _call_analysis_batch(client, video_paths, template_text, output_dir, multi_version)
    else:
        batch_results = []
        for idx in range(0, len(video_paths), max_videos_per_batch):
            batch = video_paths[idx : idx + max_videos_per_batch]
            result = _call_analysis_batch(
                client,
                batch,
                template_text,
                output_dir,
                multi_version,
                batch_label=f"batch {len(batch_results) + 1}",
            )
            batch_results.append(result)
            write_json(output_dir / f"highlights_{sanitize_name(name or input_path.stem)}_batch{len(batch_results)}.json", result)
        try:
            data = model_merge_batches(client, batch_results, episodes)
        except Exception as exc:
            print(f"警告：模型合并失败，将使用确定性合并：{exc}")
            data = deterministic_merge(batch_results, episodes)
    data.setdefault("episodes", episodes)
    if "total_source_duration_seconds" not in data:
        data["total_source_duration_seconds"] = round(sum(get_duration_seconds(p) for p in video_paths), 2)
    analysis = HighlightAnalysis.model_validate(data)
    out_name = sanitize_name(name or input_path.stem)
    output_path = output_dir / f"highlights_{out_name}.json"
    raw_output_path = output_dir / f"highlights_{out_name}_raw.json"
    write_json(raw_output_path, analysis.model_dump(exclude_none=True))
    if auto_refine:
        source_root = input_path if input_path.is_dir() else input_path.parent
        analysis = refine_analysis_data(analysis, source_root, output_dir)
        if analysis.qa and analysis.qa.get("blocking_issue_count"):
            print(f"警告：自动精修后仍有 {analysis.qa.get('blocking_issue_count')} 个严重预检问题，请先运行 drama-cut 预检/精修 查看。")
    write_json(output_path, analysis.model_dump(exclude_none=True))
    print(f"原始 AI JSON 已保存：{raw_output_path}")
    print(f"分析 JSON 已保存：{output_path}")
    return output_path
