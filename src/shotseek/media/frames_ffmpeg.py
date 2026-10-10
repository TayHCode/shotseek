from io import BytesIO
from PIL import Image
from . import MediaError
from .ffmpeg import LOCAL_INPUT, run
from ..paths import absolute


def frame(path, t_ms, timeout=60):
    data = run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", *LOCAL_INPUT,
        "-ss", str(t_ms / 1000), "-i", str(absolute(path)), "-an", "-sn", "-dn",
        "-frames:v", "1", "-vf", "scale=448:448:force_original_aspect_ratio=decrease", "-pix_fmt",
        "yuvj420p", "-c:v", "mjpeg", "-q:v", "3", "-f", "image2pipe", "pipe:1"], timeout)
    try:
        with Image.open(BytesIO(data)) as source:
            return source.convert("RGB")
    except (OSError, ValueError):
        raise MediaError("decode_failed") from None

