from io import BytesIO
from PIL import Image
from ..paths import atomic_write, writable, ensure_index


def path(index, item_id):
    return index / "thumbs" / item_id[:2] / (item_id + ".jpg")


def write(index, item_id, image, max_edge=320, libraries=()):
    image = image.copy()
    image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=80)
    atomic_write(path(index, item_id), buffer.getvalue(), libraries)


def remove(index, item_id, libraries=()):
    ensure_index(index, libraries, create=False)
    writable(path(index, item_id), libraries).unlink(missing_ok=True)
