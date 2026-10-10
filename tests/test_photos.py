from PIL import Image
import errno
from unittest.mock import patch
from tests.support import Sandbox, make_image
from shotseek.config import DEFAULTS
from shotseek.media.photos import load_photo
from shotseek.media import MediaError


class Photos(Sandbox):
    def load(self, path):
        return load_photo(path, DEFAULTS["indexing"])

    def test_orientation_and_metadata(self):
        path = make_image(self.library / "mug.jpg", "red", exif_orientation=6)
        result = self.load(path)
        self.assertEqual((result["width"], result["height"]), (480, 640))
        self.assertEqual(result["orientation"], "portrait")
        self.assertLessEqual(max(result["frames"][0]["image"].size), 448)
        exif = Image.Exif()
        exif[36867] = "2026:01:02 03:04:05"
        Image.new("RGB", (640, 630), "green").save(path, exif=exif)
        result = self.load(path)
        self.assertEqual(result["orientation"], "square")
        self.assertEqual(result["captured_at"], "2026-01-02T03:04:05")
        self.assertNotIn("gps", result)

    def test_bad_files(self):
        path = self.library / "bad.jpg"
        for data, reason in [(b"", "too_small"), (b"x" * 1000, "decode_failed")]:
            path.write_bytes(data)
            with self.assertRaises(MediaError) as error:
                self.load(path)
            self.assertEqual(error.exception.reason, reason)

    def test_storage_errors_are_retryable_read_errors(self):
        path = make_image(self.library / "mug.jpg", "red")
        for operation in ("stat", "read_bytes"):
            for code in (errno.EIO, getattr(errno, "ESTALE", errno.EIO), errno.ETIMEDOUT, errno.EACCES):
                with self.subTest(operation=operation, code=code), patch(
                    "pathlib.Path." + operation, side_effect=OSError(code, "Unavailable media")
                ):
                    with self.assertRaises(MediaError) as error:
                        self.load(path)
                    self.assertEqual(error.exception.reason, "read_error")

    def test_decoder_io_error_is_not_a_storage_error(self):
        path = make_image(self.library / "mug.jpg", "red")
        with patch("shotseek.media.photos.Image.open", side_effect=OSError("Invalid image")):
            with self.assertRaises(MediaError) as error:
                self.load(path)
        self.assertEqual(error.exception.reason, "decode_failed")

    def test_alpha_and_first_frame(self):
        path = self.library / "mug.png"
        Image.new("RGBA", (640, 480), (255, 0, 0, 100)).save(path)
        self.assertEqual(self.load(path)["frames"][0]["image"].mode, "RGB")
        path = self.library / "mug.gif"
        Image.new("RGB", (640, 480), "red").save(path, save_all=True, append_images=[Image.new("RGB", (640, 480), "blue")])
        self.assertGreater(self.load(path)["frames"][0]["image"].getpixel((0, 0))[0], 200)

    def test_heic(self):
        import pillow_heif
        if not pillow_heif.libheif_info().get("HEIF"):
            self.skipTest("HEIC encoder unavailable")
        pillow_heif.register_heif_opener()
        path = make_image(self.library / "mug.heic", "red")
        self.assertEqual(self.load(path)["width"], 640)
