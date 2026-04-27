from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .config import Settings
from .ffmpeg_utils import get_duration_seconds, require_binary
from .utils import list_video_files, write_json


def seconds_to_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def utterances_to_srt(utterances: list[dict[str, Any]]) -> str:
    blocks = []
    for idx, item in enumerate(utterances, 1):
        start = seconds_to_srt_time(float(item["start_time"]))
        end = seconds_to_srt_time(float(item["end_time"]))
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        blocks.append(f"{idx}\n{start} --> {end}\n{text}\n")
    return "\n".join(blocks)


def extract_audio_mp3(video_path: Path, audio_path: Path) -> None:
    require_binary("ffmpeg")
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "64k",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"音频提取失败：{result.stderr[-600:]}")


def transcribe_with_ark(audio_path: Path, settings: Settings, model: str | None = None) -> list[dict[str, Any]]:
    api_key = settings.require_ark_api_key()
    try:
        import httpx
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("缺少 openai 或 httpx 依赖。请运行：python3 -m pip install --user .") from exc
    with audio_path.open("rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode("utf-8")
    client = OpenAI(
        api_key=api_key,
        base_url=settings.ark_base_url,
        timeout=httpx.Timeout(600.0, connect=60.0, write=120.0, read=600.0),
        max_retries=2,
    )
    response = client.chat.completions.create(
        model=model or settings.ark_model_name,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "input_audio", "input_audio": {"data": audio_b64, "format": "mp3"}},
                    {
                        "type": "text",
                        "text": (
                            "请将这段短剧音频转录为逐句台词 JSON 数组。"
                            "每项包含 start_time、end_time、text、speaker。"
                            "时间单位为秒，保留两位小数。只返回 JSON 数组。"
                        ),
                    },
                ],
            }
        ],
        max_tokens=16384,
        temperature=0.05,
    )
    text = (response.choices[0].message.content or "").strip()
    if text.startswith("```"):
        text = "\n".join(text.splitlines()[1:-1]).strip()
    data = json.loads(text)
    if not isinstance(data, list):
        raise RuntimeError("ASR 模型返回的不是 JSON 数组")
    return data


def transcribe_with_silence(video_path: Path) -> list[dict[str, Any]]:
    require_binary("ffmpeg")
    result = subprocess.run(
        ["ffmpeg", "-i", str(video_path), "-af", "silencedetect=n=-30dB:d=0.5", "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    duration = get_duration_seconds(video_path)
    silence_starts: list[float] = []
    silence_ends: list[float] = []
    for line in result.stderr.splitlines():
        if "silence_start:" in line:
            try:
                silence_starts.append(float(line.split("silence_start:")[1].split()[0]))
            except (IndexError, ValueError):
                pass
        elif "silence_end:" in line:
            try:
                silence_ends.append(float(line.split("silence_end:")[1].split()[0]))
            except (IndexError, ValueError):
                pass
    if not silence_starts and not silence_ends:
        return [{"start_time": 0.0, "end_time": round(duration, 2), "text": "[speech]", "speaker": "unknown"}]
    utterances = []
    cursor = 0.0
    for silence_start, silence_end in zip(silence_starts, silence_ends):
        if silence_start - cursor > 0.3:
            utterances.append(
                {
                    "start_time": round(cursor, 2),
                    "end_time": round(silence_start, 2),
                    "text": f"[speech segment {len(utterances) + 1}]",
                    "speaker": "unknown",
                }
            )
        cursor = max(cursor, silence_end)
    if duration - cursor > 0.3:
        utterances.append(
            {
                "start_time": round(cursor, 2),
                "end_time": round(duration, 2),
                "text": f"[speech segment {len(utterances) + 1}]",
                "speaker": "unknown",
            }
        )
    return utterances


def transcribe_video(video_path: Path, output_dir: Path, method: str = "auto", model: str | None = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings.load(video_path)
    started = time.time()
    utterances: list[dict[str, Any]] = []
    if method in {"auto", "ark"} and settings.ark_api_key:
        with tempfile.TemporaryDirectory(prefix="drama_cut_asr_") as td:
            audio = Path(td) / "audio.mp3"
            extract_audio_mp3(video_path, audio)
            utterances = transcribe_with_ark(audio, settings, model=model)
    if not utterances and method in {"auto", "silence"}:
        utterances = transcribe_with_silence(video_path)
    result = {
        "video": video_path.name,
        "duration": get_duration_seconds(video_path),
        "utterance_count": len(utterances),
        "utterances": utterances,
        "method": "ark" if settings.ark_api_key and method != "silence" else "silence",
        "elapsed_seconds": round(time.time() - started, 2),
    }
    json_path = output_dir / f"asr_{video_path.stem}.json"
    write_json(json_path, result)
    srt_path = output_dir / f"asr_{video_path.stem}.srt"
    srt_path.write_text(utterances_to_srt(utterances), encoding="utf-8")
    print(f"ASR 已保存：{json_path}")
    return json_path


def transcribe_input(input_path: Path, output_dir: Path, method: str = "auto", model: str | None = None) -> list[Path]:
    outputs = []
    for video in list_video_files(input_path):
        outputs.append(transcribe_video(video, output_dir, method=method, model=model))
    return outputs
