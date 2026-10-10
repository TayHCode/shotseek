import os
from unittest.mock import patch
from tests.support import Sandbox, make_library, make_image
from shotseek.cli import build_parser
from shotseek.config import validate, write
from shotseek.embed.fake import FakeEmbedder
from shotseek.indexer import run
from shotseek.store.db import Store
from shotseek.errors import AppError


class IndexCase(Sandbox):
    def setUp(self):
        super().setUp()
        self.data = validate({"library": [dict(name="media", root=str(self.library))], "index": {"dir": str(self.index)}})
        write(self.config, self.data)
        self.environ = patch.dict(os.environ, self.env)
        self.environ.start()
        self.addCleanup(self.environ.stop)

    def index_run(self, *options, **kwargs):
        args = build_parser().parse_args(["index", "--progress", "none", *options])
        return run(args, self.data, self.index, embedder=FakeEmbedder(), **kwargs)


class Indexing(IndexCase):
    def test_compact_before_first_index_preserves_first_use(self):
        from shotseek.paths import ensure_index
        make_image(self.library / "mug.jpg", "red")
        for state in ("missing", "empty", "marker"):
            with self.subTest(state=state):
                index = self.base / state
                if state == "empty":
                    index.mkdir()
                elif state == "marker":
                    ensure_index(index)
                before = {p.name: p.read_bytes() for p in index.iterdir()} if index.exists() else None
                code, result, _ = self.cli("compact", "--index-dir", index)
                self.assertEqual(code, 3, result)
                self.assertEqual(result["error"]["code"], "index_not_found")
                self.assertTrue(result["error"]["hint"])
                after = {p.name: p.read_bytes() for p in index.iterdir()} if index.exists() else None
                self.assertEqual(after, before)
                self.assertFalse(self.cli("status", "--index-dir", index)[1]["index"]["exists"])
                self.assertEqual(self.cli("index", "--index-dir", index)[0], 0)
                self.assertEqual(self.cli("search", "red", "--index-dir", index)[0], 0)

    def test_empty_and_failed_media_have_top_level_warnings(self):
        result = self.index_run()
        self.assertIn("no_media_found", [w["code"] for w in result["warnings"]])
        make_image(self.library / "unreadable.jpg", "red")
        def unreadable(*args):
            raise PermissionError()
        result = self.index_run(loader=unreadable)
        self.assertEqual(result["totals"]["failed"], 1)
        self.assertEqual(result["_exit"], 0)
        self.assertIn("files_failed", [w["code"] for w in result["warnings"]])

    def test_full_incremental_and_retry(self):
        make_library(self.library)
        first = self.index_run()
        self.assertEqual(first["totals"], dict(files_indexed=9, vectors_added=10, failed=3, removed=0))
        self.assertEqual(first["libraries"][0]["unsupported"], 1)
        def no_read(*unused):
            self.fail("Unchanged file was opened")
        second = self.index_run(loader=no_read)
        self.assertEqual(second["totals"]["files_indexed"], 0)
        self.assertEqual(second["totals"]["failed"], 0)
        retried = self.index_run("--retry-failed", "--strict")
        self.assertEqual(retried["_exit"], 8)
        self.assertEqual(retried["error"]["code"], "files_failed")

    def test_partial_resume_change_delete(self):
        for i in range(5):
            make_image(self.library / f"mug{i}.jpg", "red")
        partial = self.index_run("--max-files", "3")
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(partial["totals"]["files_indexed"], 3)
        with Store(self.index) as reader:
            self.assertEqual(reader.snapshot()[1].shape, (3, 8))
        full = self.index_run()
        self.assertEqual(full["totals"]["files_indexed"], 2)
        path = self.library / "mug0.jpg"
        make_image(path, "green", size=(1000, 800))
        self.assertEqual(self.index_run()["totals"]["files_indexed"], 1)
        path.unlink()
        self.assertEqual(self.index_run()["totals"]["removed"], 1)
        with Store(self.index) as store:
            self.assertEqual(store.kv()["dead_rows"], 2)
            self.assertEqual(len(store.files()), 4)

    def test_mass_prune_and_missing_root(self):
        for i in range(105):
            make_image(self.library / f"mug{i}.jpg", "red")
        self.index_run()
        for path in self.library.iterdir():
            path.unlink()
        deferred = self.index_run()
        self.assertTrue(deferred["libraries"][0]["prune_deferred"])
        self.assertEqual(self.index_run("--prune-missing")["totals"]["removed"], 105)
        make_image(self.library / "mug.jpg", "red")
        self.index_run()
        self.library.rename(self.base / "unmounted")
        absent = self.index_run()
        self.assertEqual(absent["_exit"], 4)
        self.assertEqual(absent["index"]["files"], 1)

    def test_rebuild_model_lock_and_status(self):
        make_image(self.library / "mug.jpg", "red")
        self.index_run()
        with self.assertRaises(AppError) as error:
            self.index_run("--rebuild")
        self.assertEqual(error.exception.code, "confirmation_required")
        with Store(self.index, write=True) as store:
            with self.assertRaises(AppError) as error:
                self.index_run()
            self.assertEqual(error.exception.exit_code, 5)
            self.assertTrue(self.cli("status")[1]["run"]["active"])
        with Store(self.index, write=True) as store:
            with store.db:
                store.set("model_id", "different")
        with self.assertRaises(AppError) as error:
            self.index_run()
        self.assertEqual(error.exception.code, "index_model_mismatch")
        self.assertEqual(self.index_run("--rebuild", "--yes")["totals"]["files_indexed"], 1)
        status = self.cli("status")[1]
        self.assertFalse(status["run"]["active"])
        self.assertEqual(status["last_run"]["status"], "complete")

    def test_time_budget_and_size_mode(self):
        make_image(self.library / "mug.jpg", "red")
        self.assertEqual(self.index_run("--time-budget", ".000001")["status"], "partial")
        self.index_run()
        self.data["indexing"]["change_detection"] = "size"
        os.utime(self.library / "mug.jpg", (100, 100))
        self.assertEqual(self.index_run()["totals"]["files_indexed"], 0)

    def test_incomplete_walk_preserves_missing_rows(self):
        make_image(self.library / "cafe/mug.jpg", "red")
        make_image(self.library / "product/mug.jpg", "blue")
        self.index_run()
        original = os.scandir
        def unreadable(path):
            if str(path).endswith("cafe"):
                raise PermissionError()
            return original(path)
        with patch("shotseek.walker.os.scandir", unreadable):
            result = self.index_run()
        self.assertFalse(result["libraries"][0]["walk_complete"])
        self.assertEqual((result["status"], result["_exit"]), ("aborted", 4))
        self.assertEqual(result["error"]["code"], "library_unreachable")
        self.assertIn("library_unreachable", [w["code"] for w in result["warnings"]])
        self.assertEqual(result["totals"]["removed"], 0)
        self.assertEqual(result["index"]["files"], 2)
        self.assertIn("index_incomplete", [w["code"] for w in self.cli("search", "red")[1]["warnings"]])

    def test_missing_one_root_preserves_its_rows(self):
        extra = self.base / "extra"
        extra.mkdir()
        make_image(extra / "mug.jpg", "blue")
        make_image(self.library / "mug.jpg", "red")
        self.data["library"].append(dict(name="extra", root=str(extra), display_root="", exclude=[]))
        self.index_run()
        extra.rename(self.base / "unmounted")
        result = self.index_run()
        self.assertEqual(result["_exit"], 4)
        self.assertEqual(result["status"], "aborted")
        self.assertEqual(result["index"]["files"], 2)
        self.assertIn("library_unreachable", [w["code"] for w in result["warnings"]])
