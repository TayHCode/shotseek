"""Cumulative candidate-stall reproduction, isolated from source processing."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from unittest.mock import patch
from tests.test_indexer import IndexCase
from tests.support import make_video
from shotseek.names import env
from shotseek.source_identity import source_filter


class BrollDeadlines(IndexCase):
    def test_twelve_stalled_candidates_share_one_library_deadline(self):
        source = make_video(self.base / "source.mp4", segments=[("red", 6)], audio=True)
        first = make_video(self.library / "clip00.mp4", segments=[("blue", 6)])
        for i in range(1, 12):
            shutil.copy2(first, self.library / f"clip{i:02}.mp4")
        self.index_run()
        fixture = self.base / "speech.json"
        fixture.write_text(json.dumps([dict(start=0, end=6, text="Red ceramic mug on the cafe counter.")]))
        self.env[env("TRANSCRIBER")] = "fake:" + str(fixture)
        script = self.base / "stall.py"

        script.write_text('''import sys,time
from pathlib import Path
from shotseek.cli import main
root,source=sys.argv[1:3]
old=Path.stat
calls=[]
def stat(self,*a,**k):
 if str(self).startswith(root+'/clip'):
  calls.append(str(self));time.sleep(60)
 return old(self,*a,**k)
Path.stat=stat
code=main(['broll','--aroll',source,'--min-need','0'])
print('candidate_probes='+str(len(calls)),file=sys.stderr)
raise SystemExit(code)
''')
        started = time.monotonic()
        done = subprocess.run([sys.executable, str(script), str(self.library), str(source)], env=dict(os.environ, **self.env), capture_output=True, text=True, timeout=15)
        elapsed = time.monotonic() - started
        self.assertEqual(done.returncode, 0, done.stderr)
        doc = json.loads(done.stdout)
        self.assertFalse(any(b["candidates"] for b in doc["beats"]))
        self.assertIn("library_unreachable", [w["code"] for w in doc["warnings"]])
        self.assertIn("candidate_probes=1", done.stderr)
        self.assertLess(elapsed, 15)
        print(f"candidate_stall_seconds={elapsed:.3f} candidate_probes=1")

    def test_slow_successes_also_consume_the_global_budget(self):
        source = self.base / "source.bin"
        source.write_bytes(b"source")
        for i in range(12):
            (self.library / f"clip{i}.bin").write_bytes(b"different")
        with patch("shotseek.source_identity.CANDIDATE_IO_BUDGET", .25):
            accept = source_filter(source, self.data["library"], [], [])
        old = Path.stat
        calls = []
        def stat(path, *args, **kwargs):
            if path.parent == self.library:
                calls.append(path)
                time.sleep(.08)
            return old(path, *args, **kwargs)
        started = time.monotonic()
        with patch.object(Path, "stat", stat):
            results = [accept(dict(file_key=str(i), library="media", relpath=f"clip{i}.bin")) for i in range(12)]
        self.assertGreater(sum(results), 0)
        self.assertLessEqual(len(calls), 4)
        self.assertLess(time.monotonic() - started, 3)
        self.assertIn("library_unreachable", [w["code"] for w in accept.warnings])

    def test_content_stall_disables_library_but_other_library_remains_usable(self):
        source = self.base / "source.bin"
        source.write_bytes(b"source")
        (self.library / "copy.bin").write_bytes(b"source")
        extra = self.base / "extra"
        extra.mkdir()
        (extra / "cutaway.bin").write_bytes(b"different")
        libraries = self.data["library"] + [dict(name="extra", root=str(extra))]
        accept = source_filter(source, libraries, [], [])
        with patch("shotseek.source_identity.content_sample", side_effect=TimeoutError):
            frame_id = "copy"
            self.assertFalse(accept(dict(file_key=frame_id, library="media", relpath="copy.bin")))
        with patch.object(Path, "stat", side_effect=AssertionError("Stalled library must not be probed again")):
            frame_id = "other"
            self.assertFalse(accept(dict(file_key=frame_id, library="media", relpath="other.bin")))
        frame_id = "good"
        self.assertTrue(accept(dict(file_key=frame_id, library="extra", relpath="cutaway.bin")))
