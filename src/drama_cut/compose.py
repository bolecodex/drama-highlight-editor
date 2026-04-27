from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .ffmpeg_utils import get_duration_seconds, has_audio_stream, require_binary, run_command, time_to_seconds
from .review import has_blocking_issues, preflight_analysis, report_summary
from .schemas import HighlightAnalysis, load_analysis
from .utils import sanitize_name


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


def cut_segment_precise(
    source_video: Path,
    start_time: str,
    end_time: str,
    output_path: Path,
    reencode: bool = True,
    fade_in: float = 0.0,
    fade_out: float = 0.0,
) -> Path:
    require_binary("ffmpeg")
    start_sec = time_to_seconds(start_time)
    end_sec = time_to_seconds(end_time)
    duration = end_sec - start_sec
    if duration <= 0:
        raise ValueError(f"片段时间范围无效：{start_time}-{end_time}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not reencode:
        run_command(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(start_sec),
                "-i",
                str(source_video),
                "-t",
                str(duration),
                "-c",
                "copy",
                "-avoid_negative_ts",
                "make_zero",
                str(output_path),
            ],
            desc=f"切片 {source_video.name} {start_time}->{end_time}",
        )
        return output_path

    trim_v = f"trim=start={start_sec}:end={end_sec},setpts=PTS-STARTPTS,setsar=1"
    vf_parts = [trim_v]
    if fade_in > 0:
        vf_parts.append(f"fade=t=in:st=0:d={fade_in}")
    if fade_out > 0:
        vf_parts.append(f"fade=t=out:st={max(0, duration - fade_out)}:d={fade_out}")
    vf = ",".join(vf_parts)

    if has_audio_stream(source_video):
        trim_a = f"atrim=start={start_sec}:end={end_sec},asetpts=PTS-STARTPTS"
        af_parts = [trim_a]
        if fade_in > 0:
            af_parts.append(f"afade=t=in:st=0:d={fade_in}")
        if fade_out > 0:
            af_parts.append(f"afade=t=out:st={max(0, duration - fade_out)}:d={fade_out}")
        af = ",".join(af_parts)
        args = [
            "ffmpeg",
            "-y",
            "-i",
            str(source_video),
            "-filter_complex",
            f"[0:v]{vf}[v];[0:a]{af}[a]",
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    else:
        args = [
            "ffmpeg",
            "-y",
            "-i",
            str(source_video),
            "-filter_complex",
            f"[0:v]{vf}[v]",
            "-map",
            "[v]",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    run_command(args, desc=f"切片 {source_video.name} {start_time}->{end_time}")
    return output_path


def concat_standard(segment_files: list[Path], output_path: Path, normalize_audio: bool = True) -> Path:
    require_binary("ffmpeg")
    if not segment_files:
        raise ValueError("没有可合并的片段文件")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if len(segment_files) == 1:
        if normalize_audio and has_audio_stream(segment_files[0]):
            run_command(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(segment_files[0]),
                    "-c:v",
                    "copy",
                    "-af",
                    "loudnorm=I=-16:TP=-1.5:LRA=11",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    str(output_path),
                ],
                desc=f"音频响度归一化 -> {output_path.name}",
            )
        else:
            shutil.copy2(segment_files[0], output_path)
        return output_path

    all_have_audio = all(has_audio_stream(path) for path in segment_files)
    inputs: list[str] = []
    for segment in segment_files:
        inputs.extend(["-i", str(segment)])
    if all_have_audio:
        streams = "".join(f"[{i}:v:0][{i}:a:0]" for i in range(len(segment_files)))
        af_chain = ",loudnorm=I=-16:TP=-1.5:LRA=11" if normalize_audio else ""
        filter_str = (
            streams
            + f"concat=n={len(segment_files)}:v=1:a=1[outv][outa_raw];"
            + f"[outa_raw]aformat=sample_rates=48000:channel_layouts=stereo{af_chain}[outa]"
        )
        args = [
            "ffmpeg",
            "-y",
            *inputs,
            "-filter_complex",
            filter_str,
            "-map",
            "[outv]",
            "-map",
            "[outa]",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    else:
        streams = "".join(f"[{i}:v:0]" for i in range(len(segment_files)))
        filter_str = streams + f"concat=n={len(segment_files)}:v=1:a=0[outv]"
        args = [
            "ffmpeg",
            "-y",
            *inputs,
            "-filter_complex",
            filter_str,
            "-map",
            "[outv]",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    run_command(args, desc=f"合并 {len(segment_files)} 个片段 -> {output_path.name}")
    return output_path


def concat_crossfade(
    segment_files: list[Path],
    output_path: Path,
    crossfade: float,
    normalize_audio: bool = True,
) -> Path:
    if crossfade <= 0 or len(segment_files) < 2:
        return concat_standard(segment_files, output_path, normalize_audio)
    durations = [get_duration_seconds(path) for path in segment_files]
    min_duration = min(durations)
    if min_duration <= 0:
        return concat_standard(segment_files, output_path, normalize_audio)
    d = min(crossfade, max(0.05, min_duration / 3))
    if d <= 0:
        return concat_standard(segment_files, output_path, normalize_audio)

    all_have_audio = all(has_audio_stream(path) for path in segment_files)
    inputs: list[str] = []
    for segment in segment_files:
        inputs.extend(["-i", str(segment)])

    filter_lines: list[str] = []
    cumulative = 0.0
    prev_v = "[0:v]"
    prev_a = "[0:a]" if all_have_audio else None
    for idx in range(1, len(segment_files)):
        cumulative += durations[idx - 1] - d
        out_v = "[outv]" if idx == len(segment_files) - 1 else f"[v{idx}]"
        filter_lines.append(
            f"{prev_v}[{idx}:v]xfade=transition=fade:duration={d:.3f}:offset={cumulative:.3f}{out_v}"
        )
        prev_v = out_v
        if all_have_audio and prev_a is not None:
            out_a = "[outa_raw]" if idx == len(segment_files) - 1 else f"[a{idx}]"
            filter_lines.append(f"{prev_a}[{idx}:a]acrossfade=d={d:.3f}{out_a}")
            prev_a = out_a

    if all_have_audio:
        if normalize_audio:
            filter_lines.append("[outa_raw]loudnorm=I=-16:TP=-1.5:LRA=11[outa]")
            audio_map = "[outa]"
        else:
            audio_map = "[outa_raw]"
        args = [
            "ffmpeg",
            "-y",
            *inputs,
            "-filter_complex",
            ";".join(filter_lines),
            "-map",
            "[outv]",
            "-map",
            audio_map,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    else:
        args = [
            "ffmpeg",
            "-y",
            *inputs,
            "-filter_complex",
            ";".join(filter_lines),
            "-map",
            "[outv]",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    run_command(args, desc=f"交叉淡化合并 {len(segment_files)} 个片段 -> {output_path.name}")
    return output_path


def _process_order(
    analysis: HighlightAnalysis,
    video_dir: Path,
    temp_dir: Path,
    reencode: bool,
    suffix: str = "",
) -> list[Path]:
    by_id = {segment.id: segment for segment in analysis.segments_to_keep}
    output_files: list[Path] = []
    for idx, entry in enumerate(analysis.final_structure.segment_order):
        if entry.type == "hook":
            if not analysis.hook.enabled:
                continue
            assert analysis.hook.source_file and analysis.hook.source_start and analysis.hook.source_end
            src = resolve_source_path(analysis.hook.source_file, video_dir)
            output_files.append(
                cut_segment_precise(
                    src,
                    analysis.hook.source_start,
                    analysis.hook.source_end,
                    temp_dir / f"seg{suffix}_hook.mp4",
                    reencode=reencode,
                )
            )
        else:
            segment = by_id.get(entry.id or -1)
            if segment is None:
                raise ValueError(f"segment_order 引用了缺失的片段 id：{entry.id}")
            src = resolve_source_path(segment.source_file, video_dir)
            output_files.append(
                cut_segment_precise(
                    src,
                    segment.start_time,
                    segment.end_time,
                    temp_dir / f"seg{suffix}_{segment.id:03d}.mp4",
                    reencode=reencode,
                )
            )
    return output_files


def compose(
    analysis_json: Path,
    video_dir: Path,
    output_dir: Path,
    name: str | None = None,
    reencode: bool = True,
    crossfade: float = 0.0,
    normalize_audio: bool = True,
    strict_preflight: bool = True,
    allow_risky: bool = False,
) -> Path:
    if strict_preflight:
        report = preflight_analysis(analysis_json, video_dir, output_dir)
        if has_blocking_issues(report) and not allow_risky:
            report_path = report.get("report_path", output_dir / f"qa_{analysis_json.stem}.json")
            raise RuntimeError(
                f"{report_summary(report)}。已保存报告：{report_path}。"
                "请先运行 drama-cut 精修 或人工修正 JSON；确认风险后可传 --allow-risky。"
            )
    analysis = load_analysis(analysis_json)
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = sanitize_name(name or analysis.drama_name)
    if safe_name.startswith("promo_"):
        safe_name = safe_name[len("promo_") :]
    output_path = output_dir / f"promo_{safe_name}.mp4"
    with tempfile.TemporaryDirectory(prefix="drama_cut_segments_", dir=str(output_dir)) as td:
        temp_dir = Path(td)
        cut_files = _process_order(analysis, video_dir, temp_dir, reencode)
        concat_crossfade(cut_files, output_path, crossfade, normalize_audio)
    print(f"输出成片：{output_path}")
    return output_path
