import re
import zlib
import numpy as np
from PIL import Image
from . import normalise


class FakeEmbedder:
    model_id = "fake/color-v1"
    dim = 8
    device = "cpu"
    batch_size = 16

    def images(self, images):
        result = np.zeros((len(images), self.dim), dtype=np.float32)
        for i, image in enumerate(images):
            result[i, :3] = np.asarray(image.convert("RGB").resize((4, 4), Image.Resampling.BOX),
                dtype=np.float32).mean(axis=(0, 1)) / 255
            if np.linalg.norm(result[i]) < 1e-6:
                result[i, 3] = 1
        return normalise(result)

    def texts(self, texts):
        colors = dict(red=[1, 0, 0], green=[0, 1, 0], blue=[0, 0, 1], yellow=[1, 1, 0], magenta=[1,
            0, 1], cyan=[0, 1, 1], white=[1, 1, 1])
        result = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            for token in re.findall("[a-z]+", text.lower()):
                if token in colors:
                    result[i, :3] += colors[token]
                elif token == "black":
                    result[i, 3] += 1
                else:
                    result[i, 4 + zlib.crc32(token.encode()) % 4] += .25
            if not np.any(result[i]):
                result[i, 4] = 1
        return normalise(result)
