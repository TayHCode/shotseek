import csv
import io
import numpy as np
from unittest.mock import patch
from tests.test_indexer import IndexCase
from tests.test_raw_frames import seed_index
from shotseek.cli import build_parser
from shotseek.search import command, Search
from shotseek.errors import AppError
from shotseek.store.db import Store


class SearchBehavior(IndexCase):
    def test_csv_and_ranking(self):
        seed_index(self)
        queries = self.base / "queries.csv"
        queries.write_text("query_id,query\nq1,red mug\n,blue cup\n")
        args = build_parser().parse_args(["search", "--queries-file", str(queries),
                                         "--top-k", "2", "--raw-frames", "--format", "csv"])
        vectors = np.eye(8, dtype=np.float32)[:2]
        with patch.object(Search, "text_vectors", return_value=vectors):
            result = command(args)
        reader = csv.DictReader(io.StringIO(result["_raw"]))
        self.assertEqual(reader.fieldnames, ["query_id", "query", "rank", "score", "relevance",
            "media_type", "path", "open_path", "filename", "folder", "timestamp", "start", "end",
            "timecode", "duration", "width", "height", "orientation", "captured_at", "thumbnail",
            "item_id", "library", "review_status", "notes"])
        rows = list(reader)
        self.assertEqual(len(rows), 4)
        self.assertEqual([r["query_id"] for r in rows], ["q1", "q1", "blue_cup", "blue_cup"])
        self.assertEqual([float(r["timestamp"]) for r in rows[:2]], [5, 4])
        self.assertGreater(float(rows[0]["score"]), float(rows[1]["score"]))
        self.assertTrue(all(len(r["score"].partition(".")[2]) <= 4 for r in rows))

    def test_missing_query_and_empty_index(self):
        seed_index(self)
        with self.assertRaises(AppError) as raised:
            command(build_parser().parse_args(["search"]))
        self.assertEqual(raised.exception.code, "usage")
        with Store(self.index, write=True) as store:
            store.remove_files([r["id"] for r in store.files()])
        with self.assertRaises(AppError) as raised:
            command(build_parser().parse_args(["search", "red"]))
        self.assertEqual(raised.exception.code, "index_empty")
