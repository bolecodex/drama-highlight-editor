from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mpeg", ".mpg", ".webm", ".avi", ".mkv"}


def natural_sort_key(path: Path) -> list[Any]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", path.stem)]


def natural_sort_video_paths(paths: list[Path]) -> list[Path]:
    return sorted(paths, key=natural_sort_key)


def list_video_files(input_path: Path) -> list[Path]:
    if input_path.is_file() and input_path.suffix.lower() in VIDEO_EXTENSIONS:
        return [input_path]
    if not input_path.is_dir():
        raise FileNotFoundError(f"Input is not a video file or directory: {input_path}")
    videos = [p for p in input_path.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS]
    return natural_sort_video_paths(videos)


def strip_json_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def parse_json_maybe_fenced(text: str) -> Any:
    return json.loads(strip_json_fence(text))


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return path


def sanitize_name(name: str) -> str:
    name = name.strip() or "drama"
    return re.sub(r'[\\/:*?"<>|\s]+', "_", name).strip("_") or "短剧"
