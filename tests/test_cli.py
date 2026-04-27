import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.test_schemas import valid_payload
from drama_cut.utils import write_json


class CliTest(unittest.TestCase):
    def run_cli(self, *args):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        return subprocess.run(
            [sys.executable, "-m", "drama_cut.cli", *args],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            capture_output=True,
            text=True,
        )

    def test_help(self):
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("produce", result.stdout)

    def test_templates_list(self):
        result = self.run_cli("templates", "list")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("default", result.stdout)

    def test_validate(self):
        with tempfile.TemporaryDirectory() as td:
            path = write_json(Path(td) / "analysis.json", valid_payload())
            result = self.run_cli("validate", str(path))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("校验通过", result.stdout)

    def test_qa_and_refine_help(self):
        result = self.run_cli("预检", "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("投流剪辑预检", result.stdout)
        result = self.run_cli("精修", "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("自动精修切点", result.stdout)


if __name__ == "__main__":
    unittest.main()
