"""External literal-term scan; diagnostics contain locations and counts only."""
import json
import os
from pathlib import Path
import re
import subprocess
import unittest
from tests.support import ROOT, repo_files
from tests.support import env


def read_terms(path):
    if Path(path).resolve().is_relative_to(ROOT):
        raise ValueError("Term input must be outside the repository")
    try:
        text = Path(path).read_text(encoding="utf-8")
        if text.lstrip().startswith(("[", "{")):
            data = json.loads(text)
            if isinstance(data, dict):
                if "terms" in data:
                    data = data["terms"]
                else:
                    values = data["categories"].values()
                    data = [term for value in values for term in (value["terms"] if isinstance(value, dict) else value)]
        else:
            data = text.splitlines()
        if not isinstance(data, list) or any(not isinstance(t, str) for t in data):
            raise ValueError
        data = [t.strip() for t in data if t.strip()]
        if not data:
            raise ValueError
        return data
    except Exception:
        raise ValueError("Term input is missing, unreadable, empty, or invalid") from None


def scan(terms):
    patterns = [re.compile((r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])") if len(t) <= 3 and t.isalnum() else re.escape(t), re.I) for t in terms]
    locations = []
    documents = []
    for path in repo_files():
        relative = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.name
        for pattern in patterns:
            if pattern.search(relative):
                locations.append((relative, 1))
        documents.append((relative, path.read_text(errors="replace")))
    try:
        history = subprocess.check_output(["git", "log", "--all", "--format=%h%x00%an%n%ae%n%cn%n%ce%n%B%x00"], cwd=ROOT).decode().split("\0")
        documents += [(history[i].strip(), history[i + 1]) for i in range(0, len(history) - 1, 2)]
    except (OSError, subprocess.CalledProcessError):
        pass
    if os.environ.get(env("DENYLIST_HISTORY")) == "1":
        objects = subprocess.check_output(
            ["git", "rev-list", "--objects", "--all"], cwd=ROOT
        ).decode().splitlines()
        for entry in objects:
            oid, _, name = entry.partition(" ")
            kind = subprocess.check_output(["git", "cat-file", "-t", oid], cwd=ROOT).strip()
            if kind == b"blob":
                content = subprocess.check_output(["git", "cat-file", "blob", oid], cwd=ROOT)
                documents.append((oid[:12], name + "\n" + content.decode(errors="replace")))
    for path, text in documents:
        for n, line in enumerate(text.splitlines(), 1):
            for pattern in patterns:
                if pattern.search(line):
                    locations.append((path, max(1, n)))
    return locations


class PrivateTerms(unittest.TestCase):
    def test_private_terms(self):
        path = os.environ.get(env("DENYLIST"))
        if not path:
            self.skipTest("set " + env("DENYLIST") + " to a term file outside this repository to run this test")
        try:
            terms = [term for value in path.split(os.pathsep) for term in read_terms(value)]
        except ValueError:
            self.fail("Term input is missing, unreadable, empty, invalid, or inside the repository")
        hits = scan(terms)
        print(f"terms={len(terms)} matches={len(hits)} files={len({p for p, _ in hits})}")
        if hits:
            self.fail("\n".join(f"{p}:{n}" for p, n in sorted(set(hits))))

    def test_literal_boundaries_and_locations(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as directory:
            path = Path(directory) / "sample.txt"
            path.write_text("neutral marker\nabc abcde\n")
            with patch(__name__ + ".repo_files", return_value=[path]), patch(__name__ + ".subprocess.check_output", return_value=b""):
                hits = scan(["neutral marker", "abc"])
            self.assertEqual([number for _, number in hits], [1, 2])

    def test_internal_term_file_rejected(self):
        with self.assertRaises(ValueError):
            read_terms(str(ROOT / "README.md"))
