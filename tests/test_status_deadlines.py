import json
import os
import subprocess
import sys
import time
from tests.test_indexer import IndexCase
from tests.support import make_image, validate_schema


CHILD = """
import sys, time
from pathlib import Path
from tests import support
from shotseek.cli import main
target, operation = sys.argv[1:3]
original = getattr(Path, operation)
def slow(path, *args, **kwargs):
    if str(path) == target:
        time.sleep(60)
    return original(path, *args, **kwargs)
setattr(Path, operation, slow)
sys.argv[1:] = ['status']
raise SystemExit(main())
"""


class StatusDeadlines(IndexCase):
    def setUp(self):
        super().setUp()
        make_image(self.library / "mug.jpg", "red")
        self.index_run()

    def stalled(self, target, operation):
        started = time.monotonic()
        done = subprocess.run([sys.executable, "-c", CHILD, str(target), operation],
                              env=dict(os.environ, **self.env), capture_output=True, text=True, timeout=3)
        self.assertLess(time.monotonic() - started, 3)
        return done.returncode, json.loads(done.stdout)

    def test_stalled_library_stat_returns_local_counts(self):
        code, result = self.stalled(self.library, "is_dir")
        self.assertEqual(code, 0, result)
        self.assertTrue(result["index"]["searchable"])
        self.assertFalse(result["libraries"][0]["reachable"])
        self.assertEqual(result["libraries"][0]["files"]["indexed"], 1)
        self.assertIn("library_unreachable", [w["code"] for w in result["warnings"]])
        validate_schema(result, "status")

    def test_stalled_path_resolution_has_bounded_error(self):
        code, result = self.stalled(self.library, "resolve")
        self.assertEqual(code, 4, result)
        self.assertEqual(result["error"]["code"], "storage_stalled")
        validate_schema(result, "error")

    def test_stalled_index_metadata_has_bounded_error(self):
        code, result = self.stalled(self.index, "stat")
        self.assertEqual(code, 4, result)
        self.assertEqual(result["error"]["code"], "storage_stalled")
        validate_schema(result, "error")
