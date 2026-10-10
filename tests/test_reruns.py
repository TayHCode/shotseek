"""Edited-document audit loop, reuse, invalidation, and ordering."""
from copy import deepcopy
import json
import shutil
from unittest.mock import patch
from tests.test_indexer import IndexCase
from tests.support import make_image, make_video, validate_schema
from shotseek.broll import command
from shotseek.cli import build_parser
from shotseek.search import Search
from shotseek.names import env


class Reruns(IndexCase):
    def setUp(self):
        super().setUp()
        for color in ("red", "blue", "green"):
            make_image(self.library / (color + ".jpg"), color)
        self.index_run()
        self.path = self.base / "beats.json"

    def run_beats(self, doc, *options):
        self.path.write_text(json.dumps(doc))
        return command(build_parser().parse_args(["broll", "--beats", str(self.path), "--media", "photo", "--segmenter", "pauses", "--min-need", "0", *options]))

    def initial(self):
        return self.run_beats(dict(beats=[dict(id="first", text="Red ceramic mug", visual_queries=["red"]),
                                         dict(id="second", text="Blue ceramic mug", visual_queries=["blue"]),
                                         dict(id="third", text="Green ceramic mug", visual_queries=["green"])]))

    def test_unchanged_reuses_computed_results_and_ignores_supplied_candidates(self):
        first = self.initial()
        changed = deepcopy(first)
        changed["beats"][0]["candidates"] = [dict(filename="untrusted.mp4", recommended=True)]
        with patch.object(Search, "score", side_effect=AssertionError("Unchanged beats must reuse scores")), patch.object(Search, "text_vectors", side_effect=AssertionError("Unchanged beats must reuse query work")):
            second = self.run_beats(changed)
        self.assertEqual(first["beats"], second["beats"])
        self.assertEqual(first["revision"], second["revision"])
        code, result, _ = self.cli("broll", "--beats", self.path, "--media", "photo", "--segmenter", "pauses", "--min-need", "0")
        self.assertEqual(code, 0, result)
        validate_schema(result, "broll")

    def test_only_edited_beat_recomputed_and_removed_beats_dropped(self):
        first = self.initial()
        edited = deepcopy(first)
        edited["beats"][1]["visual_queries"] = ["green"]
        edited["beats"].pop(2)
        original = Search.score
        calls = []
        def score(search, vectors):
            calls.append(len(vectors))
            return original(search, vectors)
        with patch.object(Search, "score", score):
            second = self.run_beats(edited)
        self.assertEqual(calls, [1])
        self.assertEqual([b["id"] for b in second["beats"]], ["first", "second"])
        self.assertEqual(second["beats"][0]["candidates"], first["beats"][0]["candidates"])
        self.assertEqual(second["beats"][1]["candidates"][0]["filename"], "green.jpg")
        with patch.object(Search, "score", side_effect=AssertionError("Second round must reuse both beats")):
            third = self.run_beats(second)
        self.assertEqual(second["beats"], third["beats"])

    def test_reordering_reselects_recommendations_deterministically(self):
        first = self.initial()
        for beat in first["beats"]:
            beat["visual_queries"] = ["red"]
        first = self.run_beats(first)
        first["beats"] = list(reversed(first["beats"]))
        with patch.object(Search, "score", side_effect=AssertionError("Reordering does not change scores")):
            second = self.run_beats(first)
        self.assertEqual([b["id"] for b in second["beats"]], ["third", "second", "first"])
        choices = [next(c for c in b["candidates"] if c["recommended"])["file_id"] for b in second["beats"]]
        self.assertEqual(len(set(choices)), 3)
        self.assertEqual(second["beats"], self.run_beats(second)["beats"])
        second["beats"] = []
        self.assertEqual(self.run_beats(second)["beats"], [])

    def test_transcript_edits_preserve_ids_remove_and_append(self):
        transcript = dict(timed=True, segments=[dict(id=1, start=0, end=6, text="Red ceramic mug"), dict(id=2, start=8, end=14, text="Blue ceramic mug")])
        beats = [dict(id="first", text=s["text"], start=s["start"], end=s["end"], segment_ids=[s["id"]]) for s in transcript["segments"]]
        beats[1]["id"] = "second"
        first = self.run_beats(dict(beats=beats, transcript=transcript))
        first["transcript"]["segments"][0].update(text="Green ceramic mug", end=7)
        first["transcript"]["segments"].pop(1)
        first["transcript"]["segments"].append(dict(id=3, start=20, end=26, text="Blue ceramic product"))
        second = self.run_beats(first)
        self.assertEqual(second["beats"][0]["id"], "first")
        self.assertEqual(second["beats"][0]["text"], "Green ceramic mug")
        self.assertEqual(second["beats"][0]["end"], 7)
        self.assertEqual(second["beats"][0]["candidates"][0]["filename"], "green.jpg")
        self.assertEqual(len(second["beats"]), 2)
        self.assertNotIn("second", [b["id"] for b in second["beats"]])
        self.assertEqual(second["beats"][1]["segment_ids"], [3])
        self.assertEqual(second["beats"], self.run_beats(second)["beats"])

    def test_text_time_and_insertions_are_edits_without_id_renumbering(self):
        first = self.run_beats(dict(beats=[dict(id="keep", text="Red ceramic mug"), dict(id="edit", text="Blue ceramic mug")]))
        first["beats"][1].update(text="Green ceramic mug", start=2, end=5)
        first["beats"].insert(0, dict(text="Blue ceramic product"))
        second = self.run_beats(first)
        self.assertEqual([b["id"] for b in second["beats"]][1:], ["keep", "edit"])
        self.assertEqual(second["beats"][2]["candidates"][0]["filename"], "green.jpg")
        self.assertEqual(second["beats"], self.run_beats(second)["beats"])

    def test_index_and_options_invalidate_reuse(self):
        first = self.initial()
        make_image(self.library / "red.jpg", "blue", size=(800, 600))
        self.index_run()
        second = self.run_beats(first)
        self.assertNotEqual(first["beats"][0]["candidates"], second["beats"][0]["candidates"])
        third = self.run_beats(second, "--per-beat", "1")
        self.assertTrue(all(len(b["candidates"]) == 1 for b in third["beats"]))
        key = third["beats"][0]["candidates"][0]["file_id"]
        fourth = self.run_beats(third, "--exclude-id", key)
        self.assertTrue(all(c["file_id"] != key for b in fourth["beats"] for c in b["candidates"]))
        fifth = self.run_beats(fourth)
        self.assertTrue(all(c["file_id"] != key for b in fifth["beats"] for c in b["candidates"]))

    def test_aroll_protection_survives_successive_edits_and_rejects_changes(self):
        source = make_video(self.library / "source.mp4", segments=[("red", 6)], audio=True)
        shutil.copy2(source, self.library / "SOURCE.MP4")
        (self.library / "alias.mp4").symlink_to(source)
        external = self.base / "source.mp4"
        shutil.copy2(source, external)
        make_video(self.library / "cutaway.mp4", segments=[("blue", 6)])
        self.index_run()
        fixture = self.base / "speech.json"
        fixture.write_text(json.dumps([dict(start=0, end=6, text="Red ceramic mug at the cafe")]))
        self.env[env("TRANSCRIBER")] = "fake:" + str(fixture)
        code, first, _ = self.cli("broll", "--aroll", external, "--min-need", "0")
        self.assertEqual(code, 0, first)
        for iteration in range(3):
            first["beats"][0]["visual_queries"] = ["red ceramic mug" if iteration == 0 else "blue"]
            self.path.write_text(json.dumps(first))
            code, second, _ = self.cli("broll", "--beats", self.path)
            self.assertEqual(code, 0, second)
            self.assertEqual(second["source"], first["source"])
            self.assertEqual([c["filename"] for b in second["beats"] for c in b["candidates"]], ["cutaway.mp4"])
            first = second
        tampered = deepcopy(first)
        tampered["source"]["kind"] = "beats"
        self.path.write_text(json.dumps(tampered))
        self.assertEqual(self.cli("broll", "--beats", self.path)[0], 2)
        self.path.write_text(json.dumps(first))
        with external.open("ab") as stream:
            stream.write(b"changed")
        self.assertEqual(self.cli("broll", "--beats", self.path)[0], 2)
        external.unlink()
        code, unavailable, _ = self.cli("broll", "--beats", self.path)
        self.assertEqual(code, 0, unavailable)
        self.assertEqual([c["filename"] for b in unavailable["beats"] for c in b["candidates"]], ["cutaway.mp4"])

    def test_missing_local_history_recomputes_and_reports(self):
        first = self.initial()
        (self.index / "broll" / (first["revision"] + ".json")).unlink()
        second = self.run_beats(first)
        self.assertIn("rerun_history_missing", [w["code"] for w in second["warnings"]])
        self.assertEqual(first["beats"], second["beats"])
