from datetime import datetime
from io import BytesIO
import warnings
from PIL import Image, ImageOps, UnidentifiedImageError
from . import MediaError, orientation
from .quality import quality
from ..paths import filesystem_path


def load_photo(path, settings):
    path = filesystem_path(path)
    try:
        try:
            size = path.stat().st_size
        except OSError:
            raise MediaError("read_error") from None
        if size < 512:
            raise MediaError("too_small")
        if size > 200 * 1024 * 1024:
            raise MediaError("too_large")
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            if path.suffix.lower() in {".heic", ".heif"}:
                raise MediaError("heic_support_missing") from None
        Image.MAX_IMAGE_PIXELS = int(settings["max_image_megapixels"] * 1000000)
        try:
            data = path.read_bytes()
        except OSError:
            raise MediaError("read_error") from None
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                source.seek(0)
                width, height = source.size
                exif = source.getexif()
                if exif.get(274) in {5, 6, 7, 8}:
                    width, height = height, width
                captured = exif.get(36867)
                if captured is None and 34665 in exif:
                    captured = exif.get_ifd(34665).get(36867)
                try:
                    captured = datetime.strptime(str(captured),
                        "%Y:%m:%d %H:%M:%S").isoformat() if captured else None
                except ValueError:
                    captured = None
                if source.format == "JPEG":
                    source.draft("RGB", (896, 896))
                image = ImageOps.exif_transpose(source).convert("RGB")
                image.thumbnail((448, 448), Image.Resampling.LANCZOS)
        return dict(width=width, height=height, orientation=orientation(width, height),
            duration=None, sample_interval=None,
                    captured_at=captured, frames=[dict(image=image, t_ms=None, **quality(image))])
    except MediaError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise MediaError("too_large") from None
    except (UnidentifiedImageError, ValueError, SyntaxError):
        raise MediaError("decode_failed") from None
    except OSError as exc:
        reason = "read_error" if isinstance(exc, (FileNotFoundError,
            PermissionError)) else "decode_failed"
        raise MediaError(reason) from None
