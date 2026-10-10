from unittest.mock import patch
import numpy as np
from PIL import Image
from tests.support import Sandbox
from shotseek.store.db import Store
from shotseek.store.querycache import QueryCache
from shotseek.store.vectors import vector_path
from shotseek.errors import AppError

MODEL = dict(model_id="fake/color-v1", dim=8, name="fake", pretrained="color-v1")


def record(name="mug.jpg", color=0):
    vector = np.eye(8, dtype=np.float32)[color]
    return dict(library="media", relpath=name, kind="photo", ext=".jpg", size=1000, mtime_ns=1, status="indexed", width=640, height=480, orientation="landscape", frames=[dict(vector=vector, image=Image.new("RGB", (100, 100), "red"), t_ms=None, brightness=.5, sharpness=0)])


class Storage(Sandbox):
    def test_writer_without_model_does_not_create_database(self):
        with self.assertRaises(AppError) as error:
            Store(self.index, write=True)
        self.assertEqual(error.exception.code, "index_not_found")
        self.assertFalse(self.index.exists())

    def test_commit_reopen_and_tail_recovery(self):
        with Store(self.index, MODEL, write=True) as store:
            store.checkpoint([record()])
            with Store(self.index) as reader:
                self.assertEqual(reader.kv()["vector_rows"], 1)
                with self.assertRaises(Exception):
                    reader.db.execute("DELETE FROM files")
            def fail(stage):
                if stage == "transaction":
                    raise RuntimeError("simulated interruption")
            with self.assertRaises(RuntimeError):
                store.checkpoint([record("other.jpg")], fault=fail)
            self.assertEqual(len(store.files()), 1)
            self.assertEqual(store.kv()["vector_rows"], 1)
        self.assertEqual(vector_path(self.index, 1).stat().st_size, 32)
        with Store(self.index, MODEL, write=True) as store:
            self.assertEqual(vector_path(self.index, 1).stat().st_size, 16)
            self.assertEqual(store.kv()["vector_rows"], 1)

    def test_lock(self):
        with Store(self.index, MODEL, write=True):
            with self.assertRaises(AppError) as error:
                Store(self.index, MODEL, write=True)
            self.assertEqual(error.exception.exit_code, 5)
        with Store(self.index, MODEL, write=True):
            pass

    def test_compact_and_cache(self):
        with Store(self.index, MODEL, write=True) as store:
            store.checkpoint([record()])
            store.checkpoint([record(color=1), record("second.jpg", 2)])
            self.assertEqual(store.kv()["dead_rows"], 1)
            self.assertEqual(store.compact(), dict(rows_before=3, rows_after=2))
        with Store(self.index) as store:
            info, matrix = store.snapshot()
            np.testing.assert_array_equal(matrix, np.eye(8, dtype=np.float16)[[1, 2]])
            self.assertEqual(vector_path(self.index, 2).stat().st_size, 32)
        cache = QueryCache(self.index)
        cache.put(MODEL["model_id"], "red", np.eye(8)[0])
        np.testing.assert_array_equal(cache.get(MODEL["model_id"], "red", 8), np.eye(8)[0])
        self.assertIsNone(cache.get("another", "red", 8))
        cache.close()

    def test_marker_mismatch_and_missing_generation_retry(self):
        with Store(self.index, MODEL, write=True) as store:
            store.checkpoint([record()])
        with self.assertRaises(AppError) as error:
            Store(self.index, dict(MODEL, model_id="different"), write=True)
        self.assertEqual(error.exception.code, "index_model_mismatch")
        from shotseek.store import vectors
        read = vectors.read
        calls = []
        def once(*args):
            calls.append(1)
            if len(calls) == 1:
                raise FileNotFoundError
            return read(*args)
        with Store(self.index) as store, patch("shotseek.store.vectors.read", once):
            self.assertEqual(store.snapshot()[1].shape, (1, 8))
        self.assertEqual(len(calls), 2)

    def test_corrupt_metadata_has_stable_error(self):
        with Store(self.index, MODEL, write=True) as store:
            with store.db:
                store.set("vector_rows", "invalid")
        with self.assertRaises(AppError) as error:
            Store(self.index)
        self.assertEqual(error.exception.code, "index_corrupt")
        self.assertEqual(error.exception.exit_code, 3)
