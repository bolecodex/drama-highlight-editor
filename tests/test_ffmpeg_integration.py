import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from drama_cut.compose import compose
from drama_cut.export import export_platform
from drama_cut.ffmpeg_utils import get_duration_seconds, get_video_info
from drama_cut.utils import write_json


def make_test_video(path: Path, color: str, freq: int = 440, duration: float = 2.0) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=320x240:d={duration}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={freq}:duration={duration}",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


class FfmpegIntegrationTest(unittest.TestCase):
    def setUp(self):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("ffmpeg/ffprobe not available")

    def test_compose_two_segments(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            video_dir = root / "videos"
            out_dir = root / "out"
            video_dir.mkdir()
            make_test_video(video_dir / "ep01.mp4", "red", 440)
            make_test_video(video_dir / "ep02.mp4", "blue", 660)
            analysis = {
                "drama_name": "demo",
                "episodes": ["ep01.mp4", "ep02.mp4"],
                "total_source_duration_seconds": 4,
                "summary": "demo",
                "hook": {"enabled": False},
                "segments_to_keep": [
                    {"id": 1, "source_file": "ep01.mp4", "start_time": "00:00:00", "end_time": "00:00:01", "duration_seconds": 1, "content": "a", "why_keep": "a"},
                    {"id": 2, "source_file": "ep02.mp4", "start_time": "00:00:00", "end_time": "00:00:01", "duration_seconds": 1, "content": "b", "why_keep": "b"},
                ],
                "segments_to_remove": [],
                "final_structure": {"description": "x", "estimated_duration_seconds": 2, "segment_order": [{"type": "keep", "id": 1}, {"type": "keep", "id": 2}]},
            }
            analysis_path = write_json(root / "analysis.json", analysis)
            output = compose(analysis_path, video_dir, out_dir, name="demo", normalize_audio=False, crossfade=0.2, allow_risky=True)
            self.assertTrue(output.exists())
            self.assertGreater(get_duration_seconds(output), 1.5)

    def test_compose_strict_preflight_blocks_risky_recap(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            video_dir = root / "videos"
            out_dir = root / "out"
            video_dir.mkdir()
            make_test_video(video_dir / "ep01.mp4", "red", 440)
            make_test_video(video_dir / "ep02.mp4", "blue", 660)
            analysis = {
                "drama_name": "demo",
                "episodes": ["ep01.mp4", "ep02.mp4"],
                "total_source_duration_seconds": 4,
                "summary": "demo",
                "hook": {"enabled": False},
                "segments_to_keep": [
                    {"id": 1, "source_file": "ep01.mp4", "start_time": "00:00:00", "end_time": "00:00:01", "duration_seconds": 1, "content": "a", "why_keep": "a"},
                    {"id": 2, "source_file": "ep02.mp4", "start_time": "00:00:00", "end_time": "00:00:01", "duration_seconds": 1, "content": "b", "why_keep": "b"},
                ],
                "segments_to_remove": [],
                "final_structure": {"description": "x", "estimated_duration_seconds": 2, "segment_order": [{"type": "keep", "id": 1}, {"type": "keep", "id": 2}]},
            }
            analysis_path = write_json(root / "analysis.json", analysis)
            with self.assertRaises(RuntimeError):
                compose(analysis_path, video_dir, out_dir, name="demo", normalize_audio=False)
            self.assertTrue((out_dir / "qa_analysis.json").exists())

    def test_export_platform_resolution(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            video = root / "input.mp4"
            out_dir = root / "exports"
            make_test_video(video, "green", 330)
            outputs = export_platform(video, out_dir, "moments", durations=[1], method="crop")
            self.assertEqual(len(outputs), 1)
            info = get_video_info(outputs[0])
            self.assertEqual((info["width"], info["height"]), (1080, 1080))


if __name__ == "__main__":
    unittest.main()
