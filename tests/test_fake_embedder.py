import unittest
import numpy as np
from PIL import Image
from tests import support as support  # Activates the test network guard.
from shotseek.embed.fake import FakeEmbedder


class Fake(unittest.TestCase):
    def test_vectors(self):
        model = FakeEmbedder()
        images = model.images([Image.new("RGB", (20, 20), color) for color in ("red", "green", "black")])
        texts = model.texts(["red", "green", "black", "a red mug", ""])
        self.assertEqual(images.dtype, np.float32)
        np.testing.assert_allclose(np.linalg.norm(texts, axis=1), 1)
        np.testing.assert_allclose(images @ texts[:3].T, np.eye(3), atol=1e-6)
        self.assertEqual(int((images @ texts[3]).argmax()), 0)
        np.testing.assert_array_equal(texts, model.texts(["red", "green", "black", "a red mug", ""]))
