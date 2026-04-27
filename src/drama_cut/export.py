from __future__ import annotations

import json
from pathlib import Path

from .ffmpeg_utils import get_video_info, require_binary, run_command
from .utils import write_json

PLATFORM_PRESETS: dict[str, dict] = {
    "douyin": {"name": "抖音/快手", "aspect": "9:16", "width": 1080, "height": 1920, "durations": [15, 30, 60], "bitrate": "4M", "fps": 30},
    "wechat_video": {"name": "微信视频号", "aspect": "9:16", "width": 1080, "height": 1920, "durations": [30, 60, 180], "bitrate": "4M", "fps": 30},
    "wechat_34": {"name": "微信视频号 3:4", "aspect": "3:4", "width": 1080, "height": 1440, "durations": [30, 60], "bitrate": "3500k", "fps": 30},
    "toutiao": {"name": "头条/穿山甲", "aspect": "16:9", "width": 1920, "height": 1080, "durations": [60, 120, 180], "bitrate": "5M", "fps": 30},
    "moments": {"name": "朋友圈广告", "aspect": "1:1", "width": 1080, "height": 1080, "durations": [15, 30], "bitrate": "3M", "fps": 30},
}


def build_resize_filter(src_w: int, src_h: int, dst_w: int, dst_h: int, method: str = "crop") -> str:
    src_ratio = src_w / src_h
    dst_ratio = dst_w / dst_h
    if method == "stretch":
        return f"scale={dst_w}:{dst_h}"
    if method == "scale":
        return f"scale={dst_w}:{dst_h}:force_original_aspect_ratio=decrease,pad={dst_w}:{dst_h}:(ow-iw)/2:(oh-ih)/2:black"
    if src_ratio > dst_ratio:
        return f"scale=-2:{dst_h},crop={dst_w}:{dst_h}:(iw-ow)/2:0"
    return f"scale={dst_w}:-2,crop={dst_w}:{dst_h}:0:(ih-oh)/2"


def export_platform(
    video_path: Path,
    output_dir: Path,
    platform: str,
    durations: list[int] | None = None,
    method: str = "crop",
) -> list[Path]:
    require_binary("ffmpeg")
    preset = PLATFORM_PRESETS[platform]
    output_dir.mkdir(parents=True, exist_ok=True)
    info = get_video_info(video_path)
    vf = build_resize_filter(info["width"], info["height"], preset["width"], preset["height"], method=method)
    outputs = []
    for max_duration in durations or preset["durations"]:
        actual_duration = min(float(max_duration), max(float(info["duration"]), 0.01))
        label = f"{int(max_duration)}s" if info["duration"] > max_duration * 0.8 else "full"
        out = output_dir / f"{video_path.stem}_{platform}_{label}.mp4"
        run_command(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-t",
                str(actual_duration),
                "-vf",
                vf,
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-b:v",
                preset["bitrate"],
                "-r",
                str(preset["fps"]),
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-ar",
                "44100",
                "-movflags",
                "+faststart",
                str(out),
            ],
            desc=f"导出 {preset['name']} {label}",
        )
        outputs.append(out)
    return outputs


def export_all(video_path: Path, output_dir: Path, platforms: list[str] | None = None, method: str = "crop") -> Path:
    platforms = platforms or list(PLATFORM_PRESETS)
    results = {}
    for platform in platforms:
        if platform not in PLATFORM_PRESETS:
            raise KeyError(f"未知平台：{platform}")
        results[platform] = [str(p) for p in export_platform(video_path, output_dir, platform, method=method)]
    manifest = {"source": str(video_path), "exports": results}
    path = output_dir / f"{video_path.stem}_exports.json"
    write_json(path, manifest)
    print(f"导出清单：{path}")
    return path
