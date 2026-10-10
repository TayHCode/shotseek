import csv
import json
import re
import shlex
import unittest
from tests.support import ROOT, validate_schema
from shotseek.cli import build_parser


class Docs(unittest.TestCase):
    def test_readme_sections_and_wording(self):
        text = (ROOT / "README.md").read_text()
        headings = re.findall(r"^## (.+)$", text, re.M)
        self.assertEqual(headings, ["What you can ask for", "Requirements", "Quickstart (about ten minutes)", "Connect your agent", "B-roll for a talking-head video", "Using a GPU", "Where your media can live", "What it stores and what it never does", "Commands", "Limitations and not in this version", "What has been verified", "Related tools", "Third-party components and licenses", "License"])
        normalized = " ".join(text.split())
        self.assertIn("shotseek has been tested on a desktop with an NVIDIA RTX-class GPU.", normalized)
        self.assertIn("It runs on CPU by default and does not need a GPU; add `--device cuda` to use one.", normalized)
        for path in ("LICENSE", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md", "docs/storage.md", "docs/output.md", "docs/how-it-works.md", "agents/README.md", ".github/ISSUE_TEMPLATE/bug_report.yml", ".github/ISSUE_TEMPLATE/feature_request.yml"):
            self.assertTrue((ROOT / path).is_file())

    def test_commands_and_examples(self):
        for path in [ROOT / "README.md", *(ROOT / "docs").glob("*.md")]:
            for block in re.findall(r"```[^\n]*\n(.*?)```", path.read_text(), re.S):
                for line in block.splitlines():
                    if line.strip().startswith("shotseek "):
                        build_parser().parse_args(shlex.split(line.strip())[1:])
        for path in (ROOT / "docs/examples").glob("*.json"):
            validate_schema(json.loads(path.read_text()), path.stem)

    def test_beat_example_ids_agree(self):
        folder = ROOT / "docs/examples"
        beats = json.loads((folder / "broll.json").read_text())["beats"]
        with (folder / "broll.csv").open(newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual({row["beat_id"] for row in rows}, {beat["id"] for beat in beats})
