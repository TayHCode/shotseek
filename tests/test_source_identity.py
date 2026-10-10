"""Copied-source reproducers and bounded-content/visual controls."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from tests.test_indexer import IndexCase
from tests.support import make_video, tree_manifest
from shotseek.names import env
from shotseek.source_identity import content_sample, near_source, source_filter, HASH_BLOCK


class SourceIdentity(IndexCase):
    def test_zero_inode_provider_does_not_exclude_distinct_candidates(self):
        source = self.base / "source.bin"
        source.write_bytes(b"source")
        (self.library / "copy.bin").write_bytes(b"source")
        (self.library / "other.bin").write_bytes(b"other!")
        original = Path.stat
        def stat(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            return SimpleNamespace(st_dev=value.st_dev, st_ino=0, st_size=value.st_size,
                st_mtime_ns=value.st_mtime_ns, st_mode=value.st_mode)
        with patch.object(Path, "stat", stat), patch(
            "shotseek.source_identity.content_sample",
            side_effect=lambda path, expected: hashlib.sha256(path.read_bytes()).hexdigest()
        ):
            accept = source_filter(source, self.data["library"], [], [])
            frame_id = "copy"
            self.assertFalse(accept(dict(file_key=frame_id, library="media", relpath="copy.bin")))
            frame_id = "other"
            self.assertTrue(accept(dict(file_key=frame_id, library="media", relpath="other.bin")))

    def speech(self):
        speech = self.base / "speech.json"
        speech.write_text(json.dumps([dict(start=0, end=6, text="Red ceramic mug at the cafe")]))
        self.env[env("TRANSCRIBER")] = "fake:" + str(speech)

    def test_external_and_in_library_renamed_copies(self):
        self.speech()
        source = make_video(self.library / "source.mp4", segments=[("red", 6)], audio=True)
        outside = self.base / "renamed.mp4"
        shutil.copy2(source, outside)
        shutil.copy2(source, self.library / "SOURCE.MP4")
        make_video(self.library / "cutaway.mp4", segments=[("blue", 6)])
        self.index_run()
        before = tree_manifest(self.library)
        for path in (source, outside):
            with self.subTest(path=path.name):
                code, doc, _ = self.cli("broll", "--aroll", path, "--min-need", "0")
                self.assertEqual(code, 0, doc)
                self.assertIn("aroll_excluded", [w["code"] for w in doc["warnings"]])
                candidates = [c for b in doc["beats"] for c in b["candidates"]]
                self.assertEqual([c["filename"] for c in candidates], ["cutaway.mp4"])
                self.assertTrue(all(hashlib.sha256(Path(c['path']).read_bytes()).digest() != hashlib.sha256(path.read_bytes()).digest() for c in candidates))
        self.assertEqual(tree_manifest(self.library), before)

    def test_reencoded_video_is_labeled_and_excluded(self):
        self.speech()
        source = make_video(self.base / "source.mp4", segments=[("red", 4), ("green", 4), ("blue", 4)], audio=True)
        target = self.library / "renamed.mkv"
        subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(source), "-an", "-vf", "scale=160:120", "-c:v", "libx264", "-threads", "1", "-crf", "30", str(target)], check=True, timeout=30)
        self.assertNotEqual(source.read_bytes(), target.read_bytes())
        make_video(self.library / "cutaway.mp4", segments=[("magenta", 12)])
        self.index_run()
        code, doc, _ = self.cli("broll", "--aroll", source, "--min-need", "0")
        self.assertEqual(code, 0, doc)
        self.assertEqual([c["filename"] for b in doc["beats"] for c in b["candidates"]], ["cutaway.mp4"])
        self.assertTrue(any(w["code"] == "aroll_near_duplicate" and "near-duplicate of the A-roll" in w["message"] for w in doc["warnings"]))

    def test_content_read_is_bounded_and_size_sensitive(self):
        path = self.base / "large.bin"
        path.write_bytes(b"a" * (20 * HASH_BLOCK))
        original = Path.open
        reads = []
        class Reader:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): return self
            def __exit__(self, *args): self.stream.close()
            def __getattr__(self, name): return getattr(self.stream, name)
            def read(self, size):
                reads.append(size)
                return self.stream.read(size)
        with patch.object(Path, "open", lambda p, *a, **k: Reader(original(p, *a, **k))):
            first = content_sample(path, path.stat())
        self.assertEqual(sum(reads), 3 * HASH_BLOCK)
        with path.open("ab") as stream:
            stream.write(b"a")
        self.assertNotEqual(first, content_sample(path, path.stat()))

    def test_visual_threshold_and_bidirectional_coverage(self):
        source = np.eye(3, dtype=np.float32)
        self.assertTrue(near_source(source, source))
        self.assertFalse(near_source(source[:1], source))
        below = np.array([[.98, np.sqrt(1 - .98**2), 0]], dtype=np.float32)
        above = np.array([[.99, np.sqrt(1 - .99**2), 0]], dtype=np.float32)
        self.assertFalse(near_source(below, source[:1]))
        self.assertTrue(near_source(above, source[:1]))
