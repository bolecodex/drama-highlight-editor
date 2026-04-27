from __future__ import annotations

import base64
import json
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .config import Settings
from .ffmpeg_utils import get_duration_seconds, require_binary
from .provider.ark import ArkClient
from .utils import parse_json_maybe_fenced, write_json


def compress_for_scoring(video_path: Path, target_mb: float = 8.0) -> Path:
    size_mb = video_path.stat().st_size / (1024 * 1024)
    if size_mb <= target_mb:
        return video_path
    require_binary("ffmpeg")
    duration = max(get_duration_seconds(video_path), 30.0)
    target_bitrate = int((target_mb * 8 * 1024) / duration * 0.85)
    video_bitrate = max(target_bitrate - 48, 200)
    tmp = Path(tempfile.NamedTemporaryFile(suffix=".mp4", delete=False).name)
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            "scale='min(480,iw)':-2",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-b:v",
            f"{video_bitrate}k",
            "-c:a",
            "aac",
            "-b:a",
            "48k",
            "-ac",
            "1",
            "-movflags",
            "+faststart",
            str(tmp),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        tmp.unlink(missing_ok=True)
        return video_path
    return tmp


def score(video_path: Path, output_dir: Path, model: str | None = None) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings.load(video_path)
    client = ArkClient(settings, model=model)
    compressed = compress_for_scoring(video_path)
    remove_compressed = compressed != video_path
    try:
        video_b64 = base64.b64encode(compressed.read_bytes()).decode("utf-8")
        prompt = (
            "你是一位专业短剧投流素材质检师。请对视频评分并只返回 JSON。"
            "维度：hook_score、rhythm_score、emotion_score、ending_score、dialogue_score。"
            "输出字段：overall_score、grade、scores、strengths、weaknesses、suggestions、summary。"
        )
        started = time.time()
        text = client.complete(
            [
                {"type": "video_url", "video_url": {"url": f"data:video/mp4;base64,{video_b64}"}},
                {"type": "text", "text": prompt},
            ],
            max_tokens=4096,
            temperature=0.1,
        )
        data: dict[str, Any] = parse_json_maybe_fenced(text)
        data["elapsed_seconds"] = round(time.time() - started, 2)
    finally:
        if remove_compressed:
            compressed.unlink(missing_ok=True)
    data["video"] = video_path.name
    data["duration"] = get_duration_seconds(video_path)
    out = output_dir / f"score_{video_path.stem}.json"
    write_json(out, data)
    print(f"评分 JSON 已保存：{out}")
    return out
