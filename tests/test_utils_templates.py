import unittest
from pathlib import Path

from drama_cut.templates import get_template_meta, list_templates, load_template
from drama_cut.utils import natural_sort_video_paths, parse_json_maybe_fenced, sanitize_name


class UtilsAndTemplatesTest(unittest.TestCase):
    def test_natural_sort_video_paths(self):
        paths = [Path("Episode10.mp4"), Path("Episode2.mp4"), Path("Episode1.mp4")]
        self.assertEqual([p.name for p in natural_sort_video_paths(paths)], ["Episode1.mp4", "Episode2.mp4", "Episode10.mp4"])

    def test_parse_json_maybe_fenced(self):
        self.assertEqual(parse_json_maybe_fenced("```json\n{\"ok\": true}\n```"), {"ok": True})

    def test_sanitize_name(self):
        self.assertEqual(sanitize_name(" a/b c "), "a_b_c")

    def test_templates_available(self):
        ids = {item["id"] for item in list_templates()}
        self.assertIn("default", ids)
        self.assertIn("content_clean", ids)
        self.assertEqual(get_template_meta("conflict")["file"], "conflict.txt")
        self.assertIn("JSON", load_template("default"))


if __name__ == "__main__":
    unittest.main()
