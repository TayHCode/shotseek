import os
import unittest
from tests.test_indexer import IndexCase
from tests.support import make_image, tree_manifest, validate_schema
from shotseek.store.db import Store


class EntryIsolation(IndexCase):
    def check_bad_entry(self, reason):
        make_image(self.library / "safe.jpg", "red")
        make_image(self.library / "café-茶.jpg", "blue")
        before = tree_manifest(self.library)
        code, first, _ = self.cli("index", "--strict")
        self.assertEqual(code, 8, first)
        self.assertEqual(first["status"], "complete")
        self.assertEqual(first["totals"]["files_indexed"], 2)
        self.assertEqual(first["totals"]["failed"], 1)
        self.assertEqual(first["failures_sample"][0]["reason"], reason)
        first["failures_sample"][0]["relative_path"].encode("utf-8")
        validate_schema(first, "index")
        self.assertEqual(tree_manifest(self.library), before)
        make_image(self.library / "later.jpg", "green")
        def no_bad_decode(entry, settings):
            self.assertEqual(entry.relpath, "later.jpg")
            from shotseek.media import load
            return load(entry, settings)
        resumed = self.index_run(loader=no_bad_decode)
        self.assertEqual(resumed["_exit"], 0)
        self.assertEqual(resumed["totals"]["files_indexed"], 1)
        self.assertEqual(resumed["index"]["files"], 3)
        self.assertEqual(resumed["totals"]["failed"], 1)
        self.assertEqual(self.cli("search", "red")[0], 0)
        self.assertEqual(self.cli("status")[1]["last_run"]["failed"], 1)
        with Store(self.index) as store:
            self.assertEqual(store.kv()["vector_rows"], 3)
            self.assertEqual(store.kv()["dead_rows"], 0)
            self.assertEqual(store.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    @unittest.skipUnless(os.name == "posix", "Byte filenames require POSIX")
    def test_byte_filename_is_skipped(self):
        path = make_image(self.library / "bad.jpg", "red")
        os.rename(os.fsencode(path), os.fsencode(self.library) + b"/invalid_\xff.jpg")
        self.check_bad_entry("path_not_utf8")

    def test_future_timestamp_is_skipped(self):
        path = make_image(self.library / "future.jpg", "red")
        stamp = 10413792000000000000
        os.utime(path, ns=(stamp, stamp))
        self.assertGreaterEqual(path.stat().st_mtime_ns, 2**63)
        self.check_bad_entry("metadata_out_of_range")

    def test_invalid_changed_metadata_does_not_prune_saved_work(self):
        path = make_image(self.library / "mug.jpg", "red")
        self.index_run()
        stamp = 10413792000000000000
        os.utime(path, ns=(stamp, stamp))
        result = self.index_run()
        self.assertEqual(result["totals"]["failed"], 1)
        self.assertEqual(result["totals"]["removed"], 0)
        self.assertEqual(result["index"]["files"], 1)
