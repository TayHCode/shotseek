import unittest
from tests.legacy_stubs import load


class Sampling(unittest.TestCase):
    def test_fixed(self):
        sample = load("broll_library").sample_timestamps
        expected = {0: [], 3: [1.5], 5: [.75, 1.917, 3.083, 4.25],
                    30: [4.5, 11.5, 18.5, 25.5], 600: [90, 230, 370, 510]}
        for duration, times in expected.items():
            self.assertEqual(sample(duration), times)

    def test_interval_and_cap(self):
        sample = load("broll_library").sample_timestamps
        self.assertEqual(sample(3, sample_every_seconds=5), [1.5])
        self.assertEqual(sample(30, sample_every_seconds=5), [2.5, 7.5, 12.5, 17.5, 22.5, 27.5])
        self.assertEqual(sample(30, sample_every_seconds=5, max_samples_per_video=3),
                         [2.5, 15.0, 27.5])
