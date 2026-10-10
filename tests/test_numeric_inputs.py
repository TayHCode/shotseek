"""Nonfinite duration and huge-finite timestamp audit reproductions."""
import json
from tests.test_indexer import IndexCase
from tests.support import make_image, validate_schema
from shotseek.beats import split
from shotseek.errors import AppError
from shotseek.inputs import MAX_SECONDS, times
from shotseek.output.textout import timecode


class NumericInputs(IndexCase):
    def setUp(self):
        super().setUp()
        make_image(self.library / "mug.jpg", "red")
        self.index_run()
        self.path = self.base / "text.txt"
        self.path.write_text("Red ceramic mug at the cafe counter.")

    def reject(self, *args):
        code, doc, stderr = self.cli(*args)
        self.assertEqual(code, 2, doc)
        self.assertEqual(doc["error"]["code"], "usage")
        self.assertTrue(doc["error"]["message"])
        self.assertNotIn("Traceback", stderr)
        validate_schema(doc, "error")

    def test_duration_and_beat_options_reject_nonfinite_and_out_of_range(self):
        for option in ("aroll-duration", "min-beat-seconds", "max-beat-seconds", "min-clip-seconds", "max-clip-seconds"):
            for value in ("nan", "inf", "-inf", "1e308", str(MAX_SECONDS + 1)):
                with self.subTest(option=option, value=value):
                    self.reject("broll", "--transcript", self.path, "--media", "photo", f"--{option}={value}")
        for value in ("nan", "inf", "1e308"):
            self.reject("transcribe", self.base / "missing.mp4", "--max-beat-seconds=" + value)

    def test_huge_finite_transcript_and_beat_times_rejected(self):
        path = self.base / "transcript.json"
        for value in (1e308, MAX_SECONDS + 1, 10**400):
            row = dict(text="Red ceramic mug at the cafe", start=value, end=value)
            path.write_text(json.dumps(dict(segments=[row])))
            self.reject("broll", "--transcript", path, "--media", "photo")
            path.write_text(json.dumps(dict(beats=[row])))
            self.reject("broll", "--beats", path, "--media", "photo")

    def test_representable_boundary_formats_and_estimates(self):
        times(MAX_SECONDS - 1, MAX_SECONDS, "test")
        self.assertEqual(timecode(MAX_SECONDS), "2777:46:40.000")
        path = self.base / "valid.json"
        path.write_text(json.dumps(dict(segments=[dict(text="Red ceramic mug at the cafe", start=MAX_SECONDS - 1, end=MAX_SECONDS)])))
        code, result, _ = self.cli("broll", "--transcript", path, "--media", "photo")
        self.assertEqual(code, 0, result)
        validate_schema(result, "broll")
        code, result, _ = self.cli("broll", "--transcript", self.path, "--media", "photo", "--aroll-duration", MAX_SECONDS)
        self.assertEqual(code, 0, result)
        self.assertEqual(result["beats"][-1]["end"], MAX_SECONDS)
        self.assertTrue(result["beats"][-1]["timecode"])

    def test_split_rejects_bad_values_before_embedding(self):
        transcript = dict(timed=False, segments=[dict(id=1, text="Coffee and pastry", start=None, end=None)])
        for value in (float("nan"), float("inf"), 1e308, True):
            with self.subTest(value=value), self.assertRaises(AppError) as error:
                split(transcript, duration=value)
            self.assertEqual(error.exception.exit_code, 2)
