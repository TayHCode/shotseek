import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from tests.support import Sandbox
from shotseek.paths import writable, ensure_index, display_path, contained
from shotseek.errors import AppError


class Paths(Sandbox):
    def alias_stat(self, inode=42, alias_inode=None):
        original = Path.stat
        alias = self.base / "MEDIA"
        def stat(path, *args, **kwargs):
            if path in (self.library, alias):
                return SimpleNamespace(st_dev=17,
                    st_ino=alias_inode if path == alias and alias_inode is not None else inode)
            return original(path, *args, **kwargs)
        return alias, patch("pathlib.Path.stat", stat)

    @unittest.skipIf(os.name == "nt", "POSIX spelling on a case-insensitive mount")
    def test_case_alias_overlap_and_write_boundary(self):
        from shotseek import config
        alias, mocked = self.alias_stat()
        with mocked:
            self.assertTrue(contained(alias / "new" / "report.csv", self.library))
            with self.assertRaises(AppError) as error:
                writable(alias / "report.csv", [str(self.library)])
            self.assertEqual(error.exception.code, "output_inside_library")
            with self.assertRaises(AppError) as error:
                config.validate({"library": [dict(name="one", root=str(self.library)),
                    dict(name="two", root=str(alias / "nested"))]})
            self.assertEqual(error.exception.code, "library_overlap")

    @unittest.skipIf(os.name == "nt", "POSIX spelling on a case-insensitive mount")
    def test_missing_inode_does_not_alias_distinct_roots(self):
        alias, mocked = self.alias_stat(inode=0)
        alias.mkdir()
        with mocked:
            self.assertFalse(contained(alias / "report.csv", self.library))

    @unittest.skipIf(os.name == "nt", "POSIX spelling on a case-insensitive mount")
    def test_case_alias_with_provider_assigned_or_missing_inodes(self):
        for inode, alias_inode in ((42, 75), (0, 0)):
            alias, mocked = self.alias_stat(inode, alias_inode)
            with mocked:
                # The provider accepts both names, but its directory listing
                # has only the canonical entry, as GVfs does for SMB aliases.
                self.assertTrue(contained(alias / "new" / "report.csv", self.library))
                with self.assertRaises(AppError):
                    writable(alias / "report.csv", [str(self.library)])

    @unittest.skipIf(os.name == "nt", "POSIX spelling on a case-sensitive mount")
    def test_distinct_case_and_unicode_entries_remain_distinct(self):
        import unicodedata
        from shotseek import config
        if (self.base / "MEDIA").exists():
            self.skipTest("Requires case-sensitive storage")
        for name in ("MEDIA", "caf\u00e9", unicodedata.normalize("NFD", "caf\u00e9")):
            folder = self.base / name
            folder.mkdir()
        data = config.validate({"library": [dict(name="a", root=str(self.base / "caf\u00e9")),
            dict(name="b", root=str(self.base / unicodedata.normalize("NFD", "caf\u00e9")))]})
        self.assertEqual(len(data["library"]), 2)
        self.assertFalse(contained(self.base / "MEDIA", self.library))

    @unittest.skipIf(os.name == "nt", "POSIX spelling on a case-insensitive mount")
    def test_unverified_case_alias_cannot_bypass_write_guard(self):
        from contextlib import nullcontext
        for listing in (OSError("Disconnected directory"),
                nullcontext(iter(SimpleNamespace(name="other") for _ in range(10001)))):
            alias, mocked = self.alias_stat(alias_inode=75)
            options = dict(side_effect=listing) if isinstance(listing, OSError) else dict(return_value=listing)
            with mocked, patch("shotseek.paths.os.scandir", **options):
                with self.assertRaises(AppError) as error:
                    writable(alias / "report.csv", [str(self.library)])
                self.assertEqual(error.exception.code, "library_unreachable")

    def test_guards_and_symlinks(self):
        libraries = [dict(root=str(self.library))]
        for path in (self.library, self.library / "new", self.library / "file.csv"):
            with self.assertRaises(AppError):
                writable(path, libraries)
        link = self.base / "link"
        link.symlink_to(self.library, target_is_directory=True)
        with self.assertRaises(AppError):
            writable(link / "file.csv", libraries)
        code, doc, _ = self.cli("init", "--library", "media=" + str(self.library), "--index-dir", self.library / "index")
        self.assertEqual(code, 2)
        self.assertEqual(doc["error"]["code"], "index_inside_library")

    def test_marker(self):
        ensure_index(self.index)
        self.assertEqual(json.loads((self.index / "index.json").read_text())["format_version"], 1)
        ensure_index(self.index)
        foreign = self.base / "foreign"
        foreign.mkdir()
        (foreign / "keep.txt").write_text("keep")
        with self.assertRaises(AppError) as error:
            ensure_index(foreign)
        self.assertEqual(error.exception.code, "index_dir_not_empty")
        self.assertEqual((foreign / "keep.txt").read_text(), "keep")

    def test_display(self):
        library = dict(root=str(self.library), display_root="G:\\My Drive\\Media")
        self.assertEqual(display_path(library, "cafe/mug.jpg")[1], "G:\\My Drive\\Media\\cafe\\mug.jpg")
        library["display_root"] = "/mnt/nas/media"
        self.assertEqual(display_path(library, "cafe/mug.jpg")[1], "/mnt/nas/media/cafe/mug.jpg")

    def test_index_cannot_contain_library(self):
        with self.assertRaises(AppError) as error:
            writable(self.base, [dict(root=str(self.library))], "index_inside_library")
        self.assertEqual(error.exception.code, "index_inside_library")

    def test_extended_windows_drive_unc_and_existing_prefix(self):
        from shotseek.paths import windows_extended
        for ordinary, expected in [
            ("C:\\Media\\café ☕.jpg", "\\\\?\\C:\\Media\\café ☕.jpg"),
            ("\\\\media-share\\photos\\mug.jpg", "\\\\?\\UNC\\media-share\\photos\\mug.jpg"),
        ]:
            self.assertEqual(windows_extended(ordinary), expected)
            self.assertEqual(windows_extended(expected), expected)

    @unittest.skipUnless(os.name == "nt", "Windows filesystem integration")
    def test_deep_unicode_library_with_legacy_long_path_policy(self):
        from tests.support import make_image
        from shotseek.paths import filesystem_path
        import shutil
        self.addCleanup(shutil.rmtree, filesystem_path(self.library))
        folder = self.library
        for i in range(7):
            folder = folder / ("generated-mug-" + str(i) + "a" * 30)
        photo = filesystem_path(folder / "café ☕.jpg")
        make_image(photo, "red")
        self.assertEqual(self.cli("init", "--library", "media=" + str(self.library))[0], 0)
        code, result, _ = self.cli("index", "--strict")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["totals"]["files_indexed"], 1)
        self.assertTrue(result["libraries"][0]["walk_complete"])
        code, result, _ = self.cli("search", "red", "--include-blank")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["queries"][0]["results"][0]["filename"], "café ☕.jpg")
