import csv
import io
from tests.test_search import SearchCase
from tests.support import make_image
from shotseek.output import csvout, textout


class Output(SearchCase):
    def test_search_csv_and_text(self):
        raw = self.search("red", "--media", "photo", "--format", "csv")["_raw"]
        rows = list(csv.reader(io.StringIO(raw)))
        self.assertEqual(rows[0], csvout.SEARCH_COLUMNS)
        self.assertEqual(rows[1][-2:], ["", ""])
        text = self.search("red", "--media", "photo", "--format", "text")["_raw"]
        self.assertEqual(len(text.splitlines()), len(rows) - 1)
        self.assertEqual(textout.timecode(3661.234), "01:01:01.234")

    def test_formula_guard_and_broll_header(self):
        for value in ("=1+1", "+1", "-1", "@mug"):
            self.assertEqual(csvout.safe_cell("query", value), "'" + value)
            self.assertEqual(csvout.safe_cell("path", value), value)
        self.assertEqual(csvout.safe_cell("score", -1), -1)
        text = csvout.format_document(dict(command="broll", beats=[]))
        self.assertEqual(next(csv.reader(io.StringIO(text))), csvout.BROLL_COLUMNS)

    def test_output_bom_and_envelope(self):
        target = self.base / "sheet.csv"
        code, result, _ = self.cli("search", "red", "--format", "csv", "--output", target)
        self.assertEqual(code, 0, result)
        self.assertEqual(result["output_path"], str(target))
        self.assertTrue(target.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertGreater(result["counts"]["results"], 0)
        self.assertNotIn("queries", result)

    def test_control_prefixed_cells_and_paths(self):
        for prefix in ("\t", "\r", "\n", " ", "\0", "\x1b", "\x7f", "\x85", "\ufeff", "\u200b", "\t \r"):
            for formula in ("=1+1", "+1", "-1", "@mug"):
                value = prefix + formula
                for key in ("query", "folder", "filename", "beat_text", "matched_query"):
                    self.assertEqual(csvout.safe_cell(key, value), "'" + value)
                for key in ("path", "open_path", "thumbnail"):
                    self.assertEqual(csvout.safe_cell(key, value), value)
        self.assertEqual(csvout.safe_cell("query", "\t coffee"), "\t coffee")

    def test_control_prefixed_folder_export(self):
        for folder in ("\t=1+1", "\r=2+2"):
            make_image(self.library / folder / "mug.jpg", "red")
        self.index_run()
        target = self.base / "controls.csv"
        code, result, _ = self.cli("search", "\t=1+1", "\r=2+2", "--no-dedupe", "--format", "csv", "--output", target)
        self.assertEqual(code, 0, result)
        with target.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertTrue(rows)
        self.assertTrue(all(row["query"].startswith("'") for row in rows))
        guarded = [row for row in rows if row["filename"] == "mug.jpg"]
        self.assertEqual(len(guarded), 4)
        self.assertTrue(all(row["folder"].startswith("'") for row in guarded))
        self.assertTrue(all(row["path"].startswith(str(self.library)) for row in rows))
        self.assertTrue(all(row["review_status"] == row["notes"] == "" for row in rows))
