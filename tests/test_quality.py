import unittest
import numpy as np
from PIL import Image, ImageFilter
from tests import support as support  # Activates the test network guard.
from shotseek.media.quality import quality


class Quality(unittest.TestCase):
    def test_brightness_and_detail(self):
        self.assertEqual(quality(Image.new("RGB", (100, 100), "black"))["brightness"], 0)
        self.assertEqual(quality(Image.new("RGB", (100, 100), "white"))["brightness"], 1)
        grid = (np.indices((256, 256)).sum(axis=0) // 8 % 2 * 255).astype("uint8")
        image = Image.fromarray(grid)
        self.assertGreater(quality(image)["sharpness"], quality(image.filter(ImageFilter.GaussianBlur(3)))["sharpness"])
