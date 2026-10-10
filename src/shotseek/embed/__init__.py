import os
from typing import Protocol
import numpy as np
from ..names import env


class Embedder(Protocol):
    model_id: str
    dim: int
    device: str

    def images(self, images) -> np.ndarray: ...
    def texts(self, texts) -> np.ndarray: ...


def normalise(values):
    values = np.asarray(values, dtype=np.float32)
    return values / np.maximum(np.linalg.norm(values, axis=-1, keepdims=True), 1e-12)


def get_embedder(model=None, device="cpu", offline=False, batch_size=0):
    if os.environ.get(env("EMBEDDER")) == "fake" or (model and model.get("model_id") == "fake/color-v1"):
        from .fake import FakeEmbedder
        return FakeEmbedder()
    from .openclip import OpenClipEmbedder
    return OpenClipEmbedder(model or {}, device, offline, batch_size)
