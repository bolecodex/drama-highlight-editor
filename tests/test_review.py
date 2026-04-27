import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from drama_cut.review import has_blocking_issues, preflight_analysis, refine_analysis_file
from drama_cut.utils import write_json


def make_color_video(path: Path, color: str = "red", duration: float = 4.0) -> None:
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
            f"anullsrc=channel_layout=stereo:sample_rate=44100:d={duration}",
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


def base_analysis() -> dict:
    return {
        "drama_name": "demo",
        "episodes": ["ep01.mp4", "ep02.mp4"],
        "total_source_duration_seconds": 8,
        "summary": "demo",
        "hook": {"enabled": False},
        "segments_to_keep": [
            {"id": 1, "source_file": "ep01.mp4", "start_time": "00:00:00", "end_time": "00:00:02", "duration_seconds": 2, "content": "a", "why_keep": "a"},
            {"id": 2, "source_file": "ep02.mp4", "start_time": "00:00:00", "end_time": "00:00:02", "duration_seconds": 2, "content": "b", "why_keep": "b"},
        ],
        "segments_to_remove": [],
        "final_structure": {"description": "x", "estimated_duration_seconds": 4, "segment_order": [{"type": "keep", "id": 1}, {"type": "keep", "id": 2}]},
    }


class ReviewTest(unittest.TestCase):
    def setUp(self):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("ffmpeg/ffprobe not available")

    def test_preflight_flags_zero_start_recap_risk(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            video_dir = root / "videos"
            out_dir = root / "out"
            video_dir.mkdir()
            make_color_video(video_dir / "ep01.mp4", "red")
            make_color_video(video_dir / "ep02.mp4", "green")
            analysis_path = write_json(root / "analysis.json", base_analysis())
            report = preflight_analysis(analysis_path, video_dir, out_dir)
            self.assertTrue(has_blocking_issues(report))
            self.assertIn("recap_zero_start_risk", {item["code"] for item in report["issues"]})
            self.assertTrue((out_dir / "qa_analysis.json").exists())

    def test_refine_extends_final_dialogue_from_asr(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            video_dir = root / "videos"
            video_dir.mkdir()
            make_color_video(video_dir / "ep01.mp4", "red", duration=4.0)
            analysis = {
                "drama_name": "demo",
                "episodes": ["ep01.mp4"],
                "total_source_duration_seconds": 4,
                "summary": "demo",
                "hook": {"enabled": False},
                "segments_to_keep": [
                    {"id": 1, "source_file": "ep01.mp4", "start_time": "00:00:00", "end_time": "00:00:01.500", "duration_seconds": 1.5, "content": "a", "why_keep": "a"}
                ],
                "segments_to_remove": [],
                "final_structure": {"description": "x", "estimated_duration_seconds": 1.5, "segment_order": [{"type": "keep", "id": 1}]},
            }
            write_json(root / "asr_ep01.json", {"utterances": [{"start_time": 0.0, "end_time": 3.0, "text": "这句话不能切断"}]})
            analysis_path = write_json(root / "analysis.json", analysis)
            refined_path = refine_analysis_file(analysis_path, video_dir, root / "refined.json")
            refined = json.loads(refined_path.read_text(encoding="utf-8"))
            self.assertGreaterEqual(refined["segments_to_keep"][0]["duration_seconds"], 3.0)
            self.assertIn("extend_dialogue", {item["code"] for item in refined["qa"]["auto_fixes"]})


if __name__ == "__main__":
    unittest.main()
