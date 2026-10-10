"""Local installation diagnostics. Never fetches model weights."""
import importlib
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from . import config
from .embed.openclip import CPU_INSTALL_HINT, offline_mode, resolve_device
from .errors import AppError
from .paths import filesystem_path, writable
from .probe import bounded_probe
from .store.db import Store


def root_probe(path):
    def listing():
        with os.scandir(filesystem_path(path)) as entries:
            next(entries, None)
        return True
    return bounded_probe(listing)[0]


def inspect(args, imports=None, which=None, roots=None):
    offline_mode(args.offline)
    imports, which, roots = imports or importlib.import_module, which or shutil.which, roots or root_probe
    checks = []
    image_runtime = None
    device_failure = None
    def add(ident, status, detail, hint=""):
        checks.append(dict(id=ident, status=status, detail=detail, hint=hint))
    add("python", "ok" if sys.version_info >= (3, 11) else "fail", sys.version.split()[0],
        "Python 3.11 or newer is required.")
    for binary in ("ffmpeg", "ffprobe"):
        available = which(binary)
        add(binary, "ok" if available else "fail", "Available" if available else "Missing",
            "Install ffmpeg and ffprobe." if not available else "")
    for ident, module in (("numpy", "numpy"), ("pillow", "PIL"), ("heic", "pillow_heif"), ("opencv",
        "cv2"), ("torch", "torch"), ("torchvision", "torchvision"), ("open_clip", "open_clip"),
        ("faster_whisper", "faster_whisper")):
        try:
            if ident == "opencv":
                os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "protocol_whitelist;file")
            loaded = imports(module)
            detail = str(getattr(loaded, "__version__", "Available"))
            if ident == "torch":
                image_runtime = loaded
                detail += "; CUDA runtime=" + str(getattr(loaded.version, "cuda", None) or "none")
                detail += "; CUDA available=" + str(loaded.cuda.is_available())
                if loaded.cuda.is_available():
                    detail += "; device=" + loaded.cuda.get_device_name(0)
                detail += "; MPS=" + str(bool(getattr(getattr(loaded, "backends", None), "mps",
                    None)) and loaded.backends.mps.is_available())
            if ident == "faster_whisper":
                detail += "; CUDA devices=" + str(imports("ctranslate2").get_cuda_device_count())
            if ident == "torchvision":
                torch = imports("torch")
                loaded.ops.nms(torch.zeros((1, 4)), torch.ones(1), 0.5)
                detail += "; CPU operators available"
            add(ident, "ok", detail)
        except Exception:
            hint = CPU_INSTALL_HINT if ident in {"torch", "torchvision",
                "open_clip"} else "Install the runtime dependencies."
            add(ident, "warn" if ident == "heic" else "fail", "Missing or unusable package", hint)
    try:
        data, path, index = config.load(args, optional=True)
        add("config", "ok" if path.exists() else "warn",
            "Available" if path.exists() else "No configuration",
            "Run init to choose a library." if not path.exists() else "")
    except AppError as exc:
        add("config", "fail", exc.message, exc.hint)
        data, path, index = None, None, None
    if data and image_runtime is not None:
        try:
            selected = resolve_device(config.device(data, args.device), image_runtime)
            add("device", "ok", "Selected image device: " + selected)
        except AppError as exc:
            device_failure = exc
            add("device", "fail", exc.message, exc.hint)
    if data:
        for library in data["library"]:
            reachable = roots(library["root"])
            add("library:" + library["name"], "ok" if reachable else "fail",
                "Reachable" if reachable else "Listing failed or exceeded ten seconds",
                "Check the drive or mount." if not reachable else "")
        try:
            writable(index, data["library"], "index_inside_library")
            ancestor = index
            while not ancestor.exists() and ancestor != ancestor.parent:
                ancestor = ancestor.parent
            writable_here = ancestor.is_dir() and os.access(ancestor, os.W_OK)
            status = "ok" if writable_here else "fail"
            detail = "Writable" if writable_here else "Not writable"
            if sys.platform.startswith("linux"):
                try:
                    candidates = []
                    for line in Path("/proc/mounts").read_text().splitlines():
                        parts = line.split()
                        mount = Path(parts[1].replace("\\040", " "))
                        if index.is_relative_to(mount):
                            candidates.append((len(str(mount)), parts[2]))
                    filesystem = max(candidates)[1] if candidates else ""
                    if filesystem in {"nfs", "nfs4", "cifs", "smb3"} or filesystem.startswith("fuse."):
                        status, detail = "warn", "The index appears to be on mounted storage"
                except OSError:
                    pass
            add("index_dir", status, detail,
                "Keep the index on a writable local disk." if status != "ok" else "")
        except AppError as exc:
            add("index_dir", "fail", exc.message, exc.hint)
        if (index / "meta.sqlite").exists():
            try:
                with Store(index) as store:
                    info, matrix = store.snapshot()
                    add("index", "ok", "Format 1; " + info["model_id"])
            except AppError as exc:
                add("index", "fail", exc.message, exc.hint)
        else:
            add("index", "warn", "No built index", "Run index after init.")
    summary = {status: sum(c["status"] == status for c in checks) for status in ("ok", "warn", "fail")}
    result = dict(checks=checks, summary=summary, _exit=6 if summary["fail"] else 0)
    if summary["fail"]:
        failure = device_failure if device_failure and summary["fail"] == 1 else AppError("dependency_missing",
            "One or more local checks failed.", "Review the checks and hints.", 6)
        result.update(ok=False, error=failure.as_dict())
    return result


def command(args, **fakes):
    result = inspect(args, **fakes)
    if getattr(args, "report", False):
        text, passed = platform_report(args, result)
        if not passed:
            result["_exit"] = result["_exit"] or 6
            result.update(ok=False)
        result["_raw"] = text
    return result


def tilde(text):
    """Replace the home directory so the report holds no personal paths."""
    home = str(Path.home())
    return str(text).replace(home, "~") if home and home != "/" else str(text)


def cpu_name():
    if sys.platform == "darwin":
        try:
            done = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True, timeout=2, check=True)
            if done.stdout.strip():
                return done.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine() or "unknown"


def model_cache():
    """Return (found, location) for the default image model, without importing torch."""
    base = os.environ.get("HF_HUB_CACHE") or os.path.join(
        os.environ.get("HF_HOME") or os.path.join(os.path.expanduser("~"), ".cache", "huggingface"), "hub")
    hits = sorted(Path(base).glob("models--*B-32*laion2B*s34B*b79K*")) if Path(base).is_dir() else []
    return bool(hits), tilde(base)


def smoke_test(args, python=None):
    """Index and search three generated photos in a scratch folder; returns (passed, detail)."""
    from PIL import Image
    python = python or sys.executable
    data, _, _ = config.load(args, optional=True)
    selected = config.device(data, args.device)
    with tempfile.TemporaryDirectory(prefix="shotseek-doctor-") as scratch:
        root = Path(scratch)
        media = root / "media"
        media.mkdir()
        for i, colour in enumerate(("red", "green", "blue")):
            Image.new("RGB", (96, 64), colour).save(media / (colour + ".jpg"))
        base = [python, "-m", "shotseek"]
        shared = ["--config", str(root / "config.toml"), "--index-dir", str(root / "index"), "--quiet"]
        extra = ["--offline"] if getattr(args, "offline", False) else []
        extra += ["--device", selected]
        steps = [(["init", "--library", "media=" + str(media)], []), (["index", "--progress", "none"], extra),
            (["search", "red", "--max-per-file", "1"], extra)]
        results = []
        for words, options in steps:
            try:
                done = subprocess.run(base + words + options + shared, capture_output=True, text=True, encoding="utf-8",
                    timeout=1800)
                payload = json.loads(done.stdout.strip().splitlines()[-1]) if done.stdout.strip() else {}
            except (OSError, ValueError, subprocess.TimeoutExpired):
                return False, words[0] + " did not complete"
            if done.returncode != 0 or not payload.get("ok", False):
                error = payload.get("error", {})
                return False, words[0] + " failed: " + str(error.get("code", "exit " + str(done.returncode)))
            results.append(payload)
        found = results[-1].get("queries", [{}])[0].get("results", [])
        if len(found) < 1:
            return False, "search returned no results"
        return True, "indexed 3 generated red/green/blue photos and searched; top fixture result " + Path(str(found[0].get("path", "?"))).name


def platform_report(args, result):
    """Plain text for pasting into an issue. Uses ~ for the home folder; no media or config paths."""
    import importlib.metadata as metadata
    try:
        version = metadata.version("shotseek")
    except metadata.PackageNotFoundError:
        version = "unknown"
    by_id = {c["id"]: c for c in result["checks"]}
    torch = by_id.get("torch", {})
    failed = [c for c in result["checks"] if c["status"] == "fail"]
    if failed:
        passed, detail = False, "local checks failed; sample not run"
    else:
        passed, detail = smoke_test(args)
    cached, where = model_cache()
    lines = ["shotseek platform report", "shotseek: " + version,
        "OS: {} {} ({})".format(platform.system(), platform.release(), platform.machine()),
        "Python: {} ({})".format(platform.python_version(), platform.python_implementation()),
        "CPU: " + cpu_name(),
        "Accelerator: " + (torch.get("detail", "torch unavailable")),
        "ffmpeg: " + by_id.get("ffmpeg", {}).get("detail", "unknown"),
        "ffprobe: " + by_id.get("ffprobe", {}).get("detail", "unknown"),
        "Model cache: {} ({})".format("present" if cached else "absent", where)]
    if "device" in by_id:
        check = by_id["device"]
        lines.append("Image device: {} {} {}".format(check["status"], check["detail"], check["hint"]).rstrip())
    for check in failed:
        if check["id"] != "device":
            lines.append("{}: fail {} {}".format(check["id"], check["detail"], check["hint"]).rstrip())
    for ident in ("numpy", "pillow", "heic", "opencv", "torchvision", "open_clip", "faster_whisper"):
        if ident in by_id:
            lines.append("{}: {} {}".format(ident, by_id[ident]["status"], by_id[ident]["detail"]))
    lines.append("Sample index and search (3 files): {} - {}".format("PASS" if passed else "FAIL", detail))
    lines.append("Doctor checks: {ok} ok, {warn} warn, {fail} fail".format(**result["summary"]))
    return tilde("\n".join(lines)), passed
