import threading
import time
import errno
import os
from pathlib import Path
from unittest.mock import patch
from tests.test_indexer import IndexCase
from tests.support import make_image
from shotseek.media import load
from shotseek.paths import filesystem_path
from shotseek.store.db import Store


class SlowStorage(IndexCase):
    def setUp(self):
        super().setUp()
        self.data["indexing"].update(file_timeout_seconds=.5, workers=1)
        self.release = threading.Event()
        self.addCleanup(self.release.set)

    def blocked(self, *unused):
        self.release.wait()
        raise OSError()

    def test_one_lost_worker(self):
        make_image(self.library / "mug.jpg", "red")
        start = time.monotonic()
        result = self.index_run(loader=self.blocked)
        self.assertLess(time.monotonic() - start, 10)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["failures_sample"][0]["reason"], "timeout")

    def test_five_lost_workers(self):
        for i in range(7):
            make_image(self.library / f"mug{i}.jpg", "red")
        result = self.index_run(loader=self.blocked)
        self.assertEqual(result["status"], "aborted")
        self.assertEqual(result["stop_reason"], "storage_stalled")
        self.assertEqual(result["_exit"], 4)
        with Store(self.index) as store:
            self.assertEqual(store.kv()["vector_rows"], 0)

    def test_read_error_and_retry(self):
        make_image(self.library / "mug.jpg", "red")
        def fail(*unused):
            raise OSError()
        result = self.index_run(loader=fail)
        self.assertEqual(result["failures_sample"][0]["reason"], "read_error")
        self.assertEqual(self.index_run()["totals"]["files_indexed"], 1)

    def test_mid_index_photo_io_error_preserves_results_and_resumes(self):
        for name in ("first.jpg", "delayed.jpg", "last.jpg"):
            make_image(self.library / name, "red")
        original = Path.read_bytes
        def read(path):
            if path.name == "delayed.jpg":
                raise OSError(errno.EIO, "Unavailable media")
            return original(path)
        with patch("pathlib.Path.read_bytes", read):
            result = self.index_run("--strict")
        self.assertEqual(result["_exit"], 8)
        self.assertEqual(result["index"]["files"], 2)
        self.assertEqual(result["failures_sample"][0]["reason"], "read_error")
        self.assertEqual(self.cli("search", "red", "--include-blank")[0], 0)
        resumed = self.index_run()
        self.assertEqual(resumed["totals"]["files_indexed"], 1)
        self.assertEqual(resumed["index"]["files"], 3)
        self.assertEqual(resumed["_exit"], 0)

    def test_interrupt_and_resume(self):
        for i in range(10):
            make_image(self.library / f"mug{i}.jpg", "red")
        stop = threading.Event()
        def once(entry, settings):
            value = load(entry, settings)
            stop.set()
            return value
        result = self.index_run(loader=once, stop=stop, drain_seconds=.1)
        self.assertEqual(result["_exit"], 130)
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(self.index_run()["index"]["files"], 10)

    def test_stalled_directory_walk_respects_budget_and_retains_searchable_rows(self):
        make_image(self.library / "mug.jpg", "red")
        self.index_run()
        original = os.scandir
        def scan(path):
            if filesystem_path(path) == filesystem_path(self.library):
                self.release.wait()
            return original(path)
        start = time.monotonic()
        with patch("shotseek.walker.os.scandir", scan):
            result = self.index_run("--time-budget", ".5")
        self.assertLess(time.monotonic() - start, 10)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["stop_reason"], "time_budget")
        self.assertEqual(result["totals"]["removed"], 0)
        self.assertEqual(result["index"]["files"], 1)
