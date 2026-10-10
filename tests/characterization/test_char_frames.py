import numpy as np
from PIL import Image
from tests.legacy_stubs import load
from tests.support import Sandbox, make_video


class Frames(Sandbox):
    def test_colours_and_failures(self):
        path = make_video(self.library / "colors.mp4")
        module = load("broll_library")
        for seconds, channel in [(2, 2), (6, 1), (10, 0)]:
            frame = module.extract_frame(path, seconds)
            self.assertEqual(int(frame.mean(axis=(0, 1)).argmax()), channel)
        self.assertIsNone(module.extract_frame(path, 20))
        bad = self.library / "bad.mp4"
        bad.write_text("invalid")
        self.assertIsNone(module.extract_frame(bad, 0))

    def test_thumbnail(self):
        out = self.base / "thumb.jpg"
        module = load("broll_library")
        module.save_thumbnail(np.zeros((600, 1200, 3), dtype=np.uint8), out)
        with Image.open(out) as image:
            self.assertEqual(image.size, (640, 320))
        self.assertFalse(any(self.library.iterdir()))
