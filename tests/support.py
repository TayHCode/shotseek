import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from PIL import Image
from shotseek.names import env

ROOT = Path(__file__).resolve().parents[1]
_ORIGINAL_CONNECT = socket.socket.connect
_ORIGINAL_CREATE = socket.create_connection


def denied(*args, **kwargs):
    raise AssertionError("Network access is disabled in tests")


def network_guard():
    socket.socket.connect = denied
    socket.create_connection = denied


def allow_network():
    socket.socket.connect = _ORIGINAL_CONNECT
    socket.create_connection = _ORIGINAL_CREATE


network_guard()


def repo_files():
    try:
        data = subprocess.check_output(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT)
        return [ROOT / p for p in sorted(set(data.decode().split("\0"))) if p]
    except (OSError, subprocess.CalledProcessError):
        return [p for p in ROOT.rglob("*") if p.is_file() and not any(part in {".git", ".venv", ".scratch", "__pycache__", "build", "dist"} or part.endswith(".egg-info") for part in p.relative_to(ROOT).parts)]


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.library = self.base / "media"
        self.library.mkdir()
        self.index = self.base / "index"
        self.config = self.base / "config.toml"
        self.env = {env("CONFIG"): str(self.config), env("INDEX_DIR"): str(self.index), env("EMBEDDER"): "fake", env("OFFLINE"): "1", "HF_HUB_OFFLINE": "1"}

    def cli(self, *args):
        return run_cli(*args, env=self.env)


def run_cli(*args, env=None):
    child_env = dict(os.environ)
    child_env.update({globals()["env"]("OFFLINE"): "1", "HF_HUB_OFFLINE": "1", globals()["env"]("EMBEDDER"): "fake"})
    child_env.update(env or {})
    done = subprocess.run([sys.executable, "-m", "shotseek", *map(str, args)], env=child_env, capture_output=True, text=True, encoding="utf-8", timeout=60)
    return done.returncode, json.loads(done.stdout), done.stderr


def require_ffmpeg():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise unittest.SkipTest("ffmpeg and ffprobe are required for generated video fixtures")


def make_image(path, color, size=(640, 480), fmt=None, exif_orientation=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", size, color)
    exif = Image.Exif()
    if exif_orientation:
        exif[274] = exif_orientation
    image.save(path, format=fmt, exif=exif)
    return path


def make_video(path, segments=None, size="320x240", audio=False):
    require_ffmpeg()
    segments = segments or [("red", 4), ("green", 4), ("blue", 4)]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
    for color, duration in segments:
        cmd += ["-f", "lavfi", "-i", f"color=c={color}:s={size}:r=10:d={duration}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={sum(x[1] for x in segments)}"]
    graph = "".join(f"[{i}:v]" for i in range(len(segments))) + f"concat=n={len(segments)}:v=1:a=0[v]"
    cmd += ["-filter_complex", graph, "-map", "[v]"]
    if audio:
        cmd += ["-map", f"{len(segments)}:a", "-c:a", "aac"]
    cmd += ["-c:v", "libx264", "-threads", "1", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True, capture_output=True, timeout=30)
    return Path(path)


def make_library(root):
    root = Path(root)
    for i, color in enumerate(("red", "green", "blue", "yellow", "magenta", "cyan")):
        make_image(root / "cafe" / f"mug {i}.jpg", color)
    make_image(root / "hiking" / "café.png", "red")
    make_image(root / "product" / "portrait.jpg", "blue", exif_orientation=6)
    make_video(root / "cafe" / "colors.mp4")
    (root / "zero.jpg").touch()
    (root / "broken.jpg").write_bytes(b"\xff\xd8" + b"x" * 1024)
    (root / "broken.mp4").write_text("not a video")
    make_image(root / "._photo.jpg", "red")
    make_image(root / "@eaDir" / "mug.jpg", "red")
    (root / "mug.cr2").write_bytes(b"x" * 1024)
    (root / "notes.txt").write_text("cafe")


def tree_manifest(root):
    return [(p.relative_to(root).as_posix(), p.stat().st_size, p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None) for p in sorted(Path(root).rglob("*"))]


def validate_schema(value, name, schema=None, location="root"):
    folder = ROOT / "src" / "shotseek" / "schemas"
    schema = schema or json.loads((folder / (name + ".json")).read_text())
    if "$ref" in schema:
        reference = schema["$ref"]
        if "/" in reference or not reference.endswith(".json"):
            raise AssertionError("Only sibling schema references are supported")
        return validate_schema(value, reference[:-5], location=location)
    types = schema.get("type", [])
    types = [types] if isinstance(types, str) else types
    checks = {"object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list), "string": lambda v: isinstance(v, str), "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool), "integer": lambda v: isinstance(v, int) and not isinstance(v, bool), "boolean": lambda v: isinstance(v, bool), "null": lambda v: v is None}
    if types and not any(checks[t](value) for t in types):
        raise AssertionError(location + ": wrong type")
    if "enum" in schema and value not in schema["enum"]:
        raise AssertionError(location + ": invalid enum")
    if isinstance(value, dict):
        missing = set(schema.get("required", [])) - value.keys()
        if missing:
            raise AssertionError(location + ": missing " + ",".join(sorted(missing)))
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                validate_schema(item, name, properties[key], location + "." + key)
            elif schema.get("additionalProperties") is False:
                raise AssertionError(location + ": unknown " + key)
            elif isinstance(schema.get("additionalProperties"), dict):
                validate_schema(item, name, schema["additionalProperties"], location + "." + key)
    if isinstance(value, list) and "items" in schema:
        for number, item in enumerate(value):
            validate_schema(item, name, schema["items"], location + f"[{number}]")
