"""Load the existing modules with deterministic local model substitutes."""
from contextlib import redirect_stdout
import io
import json
import sys
from unittest.mock import patch

import numpy as np
from tests.support import ROOT as ROOT  # Also activates the test network guard.


def load(name):
    import importlib
    paths = {
        "broll_library": "media.videos", "index_broll_library": "indexer",
        "search_broll_library": "search", "match_broll_library": "broll",
        "broll_plan": "planner", "transcribe": "transcribe.whisper",
    }
    return importlib.import_module("shotseek." + paths[name])


def colour_vectors(frames):
    values = np.asarray([frame.mean(axis=(0, 1))[::-1] for frame in frames], dtype=np.float32)
    return values / np.maximum(np.linalg.norm(values, axis=1, keepdims=True), 1e-12)


def execute(module, args, vectors=None):
    with patch.object(sys, "argv", ["local", *map(str, args)]), redirect_stdout(io.StringIO()):
        with patch.object(module, "load_clip_model", return_value=(None, None, None, "cpu")):
            if hasattr(module, "embed_frames"):
                with patch.object(module, "embed_frames", side_effect=lambda m, p, d, f: colour_vectors(f)):
                    module.main()
            else:
                with patch.object(module, "embed_texts", return_value=vectors):
                    module.main()


def vector_index(directory):
    directory.mkdir(exist_ok=True)
    vectors = np.array([[1, 0, 0], [.6, .8, 0], [0, 0, 1]], dtype=np.float32)
    np.save(directory / "embeddings.npy", vectors)
    frames = [{"path": str(directory / f"clip{i}.mp4"), "filename": f"clip{i}.mp4",
               "folder": str(directory), "duration": 12, "width": 320, "height": 240,
               "sample_timestamp": i + .5, "thumbnail": str(directory / f"thumb{i}.jpg")}
              for i in range(3)]
    (directory / "frames.json").write_text(json.dumps(frames))
    return vectors, frames
