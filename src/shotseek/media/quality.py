import numpy as np
from PIL import Image


def quality(image):
    grey = image.convert("L")
    brightness = float(np.asarray(grey, dtype=np.float32).mean() / 255)
    grey.thumbnail((256, 256), Image.Resampling.LANCZOS)
    pixels = np.asarray(grey, dtype=np.float32)
    lap = pixels[:-2, 1:-1] + pixels[2:, 1:-1] + pixels[1:-1, :-2] + pixels[1:-1,
        2:] - 4 * pixels[1:-1, 1:-1]
    return dict(brightness=brightness, sharpness=float(lap.var()) if lap.size else 0.0)
