import shutil
import subprocess
from . import MediaError
from ..errors import AppError


# Restrict media inputs to local files for both FFmpeg programs.
LOCAL_INPUT = ["-" + "protocol_whitelist", "file"]


def require():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise AppError("ffmpeg_missing", "ffmpeg and ffprobe must be on PATH.",
            "Install ffmpeg and retry.", 6)


def run(args, timeout, popen=None):
    try:
        process = (popen or subprocess.Popen)(list(map(str, args)), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        raise AppError("ffmpeg_missing", "A required media program is missing.",
            "Install ffmpeg and ffprobe.", 6) from None
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        raise MediaError("timeout") from None
    if process.returncode:
        raise MediaError("decode_failed")
    return stdout
