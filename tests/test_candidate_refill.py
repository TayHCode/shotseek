"""Dense-source audit reproduction and pools dominated by duplicate items."""
import json
import numpy as np
from tests.test_indexer import IndexCase
from tests.support import make_video
from shotseek.broll import command as broll
from shotseek.cli import build_parser
from shotseek.embed.fake import FakeEmbedder
from shotseek.search import Search, command as search_command
from shotseek.store.db import Store, file_key
from shotseek.names import env


class CandidateRefill(IndexCase):
    def seed(self, records):
        model = FakeEmbedder()
        descriptor = dict(model_id=model.model_id, name="ViT-B-32", pretrained="laion2b_s34b_b79k", dim=model.dim)
        with Store(self.index, descriptor, write=True, thumbnails=False) as store:
            store.checkpoint(records)

    def record(self, name, vector, count=1, kind="photo"):
        path = self.library / name
        stat = path.stat() if path.exists() else None
        return dict(library="media", relpath=name, kind=kind, ext=".mp4" if kind == "video" else ".jpg",
                    size=stat.st_size if stat else 1000, mtime_ns=stat.st_mtime_ns if stat else 1,
                    status="indexed", width=160, height=120, orientation="landscape", duration=6 if kind == "video" else None, sample_interval=.01 if kind == "video" else None,
                    frames=[dict(vector=vector, t_ms=i*10 if kind == "video" else None, brightness=.5, sharpness=1) for i in range(count)])

    def test_dense_aroll_does_not_hide_the_lower_scoring_cutaway(self):
        source = make_video(self.library / "source.mp4", segments=[("red", 6)], audio=True)
        make_video(self.library / "cutaway.mp4", segments=[("blue", 6)])
        model = FakeEmbedder()
        self.seed([self.record("source.mp4", model.texts(["red ceramic mug"])[0], 250, "video"),
                   self.record("cutaway.mp4", model.texts(["blue ceramic mug"])[0], 1, "video")])
        fixture = self.base / "speech.json"
        fixture.write_text(json.dumps([dict(start=0, end=6, text="Red ceramic mug at the cafe")]))
        self.env[env("TRANSCRIBER")] = "fake:" + str(fixture)
        for extra in ([], ["--exclude-id", file_key("media", "source.mp4")]):
            code, doc, _ = self.cli("broll", "--aroll", source, "--min-need", "0", *extra)
            self.assertEqual(code, 0, doc)
            self.assertEqual([c["filename"] for c in doc["beats"][0]["candidates"]], ["cutaway.mp4"])
            self.assertIn("insufficient_candidates", [w["code"] for w in doc["warnings"]])

    def test_heavy_late_exclusions_refill_and_check_each_file_once(self):
        vector = np.eye(8, dtype=np.float32)[0]
        self.seed([self.record(f"mug{i}.jpg", vector) for i in range(850)])
        args = build_parser().parse_args(["search", "red", "--no-dedupe", "--top-k", "5"])
        calls = []
        with Search(self.data, self.index, args) as search:
            scores = np.arange(850, 0, -1, dtype=np.float32)
            def eligible(metadata):
                calls.append(metadata["id"])
                return int(metadata["relpath"][3:-4]) >= 840
            result, stats = search.rank(scores, accept_file=eligible)
        self.assertEqual([r["filename"] for r in result], [f"mug{i}.jpg" for i in range(840, 845)])
        self.assertEqual(len(calls), len(set(calls)))
        self.assertEqual(stats["candidates"], 850)

    def test_duplicate_pool_refills_with_distinct_items_and_honors_offset(self):
        vectors = np.eye(8, dtype=np.float32)
        self.seed([self.record(f"copy{i}.jpg", vectors[0]) for i in range(450)] +
                  [self.record(f"mug{i}.jpg", vectors[i]) for i in range(1, 5)])
        args = build_parser().parse_args(["search", "red", "--top-k", "3", "--offset", "1"])
        result = search_command(args)["queries"][0]["results"]
        self.assertEqual(len(result), 3)
        self.assertEqual([r["rank"] for r in result], [2, 3, 4])
        self.assertTrue(all(r["filename"].startswith("mug") for r in result))
        doc = broll(build_parser().parse_args(["broll", "--point", "red ceramic mug at the cafe", "--media", "photo", "--per-beat", "5"]))
        self.assertEqual(len(doc["beats"][0]["candidates"]), 5)
        self.assertNotIn("insufficient_candidates", [w["code"] for w in doc["warnings"]])

    def test_per_file_limits_refill_and_exhaustion_is_explicit(self):
        vectors = np.eye(8, dtype=np.float32)
        self.seed([self.record("source.mp4", vectors[0], 700, "video"),
                   self.record("cutaway.mp4", vectors[1], 1, "video")])
        args = build_parser().parse_args(["broll", "--point", "red ceramic mug at the cafe", "--per-beat", "2"])
        doc = broll(args)
        self.assertEqual(len(doc["beats"][0]["candidates"]), 2)
        args.per_beat = 3
        short = broll(args)
        self.assertEqual(len(short["beats"][0]["candidates"]), 2)
        self.assertIn("insufficient_candidates", [w["code"] for w in short["warnings"]])
        args.exclude_id = [file_key("media", "source.mp4"), file_key("media", "cutaway.mp4")]
        empty = broll(args)
        self.assertFalse(empty["beats"][0]["candidates"])
        self.assertIn("insufficient_candidates", [w["code"] for w in empty["warnings"]])

    def test_lower_moment_of_a_file_survives_when_its_first_is_duplicate(self):
        vectors = np.eye(8, dtype=np.float32)
        first = self.record("first.mp4", vectors[0], 1, "video")
        second = self.record("second.mp4", vectors[0], 1, "video")
        second["frames"].append(dict(vector=vectors[1], t_ms=5000, brightness=.5, sharpness=1))
        self.seed([first, second])
        args = build_parser().parse_args(["search", "red", "--max-per-file", "1", "--top-k", "2"])
        result = search_command(args)["queries"][0]["results"]
        self.assertEqual([r["filename"] for r in result], ["first.mp4", "second.mp4"])
        self.assertEqual(result[1]["timestamp"], 5)
