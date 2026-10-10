"""Optional numerical comparison of the direct model calls and fitted frames."""
import json
import os
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from tests.support import ROOT
from shotseek.names import env


@unittest.skipUnless(os.environ.get(env("RUN_SLOW")) == "1",
                     "opt-in reference embedding test; set " + env("RUN_SLOW") + "=1")
class ReferenceEmbedding(unittest.TestCase):
    def test_reference_calls_and_prefit(self):
        from shotseek.embed.openclip import OpenClipEmbedder
        from shotseek.media.frames_cv import backend as cv_backend
        import open_clip
        import torch
        torch.set_num_threads(min(8, os.cpu_count() or 1))
        images = []
        for color, shape in [("red", "circle"), ("blue", "square"), ("green", "word")]:
            image = Image.new("RGB", (1280, 960), "white")
            draw = ImageDraw.Draw(image)
            if shape == "circle":
                draw.ellipse((300, 150, 950, 800), fill=color)
            elif shape == "square":
                draw.rectangle((300, 150, 950, 800), fill=color)
            else:
                draw.text((640, 480), "COFFEE", fill=color,
                          font=ImageFont.load_default(size=128), anchor="mm")
            images.append(image)
        images.append(Image.new("RGB", (960, 540), "red"))
        queries = ["a red circle", "a blue square", "the word coffee", "a solid red image"]
        with patch.dict(os.environ, {"HF_HUB_OFFLINE": "1"}):
            port = OpenClipEmbedder({}, "cpu", offline=True)
            actual_images, actual_text = port.images(images), port.texts(queries)
            cv = cv_backend()
            fitted = []
            for image in images:
                pixels = np.asarray(image)
                scale = 448 / max(image.size)
                pixels = cv.resize(pixels, (int(image.width * scale), int(image.height * scale)),
                                   interpolation=cv.INTER_AREA)
                fitted.append(Image.fromarray(pixels))
            smaller = port.images(fitted)
            del port
            model, _, preprocess = open_clip.create_model_and_transforms(
                "ViT-B-32", pretrained="laion2b_s34b_b79k", device="cpu"
            )
            model.eval()
            tokenizer = open_clip.get_tokenizer("ViT-B-32")
            with torch.no_grad():
                values = model.encode_image(torch.stack([preprocess(image) for image in images]).to("cpu"))
                reference_images = (values / values.norm(dim=-1,
                    keepdim=True).clamp_min(1e-12)).detach().cpu().numpy().astype(np.float32)
                values = model.encode_text(tokenizer(queries).to("cpu"))
                reference_text = (values / values.norm(dim=-1,
                    keepdim=True).clamp_min(1e-12)).detach().cpu().numpy().astype(np.float32)
        image_error = float(np.max(np.abs(actual_images - reference_images)))
        text_error = float(np.max(np.abs(actual_text - reference_text)))
        cosine_change = float(np.max(np.abs(1 - np.sum(actual_images * smaller, axis=1))))
        self.assertLessEqual(image_error, 1e-4)
        self.assertLessEqual(text_error, 1e-4)
        self.assertLess(cosine_change, .01)
        result = dict(image_max_absolute_error=image_error, text_max_absolute_error=text_error,
                      prefit_max_cosine_change=cosine_change, generated_images=len(images))
        (ROOT / ".scratch").mkdir(exist_ok=True)
        (ROOT / ".scratch/measurements-reference.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))
