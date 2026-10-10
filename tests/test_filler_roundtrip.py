"""Explicit queries and untouched filler must remain distinct across edits."""
import json
from tests.test_indexer import IndexCase
from tests.support import make_image, validate_schema


class FillerRoundtrip(IndexCase):
    def setUp(self):
        super().setUp()
        make_image(self.library / "mug.jpg", "red")
        self.index_run()
        self.path = self.base / "beats.json"

    def run_beats(self, doc, *options):
        self.path.write_text(json.dumps(doc))
        code, result, _ = self.cli("broll", "--beats", self.path, "--media", "photo", *options)
        self.assertEqual(code, 0, result)
        validate_schema(result, "broll")
        return result

    def initial(self):
        return self.run_beats(dict(beats=[dict(text="Coffee.", visual_queries=["red ceramic mug"]),
                                         dict(text="say that again", queries=[dict(text="red ceramic mug")]),
                                         dict(text="Coffee.")]))

    def assert_filler(self, result):
        self.assertEqual([b["skipped"] for b in result["beats"]], [False, False, True])
        self.assertTrue(all(b["candidates"] for b in result["beats"][:2]))
        self.assertFalse(result["beats"][2]["candidates"])
        self.assertEqual(result["beats"][2]["queries"], [dict(text="a photo of coffee", source="keywords"),
                                                               dict(text="Coffee.", source="sentence")])

    def test_audit_three_beat_roundtrip_with_and_without_revision(self):
        result = self.initial()
        self.assert_filler(result)
        for _ in range(3):
            result = self.run_beats(result)
            self.assert_filler(result)
        result.pop("revision")
        result["schema_version"] = 1
        for _ in range(2):
            result = self.run_beats(result)
            self.assert_filler(result)

    def test_editing_one_beat_does_not_activate_unrelated_filler(self):
        result = self.initial()
        result["beats"][0]["visual_queries"] = ["blue ceramic mug"]
        changed = self.run_beats(result)
        self.assert_filler(changed)
        self.assertEqual(changed["beats"][0]["queries"], [dict(text="blue ceramic mug", source="agent")])
        self.assertEqual(changed["beats"][2], result["beats"][2])

    def test_editing_generated_query_is_explicit_with_known_revision(self):
        result = self.initial()
        result["beats"][2]["queries"][0]["text"] = "red ceramic mug"
        edited = self.run_beats(result)
        self.assertFalse(edited["beats"][2]["skipped"])
        self.assertTrue(edited["beats"][2]["candidates"])
        self.assertEqual(edited["beats"][2]["queries"], [dict(text="red ceramic mug", source="agent")])
        self.assertEqual(edited["beats"], self.run_beats(edited)["beats"])

    def test_legacy_generated_queries_regenerate_from_edited_text(self):
        result = self.initial()
        result.pop("revision")
        result["beats"][2]["text"] = "Red ceramic product photographs at the cafe counter beside bright windows?"
        updated = self.run_beats(result)
        self.assertFalse(updated["beats"][2]["skipped"])
        self.assertEqual(updated["beats"][2]["queries"][-1]["text"], "Red ceramic product photographs at the cafe counter beside bright windows?")
        self.assertEqual(updated["beats"][2]["queries"][-1]["source"], "sentence")
        result["beats"][2]["text"] = "Coffee."
        result["beats"][2]["queries"] = [dict(text="red ceramic mug", source="agent")]
        self.assertFalse(self.run_beats(result)["beats"][2]["skipped"])

    def test_include_filler_is_not_a_persistent_query_override(self):
        result = self.initial()
        active = self.run_beats(result, "--include-filler")
        self.assertFalse(any(b["skipped"] for b in active["beats"]))
        self.assert_filler(self.run_beats(active))
        self.assert_filler(self.run_beats(self.run_beats(active)))

    def test_bad_query_source_is_a_usage_error(self):
        self.path.write_text(json.dumps(dict(beats=[dict(text="Coffee.", queries=[dict(text="red", source=None)])])))
        code, doc, _ = self.cli("broll", "--beats", self.path)
        self.assertEqual(code, 2, doc)
        self.assertEqual(doc["error"]["code"], "usage")
