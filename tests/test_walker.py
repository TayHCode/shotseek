import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from tests.support import Sandbox, make_image
from shotseek.config import DEFAULTS
from shotseek.walker import walk, classify


class Walker(Sandbox):
    def test_classify_and_skip(self):
        for name in ("mug.JPG", "cafe.MP4", "mug.CR2"):
            self.assertIsNotNone(classify(name))
        self.assertIsNone(classify("notes.txt"))
        for name in ("cafe/mug.jpg", "._photo.jpg", ".hidden/mug.jpg", "@eaDir/mug.jpg", "skip/mug.jpg"):
            make_image(self.library / name, "red")
        state = {}
        entries = list(walk(dict(root=str(self.library), exclude=["skip*"]), DEFAULTS["indexing"], state))
        self.assertEqual([x.relpath for x in entries], ["cafe/mug.jpg"])
        self.assertTrue(state["walk_complete"])

    def test_streaming_and_listing_error(self):
        make_image(self.library / "mug.jpg", "red")
        (self.library / "blocked").mkdir()
        original = os.scandir
        visited = []
        def scan(path):
            visited.append(path)
            if str(path).endswith("blocked"):
                raise PermissionError()
            return original(path)
        state = {}
        with patch("shotseek.walker.os.scandir", scan):
            iterator = walk(dict(root=str(self.library)), DEFAULTS["indexing"], state)
            self.assertEqual(next(iterator).relpath, "mug.jpg")
            self.assertEqual(len(visited), 1)
            list(iterator)
        self.assertFalse(state["walk_complete"])
        self.assertEqual(state["listing_errors"], 1)

    def test_loop(self):
        make_image(self.library / "mug.jpg", "red")
        (self.library / "loop").symlink_to(self.library, target_is_directory=True)
        state = {}
        entries = list(walk(dict(root=str(self.library)), dict(DEFAULTS["indexing"], follow_symlinks=True), state))
        self.assertEqual(len(entries), 1)

    def test_zero_inode_mount_traverses_distinct_folders_and_stops_alias_loop(self):
        make_image(self.library / "one/mug.jpg", "red")
        make_image(self.library / "two/mug.jpg", "blue")
        (self.library / "loop").symlink_to(self.library, target_is_directory=True)
        original = Path.stat
        def stat(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            return SimpleNamespace(st_dev=value.st_dev, st_ino=0)
        state = {}
        with patch("pathlib.Path.stat", stat):
            entries = list(walk(dict(root=str(self.library)),
                dict(DEFAULTS["indexing"], follow_symlinks=True), state))
        self.assertEqual({e.relpath for e in entries}, {"one/mug.jpg", "two/mug.jpg"})
        self.assertTrue(state["walk_complete"])

    def test_file_symlinks_obey_follow_symlinks_setting(self):
        target = make_image(self.base / "outside.jpg", "red")
        (self.library / "alias.jpg").symlink_to(target)
        state = {}
        self.assertEqual(list(walk(dict(root=str(self.library)), DEFAULTS["indexing"], state)), [])
        self.assertTrue(state["walk_complete"])
        entries = list(walk(dict(root=str(self.library)),
            dict(DEFAULTS["indexing"], follow_symlinks=True), {}))
        self.assertEqual([e.relpath for e in entries], ["alias.jpg"])
