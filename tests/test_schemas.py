import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from drama_cut.schemas import HighlightAnalysis, validate_analysis_file
from drama_cut.utils import write_json


def valid_payload():
    return {
        "drama_name": "demo",
        "episodes": ["ep01.mp4", "ep02.mp4"],
        "total_source_duration_seconds": 4,
        "summary": "demo summary",
        "hook": {"enabled": False},
        "segments_to_keep": [
            {
                "id": 1,
                "source_file": "ep01.mp4",
                "start_time": "00:00:00",
                "end_time": "00:00:01",
                "duration_seconds": 1,
                "content": "start",
                "why_keep": "main plot",
            },
            {
                "id": 2,
                "source_file": "ep02.mp4",
                "start_time": "00:00:00",
                "end_time": "00:00:01",
                "duration_seconds": 1,
                "content": "next",
                "why_keep": "main plot",
            },
        ],
        "segments_to_remove": [],
        "final_structure": {
            "description": "ordered",
            "estimated_duration_seconds": 2,
            "segment_order": [{"type": "keep", "id": 1}, {"type": "keep", "id": 2}],
        },
    }


class SchemaTest(unittest.TestCase):
    def test_valid_payload(self):
        analysis = HighlightAnalysis.model_validate(valid_payload())
        self.assertEqual(len(analysis.segments_to_keep), 2)

    def test_bad_time_range(self):
        payload = valid_payload()
        payload["segments_to_keep"][0]["end_time"] = "00:00:00"
        with self.assertRaises(ValidationError):
            HighlightAnalysis.model_validate(payload)

    def test_unknown_segment_order_id(self):
        payload = valid_payload()
        payload["final_structure"]["segment_order"] = [{"type": "keep", "id": 99}]
        with self.assertRaises(ValidationError):
            HighlightAnalysis.model_validate(payload)

    def test_validate_source_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            video_dir = root / "videos"
            video_dir.mkdir()
            (video_dir / "ep01.mp4").write_bytes(b"")
            (video_dir / "ep02.mp4").write_bytes(b"")
            path = write_json(root / "analysis.json", valid_payload())
            self.assertEqual(validate_analysis_file(path, video_dir).drama_name, "demo")


if __name__ == "__main__":
    unittest.main()
