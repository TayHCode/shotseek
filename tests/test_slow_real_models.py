import json
import os
from pathlib import Path
import time
import unittest
from unittest.mock import patch
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from tests.support import Sandbox, ROOT, make_image, make_video
from shotseek.names import env


@unittest.skipUnless(os.environ.get(env("RUN_SLOW")) == "1",
    "opt-in real model test; set " + env("RUN_SLOW") + "=1")
class RealModels(Sandbox):
    def test_generated_semantics_speech_and_speed(self):
        environment = dict(os.environ)
        for name in (env("EMBEDDER"), env("TRANSCRIBER")):
            environment.pop(name, None)
        environment.update({env("OFFLINE"): "1", "HF_HUB_OFFLINE": "1"})
        with patch.dict(os.environ, environment, clear=True):
            from shotseek.cli import build_parser
            from shotseek.config import validate, write
            from shotseek.embed.openclip import OpenClipEmbedder
            from shotseek.indexer import run
            from shotseek.search import command as search
            from shotseek.transcribe import command as transcribe
            from shotseek.broll import command as broll
            from shotseek.media.ffmpeg import run as media_run
            import open_clip
            import torch
            torch.set_num_threads(min(8, os.cpu_count() or 1))
            pairs = open_clip.list_pretrained()
            self.assertIn(("ViT-B-32", "laion2b_s34b_b79k"), pairs)
            self.assertIn(("ViT-L-14", "laion2b_s32b_b82k"), pairs)
            started = time.monotonic()
            model = OpenClipEmbedder({}, "cpu")
            load_seconds = time.monotonic() - started
            for color in ("red", "green", "blue", "yellow", "cyan", "magenta", "black", "white"):
                make_image(self.library / (color + ".jpg"), color)
            for shape, color in (("circle", "red"), ("square", "blue")):
                image = Image.new("RGB", (640, 480), "white")
                draw = ImageDraw.Draw(image)
                (draw.ellipse if shape == "circle" else draw.rectangle)((180, 100, 460, 380), fill=color)
                image.save(self.library / (shape + ".jpg"))
            for word in ("COFFEE", "TRAIL", "MUG"):
                for size in (64, 80):
                    image = Image.new("RGB", (640, 480), "white")
                    draw = ImageDraw.Draw(image)
                    font = ImageFont.load_default(size=size)
                    draw.text((320, 240), word, fill="black", font=font, anchor="mm")
                    image.save(self.library / (word.lower() + str(size) + ".jpg"))
            rng = np.random.default_rng(27)
            for i in range(40):
                pixels = rng.integers(0, 256, (32, 32, 3), dtype=np.uint8)
                Image.fromarray(pixels).resize((640, 480)).save(self.library / f"texture{i}.jpg")
            make_video(self.library / "colors.mp4")
            data = validate({"library": [dict(name="media", root=str(self.library))],
                "index": {"dir": str(self.index)}})
            write(self.config, data)
            os.environ[env("CONFIG")] = str(self.config)
            os.environ[env("INDEX_DIR")] = str(self.index)
            args = build_parser().parse_args(["index", "--progress", "none"])
            started = time.monotonic()
            indexed = run(args, data, self.index, embedder=model)
            mixed_index_seconds = time.monotonic() - started
            self.assertEqual(indexed["totals"]["files_indexed"], 57)
            semantic_results = []
            for query, expected in (("a solid red image", "red.jpg"),
                ("the word coffee printed in large letters", "coffee")):
                query_args = build_parser().parse_args([
                    "search", query, "--media", "photo", "--offline", "--include-blank"
                ])
                started = time.monotonic()
                result = search(query_args)["queries"][0]["results"][0]
                first_seconds = time.monotonic() - started
                started = time.monotonic()
                repeated = search(query_args)["queries"][0]["results"][0]
                cached_seconds = time.monotonic() - started
                self.assertEqual(repeated["filename"], result["filename"])
                semantic_results.append(dict(
                    query=query, filename=result["filename"], relevance=result["relevance"],
                    first_seconds=first_seconds, cached_seconds=cached_seconds
                ))
                with self.subTest(query=query):
                    self.assertTrue(result["filename"].startswith(expected), result["filename"])
                    self.assertGreater(result["relevance"], 2)
            filters = media_run(["ffmpeg", "-hide_banner", "-filters"], 10)
            self.assertIn(b"flite", filters, "The speech fixture requires ffmpeg's flite source")
            aroll = self.base / "aroll.mp4"
            media_run([
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=red:s=320x240:r=10:d=20",
                "-f", "lavfi", "-i",
                "flite=text='We are making a cup of coffee. "
                "We are walking along a hiking trail.':voice=slt",
                "-shortest", "-c:v", "libx264", "-threads", "1", "-c:a", "aac", str(aroll)
            ], 60)
            speech_args = build_parser().parse_args(["transcribe", str(aroll)])
            started = time.monotonic()
            speech = transcribe(speech_args)
            speech_seconds = time.monotonic() - started
            text = " ".join(row["text"] for row in speech["transcript"]["segments"]).lower()
            self.assertEqual(speech["source"]["whisper_model"], "base")
            self.assertFalse(speech["source"]["transcript_cached"])
            self.assertIn("coffee", text)
            self.assertIn("trail", text)
            self.assertFalse(list((self.index / "tmp").glob("*.wav")))
            started = time.monotonic()
            repeated_speech = transcribe(speech_args)
            cached_speech_seconds = time.monotonic() - started
            self.assertTrue(repeated_speech["source"]["transcript_cached"])
            self.assertEqual(repeated_speech["transcript"], speech["transcript"])
            started = time.monotonic()
            matches = broll(build_parser().parse_args([
                "broll", "--aroll", str(aroll), "--include-filler"
            ]))
            broll_seconds = time.monotonic() - started
            self.assertTrue(any(beat["candidates"] for beat in matches["beats"]))
            bench_library = self.base / "benchmark"
            bench_library.mkdir()
            for i in range(300):
                make_image(bench_library / f"mug{i}.jpg", tuple(int(v) for v in rng.integers(20,
                    230, 3)))
            bench_index = self.base / "benchmark-index"
            bench = validate({"library": [dict(name="media", root=str(bench_library))]})
            started = time.monotonic()
            result = run(args, bench, bench_index, embedder=model)
            photo_seconds = time.monotonic() - started
            self.assertEqual(result["totals"]["files_indexed"], 300)
            make_video(bench_library / "colors.mp4", segments=[("red", 20), ("green", 20), ("blue", 20)])
            started = time.monotonic()
            result = run(args, bench, bench_index, embedder=model)
            video_seconds = time.monotonic() - started
            self.assertEqual(result["totals"]["vectors_added"], 12)
            sizes = [p.stat().st_size for p in (bench_index / "thumbs").rglob("*.jpg")]
            hf = Path(os.environ["HF_HOME"])
            blobs = [p for p in hf.rglob("*") if p.is_file() and not p.is_symlink()]
            report = dict(
                device="cpu", torch_threads=torch.get_num_threads(),
                model_load_seconds=load_seconds, mixed_files=57,
                mixed_index_seconds=mixed_index_seconds, semantic_results=semantic_results,
                speech_model="base", speech_seconds=speech_seconds,
                speech_duration=speech["source"]["duration"],
                speech_segments=len(speech["transcript"]["segments"]),
                cached_speech_seconds=cached_speech_seconds, broll_seconds=broll_seconds,
                base_speech_verified=True, photos=300, photo_seconds=photo_seconds,
                photos_per_second=300 / photo_seconds, video_frames=12,
                video_seconds=video_seconds, video_frames_per_second=12 / video_seconds,
                thumbnail_mean_bytes=sum(sizes) / len(sizes),
                model_cache_bytes=sum(p.stat().st_size for p in blobs)
            )
            (ROOT / ".scratch").mkdir(exist_ok=True)
            (ROOT / ".scratch/measurements-real.json").write_text(json.dumps(report, indent=2))
            print(json.dumps(report))
