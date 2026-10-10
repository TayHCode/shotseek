import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
import unittest
from tests.support import Sandbox, make_image, validate_schema


CHILD = """
import sys, time
from pathlib import Path
from tests import support
import shotseek.indexer as ix
from shotseek.embed.fake import FakeEmbedder
from shotseek.store.db import Store
from shotseek.cli import main
ready, release, phase = sys.argv[1:4]
sys.argv[1:] = ['index', '--workers', '1', '--progress', 'none']
old_load, old_images, old_checkpoint = ix.load, FakeEmbedder.images, Store.checkpoint
held = False
def hold():
    global held
    if held:
        return
    held = True
    Path(ready).touch()
    deadline = time.monotonic() + 60
    while not Path(release).exists():
        if time.monotonic() > deadline:
            raise RuntimeError('Signal test did not release checkpoint')
        time.sleep(.005)
def slow_load(*args):
    time.sleep(.008)
    return old_load(*args)
def images(self, *args):
    if phase == 'embedding':
        hold()
    return old_images(self, *args)
def checkpoint(self, *args, **kwargs):
    if phase == 'transaction':
        kwargs['fault'] = lambda step: hold() if step == 'transaction' else None
    return old_checkpoint(self, *args, **kwargs)
ix.load, FakeEmbedder.images, Store.checkpoint = slow_load, images, checkpoint
raise SystemExit(main())
"""


@unittest.skipUnless(os.name == "posix", "POSIX signal delivery is required")
class CheckpointSignals(Sandbox):
    def check_signal(self, sig):
        for phase, count in (("embedding", 160), ("transaction", 160), ("embedding", 3)):
            with self.subTest(phase=phase, files=count):
                case = self.base / f"{phase}-{count}"
                library, index = case / "media", case / "index"
                for i in range(count):
                    make_image(library / f"{i:04d}.jpg", "red")
                self.env.update(SHOTSEEK_CONFIG=str(case / "config.toml"), SHOTSEEK_INDEX_DIR=str(index))
                self.assertEqual(self.cli("init", "--library", "media=" + str(library))[0], 0)
                ready, release = case / "ready", case / "release"
                child = subprocess.Popen([sys.executable, "-c", CHILD, str(ready), str(release), phase],
                                         env=dict(os.environ, **self.env), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    deadline = time.monotonic() + 60
                    while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
                        time.sleep(.01)
                    if not ready.exists():
                        if child.poll() is None:
                            child.kill()
                        stdout, stderr = child.communicate()
                        self.fail(f"Checkpoint was not reached (exit {child.returncode}): {stdout} {stderr}")
                    child.send_signal(sig)
                    release.touch()
                    stdout, stderr = child.communicate(timeout=60)
                finally:
                    if child.poll() is None:
                        child.kill()
                        child.communicate()
                result = json.loads(stdout)
                self.assertEqual(child.returncode, 130, (result, stderr))
                self.assertEqual(result["status"], "interrupted")
                self.assertEqual(result["stop_reason"], "signal")
                validate_schema(result, "index")
                with sqlite3.connect(index / "meta.sqlite") as db:
                    self.assertEqual(db.execute("SELECT status,stop_reason FROM runs ORDER BY id DESC LIMIT 1").fetchone(), ("interrupted", "signal"))
                self.assertEqual(self.cli("search", "red")[0], 0)
                code, resumed, _ = self.cli("index")
                self.assertEqual(code, 0, resumed)
                self.assertEqual(resumed["index"]["files"], count)
                with sqlite3.connect(index / "meta.sqlite") as db:
                    self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM frames").fetchone()[0], count)
                    self.assertEqual(dict(db.execute("SELECT key,value FROM kv"))["dead_rows"], "0")

    def test_sigint_at_checkpoint(self):
        self.check_signal(signal.SIGINT)

    def test_sigterm_at_checkpoint(self):
        self.check_signal(signal.SIGTERM)
