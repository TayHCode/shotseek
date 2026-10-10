from unittest.mock import Mock
from tests.test_indexer import IndexCase
from tests.support import make_video, tree_manifest
from shotseek.media import load
from shotseek.store.db import Store
from shotseek.errors import AppError


class Index(IndexCase):
    def test_run_resume_retry_and_rebuild(self):
        self.data["indexing"]["video_sampling"] = "fixed"
        for i, color in enumerate(("red", "green", "blue")):
            make_video(self.library / f"clip{i}.mp4", [(color, 6)])
        (self.library / "bad.mp4").write_text("invalid video")
        before = tree_manifest(self.library)
        first = self.index_run()
        self.assertEqual(first["status"], "complete")
        self.assertEqual(first["totals"]["vectors_added"], 12)
        with Store(self.index) as store:
            self.assertEqual(store.snapshot()[1].shape, (12, 8))
            self.assertEqual(sum(r["frame_count"] for r in store.files()), 12)
            bad = next(r for r in store.files() if r["status"] == "failed")
            self.assertEqual(bad["fail_reason"], "probe_failed")
            self.assertTrue({"relpath", "duration", "frame_count"} <= bad.keys())
        self.assertEqual(len(list((self.index / "thumbs").rglob("*.jpg"))), 12)
        loader = Mock(side_effect=load)
        self.index_run(loader=loader)
        self.assertEqual(loader.call_count, 0)
        self.index_run("--retry-failed", loader=loader)
        self.assertEqual(loader.call_count, 1)
        loader.reset_mock()
        self.index_run("--rebuild", "--yes", loader=loader)
        self.assertEqual(loader.call_count, 4)
        self.assertEqual(tree_manifest(self.library), before)

    def test_missing_vectors_refuses_resume(self):
        make_video(self.library / "clip.mp4", [("red", 6)])
        self.index_run()
        next(self.index.glob("vectors-*.f16")).unlink()
        with Store(self.index) as store:
            with self.assertRaises(AppError) as raised:
                store.snapshot()
        self.assertEqual(raised.exception.code, "index_corrupt")
