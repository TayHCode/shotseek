import json
from tests.test_indexer import IndexCase
from tests.support import make_image, validate_schema


class StructuredInputs(IndexCase):
    def setUp(self):
        super().setUp()
        make_image(self.library / "mug.jpg", "red")
        self.index_run()

    def rejected(self, *args):
        code, result, stderr = self.cli(*args)
        self.assertEqual(code, 2, result)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "usage")
        self.assertTrue(result["error"]["message"])
        self.assertNotIn("Traceback", stderr)
        validate_schema(result, "error")

    def test_invalid_beats_have_usage_errors(self):
        valid = dict(text="Coffee and pastry", start=0, end=1)
        variants = [None, [], "coffee", 4,
                    dict(valid, start=False, end=True), dict(valid, start=0, end=False),
                    dict(valid, start=-1), dict(valid, end=-1), dict(valid, start=None),
                    dict(valid, end="1"), dict(valid, end=float("inf")), dict(valid, end=10**400),
                    dict(valid, text=3), dict(valid, text="\udcff"), dict(valid, id=False),
                    dict(valid, segment_ids=None), dict(valid, segment_ids=[False]),
                    dict(valid, segment_ids=[{}]), dict(valid, segment_ids=[1, 1]),
                    dict(valid, visual_queries=None), dict(valid, visual_queries="red"),
                    dict(valid, visual_queries=[]), dict(valid, visual_queries=[1]),
                    dict(valid, queries=[None]), dict(valid, queries=[dict(text=False)])]
        path = self.base / "beats.json"
        for row in variants:
            with self.subTest(row_type=type(row).__name__):
                path.write_text(json.dumps(dict(beats=[row])))
                self.rejected("broll", "--beats", path)
        for doc in (None, [], dict(beats=None), dict(beats=[]), dict(beats=[valid], transcript=None),
                    dict(beats=[valid], transcript=dict(timed="yes", segments=[])),
                    dict(beats=[dict(valid, id="same"), dict(valid, id="same")]),
                    dict(beats=[dict(valid, segment_ids=[2])], transcript=dict(timed=False, segments=[]))):
            path.write_text(json.dumps(doc))
            self.rejected("broll", "--beats", path)
        for raw in ('{"beats":[],"beats":[]}', '{"beats":[{"text":"coffee","start":NaN,"end":1}]}'):
            path.write_text(raw)
            self.rejected("broll", "--beats", path)
        path.write_bytes(b"\xff")
        self.rejected("broll", "--beats", path)

    def test_invalid_json_transcripts_have_usage_errors(self):
        path = self.base / "transcript.json"
        variants = [None, True, 4, "coffee", dict(transcript=None), dict(transcript=[]),
                    dict(segments=None), [False], [dict(text=3)], [dict(text="\udcff")],
                    [dict(text="coffee", start=False, end=True)],
                    [dict(text="coffee", start=0, end=float("inf"))],
                    [dict(text="coffee", start=0, end=10**400)],
                    dict(transcript=dict(timed="yes", segments=[])),
                    dict(timed=False, segments=[dict(text="coffee", start=0, end=1)]),
                    [dict(id=False, text="coffee")]]
        for doc in variants:
            with self.subTest(doc_type=type(doc).__name__):
                path.write_text(json.dumps(doc))
                self.rejected("broll", "--transcript", path)
        for raw in ('{bad', '{"segments":[],"segments":[]}', '{"segments":[{"text":"coffee","start":0,"end":1e999}]}'):
            path.write_text(raw)
            self.rejected("broll", "--transcript", path)

    def test_ragged_and_malformed_csv_have_usage_errors(self):
        path = self.base / "queries.csv"
        for text in ("query_id,query\nq1\n", "query_id,query\nq1,\n", "query\nred,blue\n",
                     "query,query\nred,blue\n", "query_id\nq1\n", 'query\n"unterminated\n',
                     "query,notes\nred,coffee\n"):
            with self.subTest(csv=text):
                path.write_text(text)
                self.rejected("search", "--queries-file", path)

    def test_valid_edited_document_preserves_segment_ids_and_schema(self):
        path = self.base / "beats.json"
        doc = dict(beats=[dict(id="passage-1", text="Coffee and pastry", start=0., end=4.,
                               segment_ids=[17], visual_queries=["red ceramic mug"])],
                   transcript=dict(timed=True, segments=[dict(id=17, start=0., end=4., text="Coffee and pastry")]))
        path.write_text(json.dumps(doc))
        code, result, _ = self.cli("broll", "--beats", path, "--media", "photo")
        self.assertEqual(code, 0, result)
        validate_schema(result, "broll")
        self.assertEqual(result["transcript"]["segments"][0]["id"], 17)
        self.assertEqual(result["beats"][0]["segment_ids"], [17])
        self.assertTrue(result["beats"][0]["candidates"])
        path.write_text(json.dumps(result))
        code, again, _ = self.cli("broll", "--beats", path, "--media", "photo")
        self.assertEqual(code, 0, again)
        validate_schema(again, "broll")
