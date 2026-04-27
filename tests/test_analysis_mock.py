import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from drama_cut.analysis import analyze
from drama_cut.utils import read_json


class FakeArkClient:
    model = "fake-model"

    def __init__(self, *args, **kwargs):
        pass

    def complete(self, content, max_tokens=8192, temperature=0.1):
        return json.dumps(
            {
                "drama_name": "mock",
                "episodes": ["ep01.mp4"],
                "total_source_duration_seconds": 2,
                "summary": "mock summary",
                "hook": {"enabled": False},
                "segments_to_keep": [
                    {
                        "id": 1,
                        "source_file": "ep01.mp4",
                        "start_time": "00:00:00",
                        "end_time": "00:00:01",
                        "duration_seconds": 1,
                        "content": "mock",
                        "why_keep": "main plot",
                    }
                ],
                "segments_to_remove": [],
                "final_structure": {
                    "description": "mock",
                    "estimated_duration_seconds": 1,
                    "segment_order": [{"type": "keep", "id": 1}],
                },
            },
            ensure_ascii=False,
        )


class AnalysisMockTest(unittest.TestCase):
    def test_analyze_with_mock_ark(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            input_dir = root / "videos"
            out_dir = root / "out"
            input_dir.mkdir()
            (input_dir / "ep01.mp4").write_bytes(b"not a real video")
            with patch("drama_cut.analysis.ArkClient", FakeArkClient), patch(
                "drama_cut.analysis.get_duration_seconds", return_value=2.0
            ), patch("drama_cut.analysis.compress_video_for_api", side_effect=lambda p, *_: p), patch(
                "drama_cut.analysis.encode_file_base64", return_value=""
            ):
                path = analyze(input_dir, out_dir, template_id="default", name="mock", auto_refine=False)
            self.assertTrue(path.exists())
            self.assertTrue((out_dir / "highlights_mock_raw.json").exists())
            self.assertEqual(read_json(path)["drama_name"], "mock")


if __name__ == "__main__":
    unittest.main()
