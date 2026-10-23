import contextlib
import os
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch
import numpy as np
from tests import support as support  # Activates the test network guard.
from shotseek.embed.openclip import OpenClipEmbedder, resolve_device, dependency
from shotseek.transcribe.whisper import WhisperTranscriber
from shotseek.errors import AppError


class Tensor:
    def __init__(self, value):
        self.value = np.asarray(value)
    def to(self, *a):
        return self
    def float(self):
        return self
    def cpu(self):
        return self
    def numpy(self):
        return self.value


def torch_stub(cuda=False, mps=False):
    return NS(cuda=NS(is_available=lambda: cuda, device_count=lambda: 1), backends=NS(mps=NS(is_available=lambda: mps)), inference_mode=contextlib.nullcontext, stack=lambda values: Tensor(np.asarray([v.value for v in values])))


class Backends(unittest.TestCase):
    def test_only_routine_hub_account_message_is_filtered(self):
        import io
        import logging
        from shotseek.embed.openclip import offline_mode
        logger = logging.getLogger("huggingface_hub.utils._http")
        previous = list(logger.filters)
        out = io.StringIO()
        handler = logging.StreamHandler(out)
        logger.addHandler(handler)
        try:
            with patch.dict(os.environ):
                offline_mode()
            logger.warning("Warning: You are sending unauthenticated requests to the HF Hub. More details.")
            logger.warning("Rate limit exceeded; retry later.")
            logger.warning("Download failed: connection refused.")
            self.assertNotIn("unauthenticated", out.getvalue())
            self.assertIn("Rate limit exceeded", out.getvalue())
            self.assertIn("Download failed", out.getvalue())
        finally:
            logger.removeHandler(handler)
            logger.filters[:] = previous

    def test_devices(self):
        self.assertEqual(resolve_device("cpu", torch_stub()), "cpu")
        self.assertEqual(resolve_device("auto", torch_stub()), "cpu")
        self.assertEqual(resolve_device("auto", torch_stub(True)), "cuda")
        self.assertEqual(resolve_device("auto", torch_stub(mps=True)), "mps")
        self.assertEqual(resolve_device("cuda:0", torch_stub(True)), "cuda:0")
        for device in ("cuda", "cuda:1", "mps"):
            with self.assertRaises(AppError) as error:
                resolve_device(device, torch_stub())
            self.assertEqual(error.exception.code, "device_unavailable")

    def test_embedding_offline_dtype_and_batches(self):
        torch = torch_stub()
        model = NS(visual=NS(output_dim=3), eval=lambda: None, float=lambda: None, encode_image=lambda t: t, encode_text=lambda t: t)
        def create(*a, **k):
            self.assertEqual(os.environ["HF_HUB_OFFLINE"], "1")
            self.assertEqual(os.environ["HF_HUB_DISABLE_TELEMETRY"], "1")
            self.assertEqual(k["precision"], "fp32")
            return model, None, lambda image: Tensor([3, 4, 0])
        clip = NS(create_model_and_transforms=create, get_tokenizer=lambda name: lambda texts: Tensor([[0, 3, 4]] * len(texts)))
        with patch.dict(sys.modules, {"torch": torch, "open_clip": clip}), patch.dict(os.environ, {}, clear=False):
            backend = OpenClipEmbedder({}, offline=True)
            self.assertEqual(backend.batch_size, 16)
            values = backend.texts(["cafe", "trail"])
            self.assertEqual(values.dtype, np.float32)
            np.testing.assert_allclose(np.linalg.norm(values, axis=1), 1)
            self.assertEqual(backend.images([None]).shape, (1, 3))
            torch.cuda.is_available = lambda: True
            self.assertEqual(OpenClipEmbedder({}, device="cuda", offline=True).batch_size, 64)

    def test_missing_dependency(self):
        with patch("shotseek.embed.openclip.importlib.import_module", side_effect=ImportError):
            with self.assertRaises(AppError) as error:
                dependency("open_clip")
        self.assertEqual(error.exception.code, "dependency_missing")

    def test_incompatible_image_dependency(self):
        def imports(name):
            if name == "torch":
                return torch_stub()
            raise RuntimeError("operator torchvision::nms does not exist")
        with patch("shotseek.embed.openclip.importlib.import_module", side_effect=imports):
            with self.assertRaises(AppError) as error:
                OpenClipEmbedder({}, offline=True)
        self.assertEqual(error.exception.code, "dependency_missing")
        self.assertEqual(error.exception.exit_code, 6)
        self.assertIn("torch and torchvision together", error.exception.hint)

    def test_native_dependency_failure_names_windows_runtime(self):
        for name in ("torch", "torchvision", "open_clip", "faster_whisper"):
            with self.subTest(name=name), patch(
                "shotseek.embed.openclip.importlib.import_module", side_effect=OSError("DLL load failed")
            ):
                with self.assertRaises(AppError) as error:
                    dependency(name)
                self.assertEqual(error.exception.code, "dependency_missing")
                self.assertEqual(error.exception.exit_code, 6)
                self.assertIn("Visual C++", error.exception.hint)

    def test_speech_cuda_fallback(self):
        calls = []
        def create(model, **kwargs):
            calls.append(kwargs)
            if kwargs["device"] == "cuda":
                raise RuntimeError()
            return NS(transcribe=lambda *a, **k: ([NS(start=0., end=2., text=" coffee ")], NS(language="en")))
        with patch.dict(sys.modules, {"faster_whisper": NS(WhisperModel=create), "ctranslate2": NS(get_cuda_device_count=lambda: 1)}), patch.dict(os.environ):
            speech = WhisperTranscriber("tiny", "cuda", True)
            self.assertEqual([c["compute_type"] for c in calls], ["float16", "int8"])
            self.assertEqual(speech.warnings[0]["code"], "whisper_cuda_unavailable")
            self.assertEqual(speech.transcribe("unused")[0][0]["text"], "coffee")
