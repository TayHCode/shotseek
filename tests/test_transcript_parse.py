import json
import unittest
from tests import support as support  # Activates the test network guard.
from shotseek.transcribe.parse import parse
from shotseek.errors import AppError


class Parse(unittest.TestCase):
    def test_cues(self):
        for suffix, content in [(".srt", "1\n00:00:01,200 --> 00:00:03,500\n<b>Coffee</b> at the cafe.\n\n2\n00:00:04,000 --> 00:00:06,000\nThe pastry case."), (".vtt", "WEBVTT\n\n00:01.200 --> 00:03.500\n<b>Coffee</b> at the cafe.")]:
            result = parse(content, suffix)
            self.assertTrue(result["timed"])
            self.assertEqual(result["segments"][0]["start"], 1.2)
            self.assertEqual(result["segments"][0]["text"], "Coffee at the cafe.")

    def test_json_shapes(self):
        rows = [dict(start=1, end=3, text="Coffee at the cafe.")]
        for doc in (rows, dict(segments=rows), dict(transcript=dict(segments=rows))):
            result = parse(json.dumps(doc), ".json")
            self.assertEqual(result["segments"][0]["end"], 3)

    def test_text(self):
        result = parse("[01:02] Coffee at the cafe.\n01:10 The pastry case.")
        self.assertEqual([(r["start"], r["end"]) for r in result["segments"]], [(62, 70), (70, 75)])
        result = parse("Coffee at the cafe. The pastry case!\n\nBoots at the trailhead.")
        self.assertFalse(result["timed"])
        self.assertEqual(len(result["segments"]), 3)
        self.assertTrue(result["segments"][2]["_break_before"])

    def test_errors(self):
        for text, suffix, code in [("", "", "transcript_empty"), ("{bad", ".json", "usage"), ('[{"text":"cafe","start":-1,"end":2}]', ".json", "usage")]:
            with self.assertRaises(AppError) as error:
                parse(text, suffix)
            self.assertEqual(error.exception.code, code)
            self.assertEqual(error.exception.exit_code, 2 if code == "usage" else 7)
