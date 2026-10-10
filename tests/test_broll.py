import json
import os
from pathlib import Path
from unittest.mock import patch
from tests.test_search import SearchCase
from tests.support import make_video
from shotseek.names import env


class Broll(SearchCase):
    def setUp(self):
        super().setUp()
        self.fixture = self.base / "speech.json"
        self.fixture.write_text(json.dumps([dict(start=0, end=6, text="Coffee and pastry at the cafe."), dict(start=8, end=14, text="Boots and hikers at the trailhead.")]))
        self.env[env("TRANSCRIBER")] = "fake:" + str(self.fixture)

    def test_default_video_and_explicit_photo_inclusion(self):
        code, result, _ = self.cli("broll", "--point", "red")
        self.assertEqual(code, 0)
        self.assertEqual(result["filters"]["media"], "video")
        self.assertTrue(all(c["media_type"] == "video" for c in result["beats"][0]["candidates"]))
        code, result, _ = self.cli("broll", "--media", "any", "--point", "red")
        self.assertEqual(code, 0)
        self.assertTrue(any(c["media_type"] == "photo" for c in result["beats"][0]["candidates"]))

    def test_points_and_recommended(self):
        code, result, _ = self.cli("broll", "--media", "photo", "--point", "red ceramic product", "--point", "red ceramic product")
        self.assertEqual(code, 0, result)
        self.assertEqual(len(result["beats"]), 2)
        choices = [next(r for r in b["candidates"] if r["recommended"]) for b in result["beats"]]
        self.assertNotEqual(choices[0]["file_id"], choices[1]["file_id"])
        self.assertTrue(all(b["start"] is None for b in result["beats"]))
        self.assertTrue(all(b["queries"][0]["source"] == "point" for b in result["beats"]))
        code, repeated, _ = self.cli("broll", "--point", "red ceramic product", "--point", "blue ceramic product")
        self.assertEqual(code, 0)
        self.assertTrue(repeated["beats"][1]["candidates"][0]["repeat"])

    def test_transcript_and_beats(self):
        code, first, _ = self.cli("broll", "--transcript", self.fixture)
        self.assertEqual(code, 0, first)
        self.assertEqual(len(first["beats"]), 2)
        for beat in first["beats"]:
            beat["visual_queries"] = ["blue"]
        path = self.base / "beats.json"
        path.write_text(json.dumps(first))
        code, second, _ = self.cli("broll", "--beats", path)
        self.assertEqual(code, 0, second)
        self.assertEqual(second["beats"][0]["queries"], [dict(text="blue", source="agent")])
        self.assertEqual(second["beats"][0]["candidates"][0]["timestamp"], 10)
        code, empty, _ = self.cli("broll", "--point", "say that again")
        self.assertTrue(empty["beats"][0]["candidates"])
        self.assertTrue(self.cli("broll", "--point", "say that again", "--include-filler")[1]["beats"][0]["candidates"])

    def test_explicit_queries_search_short_and_production_beats(self):
        from tests.support import validate_schema
        path = self.base / "edited.json"
        rows = [dict(text="Coffee.", visual_queries=["colorful moving shapes"]),
                dict(text="say that again", queries=[dict(text="blue ceramic mug")]),
                dict(text="Coffee.")]
        path.write_text(json.dumps(dict(beats=rows)))
        code, result, _ = self.cli("broll", "--beats", path)
        self.assertEqual(code, 0, result)
        validate_schema(result, "broll")
        for beat in result["beats"][:2]:
            self.assertFalse(beat["skipped"])
            self.assertIsNone(beat["skip_reason"])
            self.assertTrue(beat["candidates"])
            self.assertEqual(sum(c["recommended"] for c in beat["candidates"]), 1)
        self.assertTrue(result["beats"][2]["skipped"])
        self.assertFalse(result["beats"][2]["candidates"])

    def test_aroll_cache_exclusion_and_save(self):
        path = make_video(self.library / "cafe/aroll.mp4", audio=True)
        self.index_run()
        saved = self.base / "saved.json"
        code, first, _ = self.cli("broll", "--aroll", path, "--save-transcript", saved)
        self.assertEqual(code, 0, first)
        self.assertFalse(first["source"]["transcript_cached"])
        self.assertTrue(saved.exists())
        self.assertIn("aroll_excluded", [w["code"] for w in first["warnings"]])
        self.assertTrue(all(r["path"] != str(path) for b in first["beats"] for r in b["candidates"]))
        code, second, _ = self.cli("broll", "--aroll", path)
        self.assertEqual(code, 0)
        self.assertTrue(second["source"]["transcript_cached"])
        self.assertFalse(list((self.index / "tmp").iterdir()))

    def test_aroll_aliases_are_never_candidates(self):
        path = make_video(self.library / "aroll.mp4", segments=[("magenta", 12)], audio=True)
        (self.library / "linked.mp4").symlink_to(path)
        os.link(path, self.library / "same.mp4")
        self.index_run()
        external = self.base / "alias.mp4"
        external.symlink_to(path)
        hardlink = self.base / "hardlink.mp4"
        os.link(path, hardlink)
        mount = self.base / "mount"
        mount.symlink_to(self.library, target_is_directory=True)
        for source in (path, external, hardlink, mount / "aroll.mp4"):
            with self.subTest(source=source.name):
                code, result, _ = self.cli("broll", "--aroll", source)
                self.assertEqual(code, 0, result)
                self.assertIn("aroll_excluded", [w["code"] for w in result["warnings"]])
                candidates = [c for b in result["beats"] for c in b["candidates"]]
                self.assertTrue(candidates)
                self.assertTrue(all(not Path(c["path"]).samefile(source) for c in candidates))

    def test_aroll_only_library_has_no_candidates_through_alias(self):
        path = make_video(self.library / "cafe/aroll.mp4", audio=True)
        self.index_run()
        alias = self.base / "alias.mp4"
        alias.symlink_to(path)
        code, result, _ = self.cli("broll", "--aroll", alias, "--path-contains", "aroll.mp4")
        self.assertEqual(code, 0, result)
        self.assertTrue(all(not b["candidates"] for b in result["beats"]))

    def test_unreadable_candidate_identity_is_omitted(self):
        from shotseek.broll import source_filter
        path = self.library / "cafe/colors.mp4"
        warnings = []
        accept = source_filter(path, self.data["library"], warnings, [])
        with patch.object(Path, "stat", side_effect=OSError):
            frame_id = "sample"
            self.assertFalse(accept(dict(file_key=frame_id, library="media", relpath="missing.mp4")))
        self.assertEqual(warnings[0]["code"], "library_unreachable")

    def test_aroll_errors_and_transcribe_without_config(self):
        self.assertEqual(self.cli("broll", "--aroll", self.base / "missing.mp4")[1]["error"]["code"], "aroll_not_found")
        self.assertEqual(self.cli("broll", "--aroll", self.library / "cafe/colors.mp4")[1]["error"]["code"], "aroll_no_audio")
        path = make_video(self.base / "aroll.mp4", audio=True)
        self.fixture.write_text("[]")
        self.assertEqual(self.cli("broll", "--aroll", path)[1]["error"]["code"], "no_speech_detected")
        self.fixture.write_text('[{"start":0,"end":6,"text":"Coffee and pastry at the cafe."}]')
        self.config.unlink()
        code, result, _ = self.cli("transcribe", path)
        self.assertEqual(code, 0, result)
        self.assertTrue(result["beats"])
        self.assertNotIn("index", result)

    def test_estimated_and_csv(self):
        text = self.base / "words.txt"
        text.write_text("Coffee and pastry at the cafe. Boots and hikers on a trail.")
        code, result, _ = self.cli("broll", "--transcript", text, "--aroll-duration", "30")
        self.assertEqual(code, 0, result)
        self.assertIn("times_estimated", [w["code"] for w in result["warnings"]])
        output = self.base / "broll.csv"
        self.assertEqual(self.cli("broll", "--transcript", text, "--format", "csv", "--output", output)[0], 0)
        self.assertIn("recommended", output.read_text(encoding="utf-8-sig").splitlines()[0])
