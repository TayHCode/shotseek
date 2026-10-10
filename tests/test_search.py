from datetime import datetime, timezone
import os
from unittest.mock import patch
from tests.test_indexer import IndexCase
from tests.support import make_image, make_video
from shotseek.cli import build_parser
from shotseek.search import command
from shotseek.store.db import Store


class SearchCase(IndexCase):
    def setUp(self):
        super().setUp()
        make_image(self.library / "cafe/red.jpg", "red", (800, 600))
        make_image(self.library / "cafe/duplicate.jpg", "red", (640, 480))
        make_image(self.library / "hiking/blue.jpg", "blue", (600, 600))
        make_image(self.library / "product/green.jpg", "green", (400, 800))
        make_image(self.library / "product/black.jpg", "black")
        make_image(self.library / "product/white.jpg", "white")
        make_video(self.library / "cafe/colors.mp4")
        for p in self.library.rglob("*"):
            if p.is_file():
                stamp = datetime(2026, 1, 2, tzinfo=timezone.utc).timestamp()
                os.utime(p, (stamp, stamp))
        self.data["indexing"]["video_frame_interval_seconds"] = 4
        self.index_run()

    def search(self, *args):
        return command(build_parser().parse_args(["search", *args]))


class Searching(SearchCase):
    def test_ranking_dedupe_blank_and_stats(self):
        result = self.search("red", "--media", "photo")
        query = result["queries"][0]
        self.assertEqual(query["results"][0]["near_duplicates"], 1)
        self.assertEqual(query["results"][0]["score"], 1)
        self.assertEqual(query["score_stats"]["candidates"], 4)
        stats = query["score_stats"]
        self.assertAlmostEqual(query["results"][0]["relevance"], (1 - stats["mean"]) / stats["std"], delta=.02)
        self.assertEqual(self.search("black", "--include-blank")["queries"][0]["results"][0]["filename"], "black.jpg")

    def test_video_moment_and_show(self):
        result = self.search("blue", "--media", "video", "--max-clip-seconds", "4")["queries"][0]["results"][0]
        self.assertEqual(result["timestamp"], 10)
        self.assertLessEqual(result["start"], 10)
        self.assertGreaterEqual(result["end"], 10)
        self.assertLessEqual(result["end"] - result["start"], 4)
        self.assertEqual(result["matched_frames"], 3)
        self.assertEqual(result["timecode"], "00:00:10.000")
        code, shown, _ = self.cli("show", result["file_id"])
        self.assertEqual(code, 0)
        self.assertEqual(len(shown["frames"]), 3)
        self.assertEqual(self.cli("show", "missing")[1]["error"]["code"], "unknown_id")

    def test_every_metadata_filter(self):
        cases = [
            (["--orientation", "portrait"], {"green.jpg"}),
            (["--orientation", "square"], {"blue.jpg"}),
            (["--min-width", "750"], {"red.jpg"}),
            (["--min-height", "750"], {"green.jpg"}),
            (["--min-megapixels", ".4"], {"red.jpg"}),
            (["--under", "hiking"], {"blue.jpg"}),
            (["--under", str(self.library / "hiking")], {"blue.jpg"}),
            (["--path-contains", "CAFE", "--path-contains", "red"], {"red.jpg"}),
            (["--after", "2027-01-01"], set()),
            (["--before", "2025-01-01"], set()),
        ]
        for options, expected in cases:
            with self.subTest(options=options):
                result = self.search("red", "--media", "photo", "--no-dedupe", *options)
                self.assertEqual({r["filename"] for r in result["queries"][0]["results"]}, expected)
        self.assertTrue(self.search("red", "--min-duration", "10", "--max-duration", "15")["queries"][0]["results"])
        self.assertFalse(self.search("red", "--min-duration", "20")["queries"][0]["results"])
        self.assertTrue(self.search("red", "--library", "media")["queries"][0]["results"])
        with self.assertRaises(Exception):
            self.search("red", "--library", "missing")

    def test_paging_queries_exclusion_like(self):
        first = self.search("red", "--media", "photo", "--no-dedupe")["queries"][0]["results"]
        page = self.search("red", "--media", "photo", "--no-dedupe", "--offset", "1", "--top-k", "1")["queries"][0]["results"]
        self.assertEqual(page[0]["item_id"], first[1]["item_id"])
        results = self.search("--like", first[0]["item_id"], "--exclude-id", first[0]["file_id"])["queries"][0]["results"]
        self.assertTrue(all(r["file_id"] != first[0]["file_id"] for r in results))
        self.assertEqual(len(self.search("red", "blue")["queries"]), 2)
        query_file = self.base / "queries.csv"
        query_file.write_text("query_id,query\na,red\nb,blue\n")
        self.assertEqual([q["id"] for q in self.search("--queries-file", str(query_file))["queries"]], ["a", "b"])
        self.assertFalse(self.search("red", "--min-score", "2")["queries"][0]["results"])
        self.assertFalse(self.search("red", "--min-relevance", "200")["queries"][0]["results"])

    def test_invalid_device_rejected_with_cached_query(self):
        self.search("red")
        code, result, _ = self.cli("search", "red", "--device", "cudaa")
        self.assertEqual(code, 2)
        self.assertEqual(result["error"]["code"], "usage")
        self.assertIn("Invalid device", result["error"]["message"])

    def test_cache_and_partial_warning(self):
        self.search("red")
        with patch("shotseek.search.get_embedder", side_effect=AssertionError("Cache should avoid loading a model")):
            self.search("red")
        with Store(self.index, write=True) as store:
            with store.db:
                store.db.execute("UPDATE runs SET status='partial'")
        warnings = self.search("blue")["warnings"]
        self.assertIn("index_incomplete", [w["code"] for w in warnings])

    def test_output_guard_and_zero_success(self):
        code, doc, _ = self.cli("search", "red", "--output", self.library / "results.json")
        self.assertEqual(code, 2)
        self.assertEqual(doc["error"]["code"], "output_inside_library")
        self.assertEqual(self.cli("search", "red", "--min-score", "2")[0], 0)
