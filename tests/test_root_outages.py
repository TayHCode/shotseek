import os
import subprocess
import sys
import threading
from unittest.mock import patch
from tests.test_indexer import IndexCase
from tests.support import make_image, validate_schema
from shotseek.cli import build_parser, envelope
from shotseek.indexer import run
from shotseek.media import load
from shotseek.store.db import Store
from shotseek.walker import Discovery, walk


class RootOutages(IndexCase):
    def assert_search_warning(self):
        code, result, _ = self.cli("search", "red", "--include-blank")
        self.assertEqual(code, 0)
        self.assertGreater(result["queries"][0]["returned"], 0)
        self.assertIn("library_unreachable", [w["code"] for w in result["warnings"]])
        validate_schema(result, "search")
        text = subprocess.run([sys.executable, "-m", "shotseek", "search", "red",
            "--include-blank", "--format", "text"], env=dict(os.environ, **self.env),
            capture_output=True, text=True, timeout=60)
        self.assertEqual(text.returncode, 0)
        self.assertIn("photo.jpg", text.stdout)
        self.assertIn("unavailable", text.stderr.lower())

    def assert_outage(self, result):
        self.assertEqual((result["_exit"], result["status"]), (4, "aborted"))
        self.assertFalse(result["libraries"][0]["reachable"])
        self.assertFalse(result["libraries"][0]["walk_complete"])
        self.assertEqual(result["totals"]["removed"], 0)
        notice = next(w for w in result["warnings"] if w["code"] == "library_unreachable")
        self.assertIn("media", notice["message"])
        self.assertIn("folder", notice["message"].lower())
        with Store(self.index) as store:
            self.assertEqual(store.db.execute("SELECT walk_complete FROM runs ORDER BY id DESC LIMIT 1").fetchone()[0], 0)

    def test_root_removed_during_walk(self):
        make_image(self.library / "photo.jpg", "red")
        self.index_run()
        def vanishing(library, settings, state, stop):
            for entry in walk(library, settings, state, stop):
                entry.path.unlink()
                self.library.rmdir()
                yield entry
        with patch("shotseek.walker.walk", vanishing):
            result = self.index_run()
        self.assert_outage(result)
        self.assertEqual(result["index"]["files"], 1)

    def test_root_renamed_during_walk(self):
        make_image(self.library / "photo.jpg", "red")
        self.index_run()
        def vanishing(library, settings, state, stop):
            for entry in walk(library, settings, state, stop):
                self.library.rename(self.base / "moved")
                yield entry
        with patch("shotseek.walker.walk", vanishing):
            result = self.index_run()
        self.assert_outage(result)
        self.assertEqual(result["index"]["files"], 1)

    def test_root_renamed_after_walk_before_decode_finishes(self):
        make_image(self.library / "photo.jpg", "red")
        discoveries = []
        def discover(*args):
            value = Discovery(*args)
            discoveries.append(value)
            return value
        def rename(entry, settings):
            self.assertTrue(discoveries[0].done.wait(10))
            value = load(entry, settings)
            self.library.rename(self.base / "moved")
            return value
        with patch("shotseek.indexer.Discovery", discover):
            result = self.index_run(loader=rename)
        self.assert_outage(result)
        self.assertEqual(result["index"]["files"], 1)
        self.assert_search_warning()

    def test_root_becomes_unreadable_after_walk(self):
        make_image(self.library / "photo.jpg", "red")
        unreadable = threading.Event()
        original = os.scandir
        def scan(path):
            if unreadable.is_set() and str(path) == str(self.library):
                raise PermissionError()
            return original(path)
        def lose_permission(entry, settings):
            value = load(entry, settings)
            unreadable.set()
            return value
        with patch("shotseek.walker.os.scandir", scan):
            result = self.index_run(loader=lose_permission)
        self.assert_outage(result)

    def test_vanished_root_counts_unreached_files_and_recovers_without_retry(self):
        for i in range(8):
            make_image(self.library / f"photo{i}.jpg", "red")
        self.data["indexing"]["workers"] = 1
        reached = []
        def vanish(entry, settings):
            reached.append(entry.relpath)
            value = load(entry, settings)
            self.library.rename(self.base / "moved")
            return value
        result = self.index_run(loader=vanish)
        self.assert_outage(result)
        self.assertEqual(result["totals"]["files_indexed"], 1)
        self.assertEqual(result["totals"]["failed"], 0)
        self.assertEqual(result["totals"]["not_reached"], 7)
        self.assertEqual(result["libraries"][0]["not_reached"], 7)
        self.assertEqual(result["failures_sample"], [])
        self.assertNotIn("files_failed", [w["code"] for w in result["warnings"]])
        notice = next(w for w in result["warnings"] if w["code"] == "files_not_reached")
        self.assertIn("not reached because the folder became unavailable", notice["message"])
        self.assertNotIn("--retry-failed", notice["message"])
        with Store(self.index) as store:
            self.assertEqual(len(store.files()), 1)
        self.assertEqual(self.cli("status")[1]["last_run"]["not_reached"], 7)
        validate_schema(dict(envelope("index"), **{k: v for k, v in result.items() if k != "_exit"}), "index")
        self.base.joinpath("moved").rename(self.library)
        recovered = self.index_run()
        self.assertEqual(recovered["totals"]["files_indexed"], 7)
        self.assertEqual(recovered["totals"]["not_reached"], 0)
        self.assertEqual(recovered["index"]["files"], 8)
        self.assertEqual(recovered["_exit"], 0)

    def test_unreached_changed_rows_preserve_search_and_retry_counts(self):
        for i in range(4):
            make_image(self.library / f"photo{i}.jpg", "red")
        self.index_run()
        for i in range(4):
            make_image(self.library / f"photo{i}.jpg", "blue", size=(128, 96))
        self.data["indexing"]["workers"] = 1
        def vanish(entry, settings):
            value = load(entry, settings)
            self.library.rename(self.base / "moved")
            return value
        result = self.index_run(loader=vanish)
        self.assert_outage(result)
        self.assertEqual(result["totals"]["not_reached"], 3)
        self.assertEqual(result["index"]["files"], 4)
        with Store(self.index) as store:
            self.assertTrue(all(row["status"] == "indexed" and row["fail_count"] == 0
                for row in store.files()))
        self.base.joinpath("moved").rename(self.library)
        self.assertEqual(self.index_run()["libraries"][0]["changed"], 3)

    def test_video_not_reached_is_separate_from_reachable_probe_failure(self):
        (self.library / "clip.mp4").write_bytes(b"not a video")
        def vanish(library, settings, state, stop):
            entries = list(walk(library, settings, state, stop))
            self.library.rename(self.base / "moved")
            yield from entries
        with patch("shotseek.walker.walk", vanish):
            result = self.index_run()
        self.assert_outage(result)
        self.assertEqual(result["totals"]["not_reached"], 1)
        self.assertEqual(result["totals"]["failed"], 0)
        self.assertEqual(result["failures_sample"], [])
        with Store(self.index) as store:
            self.assertEqual(store.files(), [])
        self.base.joinpath("moved").rename(self.library)
        reachable = self.index_run()
        self.assertEqual(reachable["totals"]["not_reached"], 0)
        self.assertEqual(reachable["totals"]["failed"], 1)
        self.assertEqual(reachable["failures_sample"][0]["reason"], "probe_failed")

    def test_old_run_schema_is_readable_and_migrates_on_write(self):
        make_image(self.library / "photo.jpg", "red")
        self.index_run()
        with Store(self.index, write=True) as store:
            store.db.execute("ALTER TABLE runs DROP COLUMN not_reached")
        status = self.cli("status")[1]
        self.assertEqual(status["last_run"]["not_reached"], 0)
        validate_schema(status, "status")
        self.assertEqual(self.index_run()["totals"]["not_reached"], 0)
        self.assertEqual(self.cli("status")[1]["last_run"]["not_reached"], 0)

    def test_failed_first_attempt_recovers_as_new(self):
        make_image(self.library / "photo.jpg", "red")
        def fail(*args):
            raise OSError()
        self.index_run(loader=fail)
        recovered = self.index_run()
        self.assertEqual((recovered["libraries"][0]["new"], recovered["libraries"][0]["changed"]), (1, 0))
        make_image(self.library / "photo.jpg", "blue", size=(128, 96))
        changed = self.index_run()
        self.assertEqual((changed["libraries"][0]["new"], changed["libraries"][0]["changed"]), (0, 1))

    def test_unchanged_rerun_does_not_load_model_or_media(self):
        make_image(self.library / "photo.jpg", "red")
        self.index_run()
        args = build_parser().parse_args(["index", "--progress", "none"])
        with patch("shotseek.indexer.get_embedder", side_effect=AssertionError("Model loaded")), patch("shotseek.indexer.load", side_effect=AssertionError("Media loaded")):
            result = run(args, self.data, self.index)
        self.assertEqual(result["_exit"], 0)
        self.assertEqual(result["libraries"][0]["unchanged"], 1)

    def test_search_warns_when_complete_index_root_is_missing(self):
        make_image(self.library / "photo.jpg", "red")
        self.index_run()
        self.library.rename(self.base / "moved")
        self.assert_search_warning()
