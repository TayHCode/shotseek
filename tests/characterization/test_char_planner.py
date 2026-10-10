import unittest
from tests.legacy_stubs import load


def segments():
    return [{"start": 0, "end": 8, "text": "Students explore the school classroom?"},
            {"start": 10, "end": 18, "text": "Our team creates useful product photographs."},
            {"start": 20, "end": 25, "text": "Coffee mugs beside bright windows."},
            {"start": 40, "end": 42, "text": "okay"}]


class Planner(unittest.TestCase):
    def test_keywords_windows(self):
        p = load("broll_plan")
        self.assertEqual(p._keywords("Mugs coffee mugs and blue coffee trail"),
                         ["coffee", "mugs", "blue", "trail"])
        chunks = p._chunk_transcript(segments())
        self.assertEqual([(c["start"], c["end"]) for c in chunks], [(0, 8), (10, 18), (20, 25)])
        combined = p._chunk_transcript([{"start": 0, "end": 3, "text": "Coffee"},
                                       {"start": 3, "end": 9, "text": "mugs"}])
        self.assertEqual(combined, [{"start": 0., "end": 9., "text": "Coffee mugs"}])

    def test_scores(self):
        p = load("broll_plan")
        for text, duration, index, expected in [
            ("look at the camera", 8, 1, .05), ("okay", 8, 1, .05),
            ("coffee mugs trail", 4, 0, .4), ("coffee mugs trail?", 7, 1, .65),
            ("school", 4, 0, .45), ("cup", 4, 0, .2)]:
            self.assertAlmostEqual(p._need_score(text, duration, index)[0], expected)

    def test_placements_and_suggestions(self):
        p = load("broll_plan")
        placements = p.plan_broll_placements(segments(), max_placements=2)
        self.assertEqual([v["score"] for v in placements], [.85, .8])
        self.assertEqual([(v["aroll_start"], v["aroll_end"]) for v in placements], [(0, 6), (10, 16)])
        self.assertEqual(len(p.plan_broll_placements(segments(), min_score=.81)), 1)
        self.assertEqual(p._suggestion_for("coffee mugs")[1], ["coffee", "mugs"])
        self.assertEqual(p._suggestion_for("the and")[1],
                         ["environment cutaway", "detail shot", "simple title graphic"])
        self.assertEqual(len(p.TOPIC_PATTERNS), 5)
