"""Optional local image and text backend; no heavy imports at module load."""
import importlib
import logging
import os
import sys
import numpy as np
from . import normalise
from ..errors import AppError
from ..names import env


def actionable_hub_message(record):
    # Keep download failures and rate-limit warnings; omit the routine account suggestion.
    return not record.getMessage().startswith(
        "Warning: You are sending unauthenticated requests to the HF Hub.")


def offline_mode(offline=False):
    logging.getLogger("huggingface_hub.utils._http").addFilter(actionable_hub_message)
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    enabled = offline or os.environ.get(env("OFFLINE")) == "1" or os.environ.get("HF_HUB_OFFLINE") == "1"
    if enabled:
        os.environ["HF_HUB_OFFLINE"] = "1"
    return enabled


RUNTIME_INSTALL_HINT = "Install the runtime dependencies. On Windows, DLL load failures may require the Microsoft Visual C++ v14 Redistributable matching your Python architecture. See docs/platforms.md and the README quickstart."
CPU_INSTALL_HINT = "Install torch and torchvision together with matching platform builds. Linux/Windows CPU: https://download.pytorch.org/whl/cpu; macOS: PyPI; NVIDIA CUDA: the PyTorch selector. " + RUNTIME_INSTALL_HINT


def dependency(name):
    try:
        return importlib.import_module(name)
    except Exception:
        hint = CPU_INSTALL_HINT if name in {"torch", "torchvision",
            "open_clip"} else RUNTIME_INSTALL_HINT
        raise AppError("dependency_missing", "A required package is missing or unusable: " + name,
            hint, 6) from None


def resolve_device(requested, torch):
    cuda = torch.cuda.is_available()
    mps = bool(getattr(getattr(torch, "backends", None), "mps",
        None)) and torch.backends.mps.is_available()
    if requested == "auto":
        return "cuda" if cuda else "mps" if mps else "cpu"
    if requested == "cpu":
        return requested
    if requested == "mps" and mps:
        return requested
    if requested == "cuda" and cuda:
        return requested
    if requested.startswith("cuda:") and cuda:
        try:
            if 0 <= int(requested.split(":")[1]) < torch.cuda.device_count():
                return requested
        except ValueError:
            pass
    raise AppError("device_unavailable", "The requested device '" + requested + "' is unavailable.",
        "Use --device cpu or --device auto.", 6)


class OpenClipEmbedder:
    def __init__(self, model, device="cpu", offline=False, batch_size=0):
        offline = offline_mode(offline)
        self.torch = dependency("torch")
        clip = dependency("open_clip")
        self.device = resolve_device(device, self.torch)
        self.batch_size = batch_size or (16 if self.device == "cpu" else 64)
        name = model.get("name") or "ViT-B-32"
        pretrained = model.get("pretrained") or "laion2b_s34b_b79k"
        self.model_id = name + "/" + pretrained
        print("Loading image/text model " + self.model_id +
            (" from the local cache (offline)." if offline else "; using cached weights when available."),
            file=sys.stderr)
        try:
            self.model, _, self.transform = clip.create_model_and_transforms(name,
                pretrained=pretrained, device=self.device, precision="fp32")
            self.model.eval()
            self.model.float()
            self.tokenizer = clip.get_tokenizer(name)
            self.dim = int(self.model.visual.output_dim)
        except Exception:
            raise AppError("model_unavailable", "Image model weights could not be loaded.",
                "Offline mode requires cached weights: run once online or copy the model cache."
                if offline else "Check the model pair and cached weights; first use needs a download.",
                6) from None

    def _encode(self, values, image):
        batches = []
        with self.torch.inference_mode():
            for offset in range(0, len(values), self.batch_size):
                batch = values[offset:offset + self.batch_size]
                tensor = self.torch.stack([self.transform(item) for item in batch]) if image else self.tokenizer(batch)
                tensor = tensor.to(self.device)
                encoded = self.model.encode_image(tensor) if image else self.model.encode_text(tensor)
                batches.append(encoded.float().cpu().numpy())
        return normalise(np.concatenate(batches)) if batches else np.empty((0, self.dim),
            dtype=np.float32)

    def images(self, images):
        return self._encode(images, True)

    def texts(self, texts):
        return self._encode(texts, False)
