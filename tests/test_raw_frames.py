import numpy as np
from tests.test_indexer import IndexCase
from shotseek.cli import build_parser
from shotseek.embed.fake import FakeEmbedder
from shotseek.search import Search
from shotseek.store.db import Store


def seed_index(case, count=6):
    model = FakeEmbedder()
    vectors = np.zeros((count, model.dim), dtype=np.float32)
    vectors[:, 0] = np.linspace(.125, .875, count)
    vectors[:, 1] = np.sqrt(1 - vectors[:, 0] ** 2)
    record = dict(library="media", relpath="colors.mp4", kind="video", ext=".mp4",
                  size=1000, mtime_ns=1, status="indexed", width=320, height=240,
                  orientation="landscape", duration=12, sample_interval=1,
                  frames=[dict(vector=v, t_ms=1000*i, brightness=.5, sharpness=1)
                          for i, v in enumerate(vectors)])
    descriptor = dict(model_id=model.model_id, dim=model.dim, name="ViT-B-32",
                      pretrained="laion2b_s34b_b79k")
    with Store(case.index, descriptor, write=True, thumbnails=False) as store:
        store.checkpoint([record])
    return vectors


class RawFrames(IndexCase):
    def test_order_matches_dot_product_and_ignores_group_limits(self):
        seed_index(self)
        args = build_parser().parse_args(["search", "red", "--raw-frames", "--top-k", "6",
                                          "--max-per-file", "1"])
        with Search(self.data, self.index, args) as search:
            query = np.eye(8, dtype=np.float32)[0]
            scores = search.matrix.astype(np.float32) @ query
            expected = np.argsort(scores)[::-1]
            results, _ = search.rank(scores)
            self.assertEqual([r["timestamp"] for r in results], expected.tolist())
            self.assertEqual([r["score"] for r in results],
                             [round(float(scores[i]), 4) for i in expected])
            self.assertEqual([r["matched_frames"] for r in results], [1]*6)
            self.assertEqual([r["near_duplicates"] for r in results], [0]*6)

    def test_late_filter_refills(self):
        seed_index(self, 251)
        args = build_parser().parse_args(["search", "red", "--top-k", "1"])
        model = FakeEmbedder()
        with Store(self.index, write=True, thumbnails=False) as store:
            record = dict(store.files()[0])
            record.update(relpath="cutaway.mp4", frames=[dict(vector=model.texts(["blue"])[0],
                          t_ms=1000, brightness=.5, sharpness=1)])
            store.checkpoint([record])
        with Search(self.data, self.index, args) as search:
            scores = np.ones(252, dtype=np.float32)
            scores[-1] = .1
            results, _ = search.rank(scores, accept_file=lambda m: m["relpath"] == "cutaway.mp4")
        self.assertEqual([r["filename"] for r in results], ["cutaway.mp4"])
