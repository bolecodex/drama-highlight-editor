from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable

from pydantic import ValidationError

from .ffmpeg_utils import get_duration_seconds, require_binary, time_to_seconds
from .schemas import HighlightAnalysis, Segment, load_analysis
from .utils import write_json

ERROR = "error"
WARNING = "warning"
INFO = "info"

SPEECH_FALLBACK_TEXT = "[speech]"
DEFAULT_SCAN_SECONDS = 3.0
RECAP_WINDOW_SECONDS = 24.0
RECAP_VISUAL_THRESHOLD = 0.9


def format_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds - h * 3600 - m * 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def _issue(
    issues: list[dict[str, Any]],
    code: str,
    severity: str,
    message: str,
    segment_id: int | None = None,
    source_file: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    item: dict[str, Any] = {
        "code": code,
        "severity": severity,
        "message": message,
    }
    if segment_id is not None:
        item["segment_id"] = segment_id
    if source_file is not None:
        item["source_file"] = source_file
    if details:
        item["details"] = details
    issues.append(item)


def _fix(
    fixes: list[dict[str, Any]],
    code: str,
    message: str,
    segment_id: int | None = None,
    source_file: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    item: dict[str, Any] = {
        "code": code,
        "message": message,
    }
    if segment_id is not None:
        item["segment_id"] = segment_id
    if source_file is not None:
        item["source_file"] = source_file
    if before:
        item["before"] = before
    if after:
        item["after"] = after
    fixes.append(item)


def has_blocking_issues(report: dict[str, Any]) -> bool:
    return any(item.get("severity") == ERROR for item in report.get("issues", []))


def resolve_source_path(source_file: str, video_dir: Path) -> Path:
    source = Path(source_file)
    if source.is_absolute() and source.exists():
        return source
    candidate = video_dir / source_file
    if candidate.exists():
        return candidate
    basename = video_dir / source.name
    if basename.exists():
        return basename
    raise FileNotFoundError(f"无法在 {video_dir} 下解析 source_file：{source_file}")


def _source_root(input_path: Path) -> Path:
    return input_path if input_path.is_dir() else input_path.parent


def _ordered_segments(analysis: HighlightAnalysis) -> list[Segment]:
    by_id = {segment.id: segment for segment in analysis.segments_to_keep}
    ordered: list[Segment] = []
    for entry in analysis.final_structure.segment_order:
        if entry.type != "keep":
            continue
        segment = by_id.get(entry.id or -1)
        if segment is not None:
            ordered.append(segment)
    if ordered:
        return ordered
    return list(analysis.segments_to_keep)


def _episode_index(analysis: HighlightAnalysis, source_file: str) -> int:
    basename = Path(source_file).name
    for idx, episode in enumerate(analysis.episodes):
        if Path(episode).name == basename:
            return idx
    return len(analysis.episodes)


def _run_ffmpeg(args: list[str]) -> subprocess.CompletedProcess[str]:
    require_binary("ffmpeg")
    return subprocess.run(args, capture_output=True, text=True)


def _frame_gray(video_path: Path, second: float, size: int = 16) -> bytes:
    require_binary("ffmpeg")
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            f"{max(0.0, second):.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-vf",
            f"scale={size}:{size},format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        capture_output=True,
    )
    return result.stdout or b""


def frame_luma(video_path: Path, second: float) -> float | None:
    raw = _frame_gray(video_path, second, size=8)
    if not raw:
        return None
    return sum(raw) / len(raw)


def is_bad_luma(value: float | None) -> bool:
    if value is None:
        return False
    return value <= 12.0 or value >= 242.0


def _ahash(raw: bytes) -> int | None:
    if not raw:
        return None
    avg = sum(raw) / len(raw)
    bits = 0
    for idx, value in enumerate(raw[:256]):
        if value >= avg:
            bits |= 1 << idx
    return bits | (int(avg) << 256)


def frame_hash(video_path: Path, second: float) -> int | None:
    return _ahash(_frame_gray(video_path, second, size=16))


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _hash_similarity(a: int | None, b: int | None) -> float:
    if a is None or b is None:
        return 0.0
    mask = (1 << 256) - 1
    structure = 1.0 - (_hamming(a & mask, b & mask) / 256.0)
    luma_a = a >> 256
    luma_b = b >> 256
    luma_penalty = max(0.0, 1.0 - (abs(luma_a - luma_b) / 64.0))
    return structure * luma_penalty


def sample_hashes(video_path: Path, start: float, end: float, samples: int = 4) -> list[tuple[float, int]]:
    if end <= start:
        return []
    span = end - start
    points = [start + ((idx + 0.5) * span / samples) for idx in range(samples)]
    hashes: list[tuple[float, int]] = []
    for point in points:
        value = frame_hash(video_path, point)
        if value is not None:
            hashes.append((point, value))
    return hashes


def best_visual_similarity(
    left_video: Path,
    left_start: float,
    left_end: float,
    right_video: Path,
    right_start: float,
    right_end: float,
    samples: int = 4,
) -> float:
    left = sample_hashes(left_video, left_start, left_end, samples=samples)
    right = sample_hashes(right_video, right_start, right_end, samples=samples)
    if not left or not right:
        return 0.0
    scores = []
    for _, lh in left:
        scores.append(max(_hash_similarity(lh, rh) for _, rh in right))
    return sum(scores) / len(scores)


def detect_silences(video_path: Path, noise: str = "-35dB", duration: float = 0.25) -> list[tuple[float, float]]:
    result = _run_ffmpeg(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(video_path),
            "-af",
            f"silencedetect=noise={noise}:d={duration}",
            "-f",
            "null",
            "-",
        ]
    )
    text = "\n".join([result.stderr or "", result.stdout or ""])
    starts: list[float] = []
    ranges: list[tuple[float, float]] = []
    for line in text.splitlines():
        if "silence_start:" in line:
            try:
                starts.append(float(line.split("silence_start:")[1].split()[0]))
            except (IndexError, ValueError):
                pass
        elif "silence_end:" in line:
            try:
                end = float(line.split("silence_end:")[1].split()[0])
                start = starts.pop(0) if starts else max(0.0, end - duration)
                ranges.append((start, end))
            except (IndexError, ValueError):
                pass
    video_duration = get_duration_seconds(video_path)
    for start in starts:
        ranges.append((start, video_duration))
    return ranges


def speech_ranges_from_silence(video_path: Path) -> list[dict[str, Any]]:
    video_duration = get_duration_seconds(video_path)
    silences = detect_silences(video_path)
    if not silences:
        return [{"start": 0.0, "end": video_duration, "text": SPEECH_FALLBACK_TEXT, "source": "silence"}]
    ranges: list[dict[str, Any]] = []
    cursor = 0.0
    for start, end in sorted(silences):
        if start - cursor > 0.25:
            ranges.append({"start": cursor, "end": start, "text": SPEECH_FALLBACK_TEXT, "source": "silence"})
        cursor = max(cursor, end)
    if video_duration - cursor > 0.25:
        ranges.append({"start": cursor, "end": video_duration, "text": SPEECH_FALLBACK_TEXT, "source": "silence"})
    return ranges


def _parse_srt_time(value: str) -> float:
    hms, _, ms = value.strip().partition(",")
    parts = hms.split(":")
    if len(parts) != 3:
        return 0.0
    seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    return seconds + (int(ms or "0") / 1000.0)


def _load_srt(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    ranges: list[dict[str, Any]] = []
    for block in re.split(r"\n\s*\n", text):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing = next((line for line in lines if "-->" in line), "")
        if not timing:
            continue
        left, right = [part.strip() for part in timing.split("-->", 1)]
        body = " ".join(line for line in lines if "-->" not in line and not line.isdigit())
        ranges.append({"start": _parse_srt_time(left), "end": _parse_srt_time(right), "text": body, "source": "asr"})
    return ranges


def load_asr_ranges(video_path: Path, analysis_dir: Path | None = None) -> list[dict[str, Any]]:
    dirs = [d for d in [analysis_dir, video_path.parent] if d is not None]
    stems = [f"asr_{video_path.stem}", f"{video_path.stem}_asr"]
    for directory in dirs:
        for stem in stems:
            json_path = directory / f"{stem}.json"
            if json_path.exists():
                try:
                    data = json.loads(json_path.read_text(encoding="utf-8"))
                    utterances = data.get("utterances", data if isinstance(data, list) else [])
                    ranges = []
                    for item in utterances:
                        start = float(item.get("start_time", item.get("start")))
                        end = float(item.get("end_time", item.get("end")))
                        text = str(item.get("text", "")).strip()
                        if end > start:
                            ranges.append({"start": start, "end": end, "text": text, "source": "asr"})
                    if ranges:
                        return ranges
                except (ValueError, TypeError, json.JSONDecodeError):
                    pass
            srt_path = directory / f"{stem}.srt"
            if srt_path.exists():
                ranges = _load_srt(srt_path)
                if ranges:
                    return ranges
    return []


def load_speech_ranges(video_path: Path, analysis_dir: Path | None = None) -> list[dict[str, Any]]:
    ranges = load_asr_ranges(video_path, analysis_dir)
    if ranges:
        return ranges
    return speech_ranges_from_silence(video_path)


def find_range_containing(ranges: Iterable[dict[str, Any]], second: float, margin: float = 0.15) -> dict[str, Any] | None:
    for item in ranges:
        start = float(item["start"])
        end = float(item["end"])
        if start + margin < second < end - margin:
            return item
    return None


def text_repeat_recap_end(
    current_ranges: list[dict[str, Any]],
    previous_ranges: list[dict[str, Any]],
    current_start: float,
    window: float = RECAP_WINDOW_SECONDS,
) -> float | None:
    previous_text = "".join(item.get("text", "") for item in previous_ranges)[-500:]
    if not previous_text or previous_text == SPEECH_FALLBACK_TEXT:
        return None
    repeat_end: float | None = None
    for item in current_ranges:
        start = float(item["start"])
        end = float(item["end"])
        if start < current_start or start > current_start + window:
            continue
        text = str(item.get("text", "")).strip()
        if len(text) >= 2 and text in previous_text:
            repeat_end = max(repeat_end or end, end)
    return repeat_end


def visual_recap_end(
    current_video: Path,
    current_start: float,
    previous_video: Path,
    previous_start: float,
    previous_end: float,
    current_end: float,
) -> float | None:
    search_end = min(current_end, current_start + RECAP_WINDOW_SECONDS)
    prev_window_start = max(previous_start, previous_end - 40.0)
    previous_hashes = sample_hashes(previous_video, prev_window_start, previous_end, samples=6)
    if not previous_hashes:
        return None
    best_end: float | None = None
    point = current_start
    while point < search_end:
        current_hashes = sample_hashes(current_video, point, min(point + 2.0, search_end), samples=2)
        if not current_hashes:
            point += 2.0
            continue
        scores = []
        for _, current_hash in current_hashes:
            scores.append(max(_hash_similarity(current_hash, previous_hash) for _, previous_hash in previous_hashes))
        score = sum(scores) / len(scores)
        if score >= RECAP_VISUAL_THRESHOLD:
            best_end = point + 2.0
        point += 2.0
    return min(best_end, search_end) if best_end is not None else None


def find_safe_start(video_path: Path, start: float, end: float, scan_seconds: float = DEFAULT_SCAN_SECONDS) -> float:
    limit = min(end - 0.5, start + scan_seconds)
    point = start
    while point <= limit:
        if not is_bad_luma(frame_luma(video_path, point)):
            return point
        point += 0.25
    return start


def find_safe_end(video_path: Path, start: float, end: float, scan_seconds: float = DEFAULT_SCAN_SECONDS) -> float:
    limit = max(start + 0.5, end - scan_seconds)
    point = end
    while point >= limit:
        if not is_bad_luma(frame_luma(video_path, max(start, point - 0.04))):
            return point
        point -= 0.25
    return end


def _segment_bounds(segment: Segment) -> tuple[float, float]:
    return time_to_seconds(segment.start_time), time_to_seconds(segment.end_time)


def _set_segment_bounds(segment: Segment, start: float, end: float) -> None:
    segment.start_time = format_time(start)
    segment.end_time = format_time(end)
    segment.duration_seconds = round(max(0.0, end - start), 3)


def _source_durations(analysis: HighlightAnalysis, video_dir: Path) -> dict[str, float]:
    durations: dict[str, float] = {}
    source_files = {segment.source_file for segment in analysis.segments_to_keep}
    if analysis.hook.enabled and analysis.hook.source_file:
        source_files.add(analysis.hook.source_file)
    for source_file in source_files:
        durations[source_file] = get_duration_seconds(resolve_source_path(source_file, video_dir))
    return durations


def _audit_static(
    analysis: HighlightAnalysis,
    video_dir: Path,
    durations: dict[str, float],
    issues: list[dict[str, Any]],
) -> None:
    ordered = _ordered_segments(analysis)
    last_episode = -1
    last_by_source: dict[str, tuple[int, float]] = {}
    for segment in ordered:
        try:
            resolve_source_path(segment.source_file, video_dir)
        except FileNotFoundError as exc:
            _issue(issues, "source_missing", ERROR, str(exc), segment.id, segment.source_file)
            continue
        start, end = _segment_bounds(segment)
        duration = durations.get(segment.source_file)
        if duration is not None and (start < 0 or end > duration + 0.2):
            _issue(
                issues,
                "time_out_of_bounds",
                ERROR,
                "片段时间超出源视频时长",
                segment.id,
                segment.source_file,
                {"start": start, "end": end, "source_duration": duration},
            )
        episode = _episode_index(analysis, segment.source_file)
        if episode < last_episode:
            _issue(issues, "story_order", ERROR, "保留片段跨集顺序倒置", segment.id, segment.source_file)
        last_episode = max(last_episode, episode)
        prev = last_by_source.get(segment.source_file)
        if prev and start < prev[1] - 0.05:
            _issue(
                issues,
                "source_overlap",
                ERROR,
                f"片段与同源片段 {prev[0]} 时间重叠",
                segment.id,
                segment.source_file,
                {"previous_segment_id": prev[0], "previous_end": prev[1], "start": start},
            )
        last_by_source[segment.source_file] = (segment.id, max(end, prev[1] if prev else end))


def build_report(analysis: HighlightAnalysis, video_dir: Path, analysis_dir: Path | None = None) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    fixes: list[dict[str, Any]] = []
    try:
        durations = _source_durations(analysis, video_dir)
    except FileNotFoundError as exc:
        durations = {}
        _issue(issues, "source_missing", ERROR, str(exc))
    _audit_static(analysis, video_dir, durations, issues)
    _audit_recap_and_boundaries(analysis, video_dir, analysis_dir, durations, issues, fixes, mutate=False)
    blocking = sum(1 for item in issues if item.get("severity") == ERROR)
    return {
        "status": "failed" if blocking else "passed",
        "blocking_issue_count": blocking,
        "issue_count": len(issues),
        "fix_count": len(fixes),
        "issues": issues,
        "auto_fixes": fixes,
    }


def preflight_analysis(analysis_json: Path, video_dir: Path, output_dir: Path | None = None) -> dict[str, Any]:
    analysis = load_analysis(analysis_json)
    report = build_report(analysis, video_dir, analysis_json.parent)
    if output_dir is not None:
        out = output_dir / f"qa_{analysis_json.stem}.json"
        write_json(out, report)
        report["report_path"] = str(out)
    return report


def _audit_recap_and_boundaries(
    analysis: HighlightAnalysis,
    video_dir: Path,
    analysis_dir: Path | None,
    durations: dict[str, float],
    issues: list[dict[str, Any]],
    fixes: list[dict[str, Any]],
    mutate: bool,
) -> None:
    ordered = _ordered_segments(analysis)
    speech_cache: dict[str, list[dict[str, Any]]] = {}

    def ranges_for(segment: Segment) -> list[dict[str, Any]]:
        if segment.source_file not in speech_cache:
            speech_cache[segment.source_file] = load_speech_ranges(resolve_source_path(segment.source_file, video_dir), analysis_dir)
        return speech_cache[segment.source_file]

    for idx, segment in enumerate(ordered):
        source_path = resolve_source_path(segment.source_file, video_dir)
        start, end = _segment_bounds(segment)
        source_duration = durations.get(segment.source_file, get_duration_seconds(source_path))
        if end > source_duration:
            new_end = max(start + 0.5, source_duration - 0.05)
            if mutate:
                _set_segment_bounds(segment, start, new_end)
                _fix(
                    fixes,
                    "time_clamped",
                    "片段结尾已收回到源视频时长内",
                    segment.id,
                    segment.source_file,
                    {"end_time": format_time(end)},
                    {"end_time": format_time(new_end)},
                )
                end = new_end
        safe_start = find_safe_start(source_path, start, end)
        if safe_start > start + 0.2:
            _issue(issues, "bad_start_frame", WARNING, "片段开头落在黑屏、闪白或强转场残留上", segment.id, segment.source_file)
            if mutate:
                _set_segment_bounds(segment, safe_start, end)
                _fix(
                    fixes,
                    "safe_start",
                    "片段开头已移到可见剧情帧",
                    segment.id,
                    segment.source_file,
                    {"start_time": format_time(start)},
                    {"start_time": format_time(safe_start)},
                )
                start = safe_start
        safe_end = find_safe_end(source_path, start, end)
        if safe_end < end - 0.2:
            _issue(issues, "bad_end_frame", WARNING, "片段结尾落在黑屏、闪白或强转场残留上", segment.id, segment.source_file)
            if mutate:
                _set_segment_bounds(segment, start, safe_end)
                _fix(
                    fixes,
                    "safe_end",
                    "片段结尾已收回到可见剧情帧",
                    segment.id,
                    segment.source_file,
                    {"end_time": format_time(end)},
                    {"end_time": format_time(safe_end)},
                )
                end = safe_end

        episode_idx = _episode_index(analysis, segment.source_file)
        if episode_idx > 0 and start <= 0.3:
            recap_end: float | None = None
            if idx > 0:
                previous = ordered[idx - 1]
                prev_start, prev_end = _segment_bounds(previous)
                previous_path = resolve_source_path(previous.source_file, video_dir)
                text_end = text_repeat_recap_end(ranges_for(segment), ranges_for(previous), start)
                visual_end = visual_recap_end(source_path, start, previous_path, prev_start, prev_end, end)
                candidates = [value for value in [text_end, visual_end] if value is not None]
                if candidates:
                    recap_end = max(candidates)
            if recap_end is not None and recap_end < end - 1.0:
                _issue(issues, "recap_duplicate", ERROR, "分集开头疑似重复上段前情回顾，已定位可跳过范围", segment.id, segment.source_file)
                if mutate:
                    new_start = min(end - 0.5, recap_end + 0.25)
                    _set_segment_bounds(segment, new_start, end)
                    _fix(
                        fixes,
                        "skip_recap",
                        "集头重复前情已跳过",
                        segment.id,
                        segment.source_file,
                        {"start_time": format_time(start)},
                        {"start_time": format_time(new_start)},
                    )
                    start = new_start
            else:
                _issue(
                    issues,
                    "recap_zero_start_risk",
                    ERROR,
                    "非首个源分集从起点开始，存在前情回顾重复风险；请精修或显式确认",
                    segment.id,
                    segment.source_file,
                )

        ranges = ranges_for(segment)
        end_range = find_range_containing(ranges, end)
        if end_range:
            is_asr = end_range.get("source") == "asr"
            is_final = idx == len(ordered) - 1
            new_end = min(source_duration - 0.05, float(end_range["end"]) + 0.25)
            extension = new_end - end
            should_fix = extension > 0.1 and (is_asr or is_final or extension <= 6.0)
            severity = ERROR if is_asr or is_final else WARNING
            _issue(
                issues,
                "dialogue_cut",
                severity,
                "片段结尾疑似切在台词或连续人声中间",
                segment.id,
                segment.source_file,
                {"end_time": format_time(end), "suggested_end_time": format_time(new_end), "text": end_range.get("text", "")},
            )
            if mutate and should_fix and new_end > start + 0.5:
                _set_segment_bounds(segment, start, new_end)
                _fix(
                    fixes,
                    "extend_dialogue",
                    "片段结尾已延长到台词或人声段结束",
                    segment.id,
                    segment.source_file,
                    {"end_time": format_time(end)},
                    {"end_time": format_time(new_end)},
                )
                end = new_end
        start_range = find_range_containing(ranges, start)
        if start_range and start_range.get("source") == "asr":
            new_start = max(0.0, float(start_range["start"]) - 0.05)
            _issue(
                issues,
                "dialogue_start_cut",
                WARNING,
                "片段开头疑似切在台词中间",
                segment.id,
                segment.source_file,
                {"start_time": format_time(start), "suggested_start_time": format_time(new_start), "text": start_range.get("text", "")},
            )
            if mutate and new_start < end - 0.5:
                _set_segment_bounds(segment, new_start, end)
                _fix(
                    fixes,
                    "expand_dialogue_start",
                    "片段开头已扩展到台词开始前",
                    segment.id,
                    segment.source_file,
                    {"start_time": format_time(start)},
                    {"start_time": format_time(new_start)},
                )

    for left, right in zip(ordered, ordered[1:]):
        left_start, left_end = _segment_bounds(left)
        right_start, right_end = _segment_bounds(right)
        left_path = resolve_source_path(left.source_file, video_dir)
        right_path = resolve_source_path(right.source_file, video_dir)
        score = best_visual_similarity(
            left_path,
            max(left_start, left_end - 8.0),
            left_end,
            right_path,
            right_start,
            min(right_end, right_start + 8.0),
            samples=4,
        )
        if score >= RECAP_VISUAL_THRESHOLD:
            _issue(
                issues,
                "adjacent_visual_duplicate",
                ERROR,
                "相邻片段开头/结尾视觉高度重复",
                right.id,
                right.source_file,
                {"previous_segment_id": left.id, "similarity": round(score, 3)},
            )
            if mutate and right_start + 2.0 < right_end:
                new_start = right_start + 2.0
                _set_segment_bounds(right, new_start, right_end)
                _fix(
                    fixes,
                    "trim_adjacent_duplicate",
                    "相邻重复镜头已向后跳过 2 秒",
                    right.id,
                    right.source_file,
                    {"start_time": format_time(right_start)},
                    {"start_time": format_time(new_start)},
                )


def refine_analysis_data(
    analysis: HighlightAnalysis,
    video_dir: Path,
    analysis_dir: Path | None = None,
) -> HighlightAnalysis:
    refined = analysis.model_copy(deep=True)
    issues: list[dict[str, Any]] = []
    fixes: list[dict[str, Any]] = []
    durations = _source_durations(refined, video_dir)
    _audit_static(refined, video_dir, durations, issues)
    _audit_recap_and_boundaries(refined, video_dir, analysis_dir, durations, issues, fixes, mutate=True)
    # 重新计算时长，避免模型输出与真实切点不一致。
    for segment in refined.segments_to_keep:
        start, end = _segment_bounds(segment)
        segment.duration_seconds = round(max(0.0, end - start), 3)
    refined.final_structure.estimated_duration_seconds = round(sum(segment.duration_seconds or 0 for segment in refined.segments_to_keep), 3)
    # 精修后再跑一遍只读 QA，最终 qa 反映仍需人工确认的问题。
    final_report = build_report(refined, video_dir, analysis_dir)
    final_report["auto_fixes"] = fixes + final_report.get("auto_fixes", [])
    final_report["fix_count"] = len(final_report["auto_fixes"])
    refined.qa = final_report
    return HighlightAnalysis.model_validate(refined.model_dump(exclude_none=True))


def refine_analysis_file(analysis_json: Path, video_dir: Path, output_json: Path | None = None) -> Path:
    try:
        analysis = load_analysis(analysis_json)
    except ValidationError:
        raise
    refined = refine_analysis_data(analysis, video_dir, analysis_json.parent)
    output = output_json or analysis_json.with_name(f"{analysis_json.stem}_refined.json")
    write_json(output, refined.model_dump(exclude_none=True))
    return output


def report_summary(report: dict[str, Any]) -> str:
    status = "通过" if not has_blocking_issues(report) else "失败"
    return f"预检{status}：严重问题 {report.get('blocking_issue_count', 0)} 个，总问题 {report.get('issue_count', 0)} 个，自动修正 {report.get('fix_count', 0)} 个"
