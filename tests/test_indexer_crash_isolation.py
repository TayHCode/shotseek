import json
import os
import subprocess
import sys
from tests.test_indexer import IndexCase
from tests.support import make_video, make_image
from shotseek.media import load
from shotseek.store.db import Store
from shotseek.store.inflight import DecodeJournal
from shotseek.walker import Entry


CHILD = """
import os
from tests import support
import shotseek.indexer as indexer
from shotseek.cli import main
original = indexer.load

def loader(entry, settings):
    if entry.path.name == 'suspect.mp4':
        os._exit(23)
    return original(entry, settings)

indexer.load = loader
raise SystemExit(main(['index', '--workers', '1', '--progress', 'none']))
"""


class Recovery(IndexCase):
    def test_decoder_crash_retries_with_separate_reader(self):
        for name, color in [("suspect", "red"), ("other", "green"), ("last", "blue")]:
            make_video(self.library / (name + ".mp4"), [(color, 6)])
        done = subprocess.run([sys.executable, "-c", CHILD], env=dict(os.environ, **self.env),
                              capture_output=True, timeout=30)
        self.assertEqual(done.returncode, 23)
        journal = self.index / "inflight.jsonl"
        records = [json.loads(line) for line in journal.read_text().splitlines()]
        suspects = {record["relpath"] for record in records}
        self.assertIn("suspect.mp4", suspects)
        observed = {}

        def loader(entry, settings):
            observed[entry.relpath] = settings["frame_reader"]
            return load(entry, settings)

        resumed = self.index_run(loader=loader)
        self.assertEqual(resumed["index"]["files"], 3)
        self.assertEqual(resumed["totals"]["failed"], 0)
        for name in suspects:
            self.assertEqual(observed[name], "ffmpeg")
        self.assertFalse(journal.exists())
        self.assertEqual(self.index_run()["totals"]["files_indexed"], 0)

    def test_recovery_limit(self):
        path = make_video(self.library / "suspect.mp4", [("red", 6)])
        self.index_run()
        stat = path.stat()
        entry = Entry(path, path.name, "video", ".mp4", stat.st_size, stat.st_mtime_ns)
        with Store(self.index, write=True) as store:
            for _ in range(2):
                journal = DecodeJournal(self.index, self.data["library"])
                journal.add("media", entry)
                journal.recover(store, store.start_run("cpu"))
        journal = DecodeJournal(self.index, self.data["library"])
        journal.add("media", entry)
        result = self.index_run(loader=lambda *a: self.fail("Third automatic retry was attempted"))
        self.assertEqual(result["totals"]["files_indexed"], 0)
        with Store(self.index) as store:
            self.assertEqual(store.files()[0]["fail_count"], 3)
        self.assertEqual(self.index_run("--retry-failed")["totals"]["files_indexed"], 1)

    def test_per_library_cap_and_resume(self):
        extra = self.base / "extra"
        extra.mkdir()
        self.data["library"].append(dict(name="extra", root=str(extra), exclude=[], display_root=""))
        for root in (self.library, extra):
            for i in range(4):
                make_image(root / f"mug{i}.jpg", "red")
        first = self.index_run("--max-files-per-library", "2")
        self.assertEqual(first["status"], "partial")
        self.assertEqual(first["stop_reason"], "max_files")
        self.assertEqual([s["indexed"] for s in first["libraries"]], [2, 2])
        self.assertEqual(first["totals"]["removed"], 0)
        self.assertEqual(self.index_run()["totals"]["files_indexed"], 4)
