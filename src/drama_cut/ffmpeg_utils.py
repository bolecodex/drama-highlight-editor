from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


def require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"需要 {name}，但当前 PATH 中未找到。")
    return path


def run_command(args: list[str], desc: str | None = None, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    if desc:
        print(desc)
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        tail = (result.stderr or result.stdout)[-1200:]
        raise RuntimeError(f"命令执行失败（{args[0]}）：{tail}")
    return result


def ffprobe_json(path: Path, extra_args: list[str] | None = None) -> dict:
    require_binary("ffprobe")
    args = ["ffprobe", "-v", "quiet", "-of", "json"]
    if extra_args:
        args.extend(extra_args)
    args.append(str(path))
    result = run_command(args)
    return json.loads(result.stdout or "{}")


def get_video_info(path: Path) -> dict:
    data = ffprobe_json(
        path,
        ["-show_entries", "stream=width,height,r_frame_rate,codec_type:format=duration", "-select_streams", "v:0"],
    )
    stream = (data.get("streams") or [{}])[0]
    fmt = data.get("format") or {}
    fps = 30.0
    fps_str = stream.get("r_frame_rate") or "30/1"
    try:
        num, den = fps_str.split("/")
        fps = float(num) / float(den)
    except (ValueError, ZeroDivisionError):
        pass
    return {
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "duration": float(fmt.get("duration") or 0),
        "fps": fps,
    }


def has_audio_stream(path: Path) -> bool:
    data = ffprobe_json(path, ["-show_entries", "stream=codec_type", "-select_streams", "a"])
    return bool(data.get("streams"))


def get_duration_seconds(path: Path) -> float:
    data = ffprobe_json(path, ["-show_entries", "format=duration"])
    return float((data.get("format") or {}).get("duration") or 0)


def time_to_seconds(value: str) -> float:
    parts = value.strip().split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def seconds_to_hms(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
