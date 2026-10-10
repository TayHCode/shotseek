import csv
import io
import json
from unittest.mock import patch
from tests.test_indexer import IndexCase
from tests.test_raw_frames import seed_index
from shotseek.broll import command
from shotseek.cli import build_parser
from shotseek.search import Search
from shotseek.store.db import Store


class Match(IndexCase):
    def test_query_and_outputs(self):
        seed_index(self)
        with Store(self.index, write=True, thumbnails=False) as store:
            record = dict(store.files()[0])
            record.update(relpath="cutaway.mp4", frames=[dict(vector=[0, 0, 1, 0, 0, 0, 0, 0],
                          t_ms=500, brightness=.5, sharpness=1)])
            store.checkpoint([record])
        queries = ["red mug", "red coffee", "Coffee is ready"]
        item = dict(text="Coffee is ready", start=0, end=8, visual_queries=queries)
        path = self.base / "beats.json"
        path.write_text(json.dumps(dict(beats=[item, item])))
        args = build_parser().parse_args(["broll", "--beats", str(path), "--per-beat", "2"])
        captured = []
        original = Search.text_vectors
        def vectors(search, texts):
            captured.extend(texts)
            return original(search, texts)
        with patch.object(Search, "text_vectors", vectors):
            doc = command(args)
        self.assertEqual(captured, queries * 2)
        self.assertEqual([len(b["candidates"]) for b in doc["beats"]], [2, 2])
        self.assertTrue({"path", "open_path", "thumbnail", "matched_query"} <=
                        doc["beats"][0]["candidates"][0].keys())
        args.format = "csv"
        reader = csv.DictReader(io.StringIO(command(args)["_raw"]))
        self.assertEqual(reader.fieldnames, "beat_id beat_start beat_end beat_timecode beat_text matched_query rank recommended score relevance media_type path open_path filename clip_start clip_end clip_timecode duration width height thumbnail item_id review_status notes".split())
        rows = list(reader)
        self.assertEqual(len(rows), 4)
        self.assertEqual([row["rank"] for row in rows], ["1", "2", "1", "2"])
