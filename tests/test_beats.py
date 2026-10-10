import unittest
from tests import support as support  # Activates the test network guard.
from shotseek.beats import split_pauses as split, keywords, decorate
from shotseek.transcribe.parse import parse
from shotseek.embed.fake import FakeEmbedder


def transcript(values):
    return dict(timed=True, segments=[dict(id=i + 1, start=s, end=e, text=t) for i, (s, e, t) in enumerate(values)])


class Beats(unittest.TestCase):
    def test_pause_and_length(self):
        data = transcript([(0, 6, "Coffee at the cafe"), (8, 15, "Hikers at the trailhead")])
        self.assertEqual(len(split(data)), 2)
        data = transcript([(0, 12, "Coffee at the cafe"), (12, 24, "Hikers at the trailhead")])
        self.assertEqual(len(split(data)), 2)
        data = transcript([(0, 12, "Coffee at the cafe"), (12, 14, "The pastry case")])
        self.assertEqual(len(split(data)), 1)
        data = transcript([(0, 45, "Coffee at the cafe")])
        self.assertEqual(split(data)[0]["end"], 45)

    def test_similarity_and_no_embedder(self):
        data = transcript([(i * 6, i * 6 + 6, color) for i, color in enumerate(("red", "red", "blue", "blue"))])
        self.assertEqual(len(split(data, maximum=30, embedder=FakeEmbedder())), 2)
        self.assertEqual(len(split(data, maximum=30)), 1)

    def test_untimed_blank_and_estimation(self):
        data = parse("Coffee at the cafe.\n\nBoots at the trailhead.")
        beats = split(data)
        self.assertEqual(len(beats), 2)
        self.assertTrue(all(b["start"] is None for b in beats))
        estimated = split(data, duration=20)
        self.assertEqual(estimated[0]["start"], 0)
        self.assertEqual(estimated[-1]["end"], 20)

    def test_keywords_and_filler(self):
        self.assertEqual(keywords("Coffee coffee pastry trail boots ceramic"), ["coffee", "boots", "ceramic", "pastry", "trail"])
        self.assertTrue(decorate("say that again with coffee and pastry", 1)["skipped"])
        self.assertTrue(decorate("yes", 1)["skipped"])
        beat = decorate("Coffee and pastry at the counter?", 1, 0, 7)
        self.assertFalse(beat["skipped"])
        self.assertEqual(beat["queries"][0]["source"], "keywords")

    def test_supplied_queries_override_filler(self):
        queries = [dict(text="colorful moving shapes", source="agent")]
        for text in ("Coffee.", "say that again"):
            beat = decorate(text, 1, queries=queries)
            self.assertFalse(beat["skipped"])
            self.assertIsNone(beat["skip_reason"])
            self.assertEqual(beat["queries"], queries)
