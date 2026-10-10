import json
import os
import subprocess
import sys
import time
import unittest
import numpy as np
from tests.support import Sandbox, ROOT
from shotseek.names import env
from shotseek.config import validate, write
from shotseek.store.db import Store
from shotseek.store.querycache import QueryCache
from shotseek.embed import normalise


@unittest.skipUnless(os.environ.get(env("RUN_SLOW")) == "1", "opt-in scale test; set " + env("RUN_SLOW") + "=1")
class Scale(Sandbox):
    def test_four_hundred_thousand_vectors(self):
        descriptor = dict(model_id="synthetic/scale-v1", name="synthetic", pretrained="scale-v1", dim=512)
        data = validate({"model": {"name": "synthetic", "pretrained": "scale-v1"}, "library": [dict(name="media", root=str(self.library))], "index": {"dir": str(self.index), "thumbnails": False}})
        write(self.config, data)
        rng = np.random.default_rng(42)
        with Store(self.index, descriptor, write=True, thumbnails=False) as store:
            for offset in range(0, 400000, 2000):
                vectors = normalise(rng.standard_normal((2000, 512), dtype=np.float32))
                records = [dict(library="media", relpath=f"product/mug{offset+i}.jpg", kind="photo", ext=".jpg", size=1000, mtime_ns=1, status="indexed", width=640, height=480, orientation="landscape", frames=[dict(vector=vector, t_ms=None, brightness=.5, sharpness=10)]) for i, vector in enumerate(vectors)]
                store.checkpoint(records)
        cache = QueryCache(self.index)
        cache.put(descriptor["model_id"], "ceramic mug", normalise(rng.standard_normal(512, dtype=np.float32)))
        cache.close()
        child_env = dict(os.environ, **self.env)
        child_env.pop(env("EMBEDDER"), None)
        script = r"import resource,sys,re; from pathlib import Path; from shotseek.cli import main; code=main(); rss=int(re.search(r'VmHWM:\s+(\d+)',Path('/proc/self/status').read_text())[1])*1024 if sys.platform.startswith('linux') else resource.getrusage(resource.RUSAGE_SELF).ru_maxrss; print('SCALE_RSS_BYTES='+str(rss),file=sys.stderr); raise SystemExit(code)"
        started = time.monotonic()
        result = subprocess.run([sys.executable, "-c", script, "search", "ceramic mug", "--offline"], env=child_env, capture_output=True, text=True, timeout=30)
        elapsed = time.monotonic() - started
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["queries"][0]["score_stats"]["candidates"], 400000)
        rss = int(next(line.split("=")[1] for line in result.stderr.splitlines() if line.startswith("SCALE_RSS_BYTES=")))
        report = dict(vectors=400000, wall_seconds=elapsed, peak_rss_bytes=rss, results=output["queries"][0]["returned"])
        (ROOT / ".scratch").mkdir(exist_ok=True)
        (ROOT / ".scratch/measurements-scale.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report))
        self.assertLess(elapsed, 3)
        self.assertLess(rss, 1500000000)
