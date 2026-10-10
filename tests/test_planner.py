import json
from tests.test_indexer import IndexCase
from tests.support import make_video
from tests.characterization.test_char_planner import segments
from shotseek import planner
from shotseek.beats import split, decorate
from shotseek.names import env


class PlannerFlow(IndexCase):
    def test_command_matches_existing_placements(self):
        source = make_video(self.base / "speaker.mp4", [("red", 44)], audio=True)
        fixture = self.base / "speech.json"
        fixture.write_text(json.dumps(segments()))
        self.env[env("TRANSCRIBER")] = "fake:" + str(fixture)
        code, doc, _ = self.cli("transcribe", source)
        self.assertEqual(code, 0, doc)
        selected = sorted((b for b in doc["beats"] if not b["skipped"]), key=lambda b: -b["need_score"])
        expected = planner.plan_broll_placements(segments())
        self.assertEqual(len(selected), len(expected))
        for beat, placement in zip(selected, expected):
            self.assertEqual(beat["placement"], dict(start=placement["aroll_start"], end=placement["aroll_end"]))
            self.assertEqual(beat["need_score"], placement["score"])
            self.assertEqual(beat["search_terms"], placement["search_terms"])
            self.assertEqual(beat["suggested_broll"], placement["suggested_broll"])
        self.assertEqual(doc["beats"][-1]["skip_reason"], "too_short")
        self.assertEqual(doc["source"]["whisper_model"], "base")

    def test_limit_and_queries(self):
        transcript = dict(timed=True, segments=[dict(row, id=i+1) for i, row in enumerate(segments())])
        limited = split(transcript, max_beats=1)
        self.assertEqual(sum(not b["skipped"] for b in limited), 1)
        self.assertIn("over_limit", [b["skip_reason"] for b in limited])
        self.assertEqual(sum(not b["skipped"] for b in split(transcript, max_beats=0)), 2)
        beat = limited[0]
        self.assertEqual(beat["queries"][0]["source"], "topic")
        self.assertEqual(beat["queries"][-2]["source"], "keywords")
        self.assertEqual(beat["queries"][-1]["source"], "sentence")
        self.assertFalse(decorate("say that again", 1, point=True)["skipped"])

    def test_similarity_off_switch_keeps_identity_exclusion(self):
        from shotseek.source_identity import source_filter
        source = make_video(self.library / "source.mp4", [("red", 6)])
        self.index_run()
        from shotseek.cli import build_parser
        from shotseek.search import Search
        args = build_parser().parse_args(["broll", "--point", "red", "--keep-near-duplicates"])
        with Search(self.data, self.index, args) as search:
            accept = source_filter(source, self.data["library"], [], [], search, True)
            self.assertIsNone(accept.vectors)
            self.assertFalse(accept(search.store.files()[0]))

    def test_short_window_keeps_score_index_on_edited_roundtrip(self):
        from shotseek.broll import edited
        from shotseek.cli import build_parser
        transcript = dict(timed=True, segments=[
            dict(id=1, start=0, end=2, text="okay"),
            dict(id=2, start=20, end=28, text="Students explore the school classroom?"),
        ])
        beats = split(transcript)
        path = self.base / "beats.json"
        path.write_text(json.dumps(dict(beats=beats, transcript=transcript)))
        args = build_parser().parse_args(["broll", "--beats", str(path)])
        restored = edited(path, args=args)[0]
        self.assertEqual([b["need_score"] for b in restored], [b["need_score"] for b in beats])
        self.assertEqual([b["skipped"] for b in restored], [b["skipped"] for b in beats])
