import re
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
from tests.support import ROOT, repo_files


MANIFEST_LICENSE_URLS = {"https://" + "github.com/" + project + "/blob/" + branch + "/LICENSE"
                        for project, branch in (
    ("OpenNMT/CTranslate2", "master"),
    ("google/flatbuffers", "master"),
    ("huggingface/tokenizers", "main"),
)}


WINDOWS_RUNTIME_URL = "https://" + "aka.ms/vc14/vc_redist.x64.exe"


def violations(path):
    rel = path.relative_to(ROOT).as_posix()
    if path.is_symlink():
        return [(rel, 1, "symlink")]
    data = path.read_bytes()
    hits = []
    if len(data) > 200 * 1024:
        hits.append((rel, 1, "size"))
    if b"\0" in data:
        hits.append((rel, 1, "binary"))
    banned_ext = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif", ".avif", ".tiff", ".bmp", ".mp4", ".mov", ".wav", ".mp3", ".zip", ".gz", ".tar", ".whl", ".bin", ".pt", ".f16"}
    if path.suffix.lower() in banned_ext:
        hits.append((rel, 1, "extension"))
    patterns = {
        "mount": "/" + "mnt" + r"/[a-zA-Z]/",
        "home": r"/(?:ho" + r"me|Use" + r"rs)/(?!you(?:/|\b))[^/\s]+|[A-Z]:\\Use" + r"rs\\(?!you\\)[^\\\s]+",
        "address": r"[\w.+-]+" + chr(64) + r"[\w.-]+\.[A-Za-z]{2,}",
        "unfinished": "|".join(["TO" + "DO", "FIX" + "ME", "X" * 3]),
    }
    allowed = {"pytorch.org", "download.pytorch.org", "huggingface.co", "ffmpeg.org", "keepachangelog.com", "semver.org", "json-schema.org", "python.org",
        "docs.astral.sh", "astral.sh", "www.osxexperts.net", "www.gyan.dev", "johnvansickle.com",
        "support.google.com"}
    for number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
        for rule, pattern in patterns.items():
            if re.search(pattern, line):
                hits.append((rel, number, rule))
        for ip in re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", line):
            if ip not in {"127.0.0.1", "0.0.0.0"}:
                hits.append((rel, number, "ip"))
        for url in re.findall(r'https?://[^\s<>"\)]+', line):
            parsed = urlsplit(url)
            valid = parsed.hostname in allowed or (parsed.hostname == "github.com" and any(parsed.path.startswith("/" + p) for p in ("mlfoundations/open_clip", "SYSTRAN/faster-whisper")))
            if rel == "release-check.json" and url in MANIFEST_LICENSE_URLS:
                valid = True
            if rel in {"README.md", "docs/platforms.md"} and url == WINDOWS_RUNTIME_URL:
                valid = True
            if not valid:
                hits.append((rel, number, "url"))
    return hits


class Hygiene(unittest.TestCase):
    def test_license_evidence_urls_are_exact_and_manifest_only(self):
        for url in MANIFEST_LICENSE_URLS:
            for rel, value, rejected in (
                ("release-check.json", url, False),
                ("README.md", url, True),
                ("release-check.json", url + "?other", True),
                ("release-check.json", url.removesuffix("LICENSE") + "README.md", True),
            ):
                with self.subTest(path=rel, value=value), patch(
                    "pathlib.Path.read_bytes", return_value=value.encode()
                ):
                    self.assertEqual(bool(violations(ROOT / rel)), rejected)

    def test_windows_runtime_url_is_exact_and_install_docs_only(self):
        for rel, value, rejected in (
            ("README.md", WINDOWS_RUNTIME_URL, False),
            ("docs/platforms.md", WINDOWS_RUNTIME_URL, False),
            ("docs/other.md", WINDOWS_RUNTIME_URL, True),
            ("README.md", WINDOWS_RUNTIME_URL + "?other", True),
            ("README.md", WINDOWS_RUNTIME_URL.replace("vc_redist.x64.exe", "other.exe"), True),
        ):
            with self.subTest(path=rel, value=value), patch(
                "pathlib.Path.read_bytes", return_value=value.encode()
            ):
                self.assertEqual(bool(violations(ROOT / rel)), rejected)

    def test_files(self):
        hits = [hit for path in repo_files() for hit in violations(path)]
        self.assertFalse(hits, "\n".join(f"{p}:{n}: {r}" for p, n, r in hits))
