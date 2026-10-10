import tomllib
import unittest
from tests.support import ROOT
from shotseek.names import NAME


class Packaging(unittest.TestCase):
    def test_metadata(self):
        data = tomllib.loads((ROOT / "pyproject.toml").read_text())
        p = data["project"]
        self.assertEqual(p["name"], NAME)
        self.assertEqual(p["scripts"], {NAME: NAME + ".cli:main"})
        self.assertEqual(p["license"], "MIT")
        self.assertEqual(p["requires-python"], ">=3.11")
        self.assertEqual(len(p["dependencies"]), 9)
        self.assertIn("torchvision>=0.17", p["dependencies"])
        self.assertIn("opencv-python-headless>=4.10", p["dependencies"])
        self.assertEqual(p["authors"], [{"name": "TayHCode"}])
        self.assertFalse({"maintainers", "urls", "email"} & p.keys())
        self.assertEqual(data["tool"]["setuptools"]["package-data"][NAME], ["agent/guide.md", "schemas/*.json"])
        self.assertTrue((ROOT / "src" / NAME / "agent/guide.md").is_file())
        self.assertEqual(len(list((ROOT / "src" / NAME / "schemas").glob("*.json"))), 12)
        self.assertIn("2026 TayHCode", (ROOT / "LICENSE").read_text())
