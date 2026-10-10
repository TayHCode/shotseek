from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import math
import time
from . import MediaError, orientation
from .ffmpeg import LOCAL_INPUT
from .quality import quality
from ..paths import absolute
from ..sampling import sample_timestamps
from .frames_cv import extract_frame, bgr_to_pil, save_thumbnail as save_thumbnail


from ..walker import discover_video_files as discover_video_files


def probe_video(path: Path, timeout=60) -> dict[str, Any] | None:
    try:
        data = probe(path, timeout)
        info = video_info(data)
    except MediaError:
        return None
    stream = next(s for s in data["streams"] if s.get("codec_type") == "video")
    fmt = data.get("format", {})
    return {
        "path": str(path), "filename": path.name, "folder": str(path.parent),
        "duration": round(info["duration"], 3), "size": int(fmt.get("size", 0) or 0),
        "width": info["width"], "height": info["height"],
        "frame_rate": stream.get("r_frame_rate", ""),
    }


def probe(path, timeout=60):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", *LOCAL_INPUT,
             "-show_entries", "stream=codec_type,width,height,r_frame_rate,duration",
             "-show_entries", "stream_tags=rotate,creation_time:stream_side_data=rotation",
             "-show_entries", "format=duration,size,format_name:format_tags=creation_time",
             "-of", "json", str(absolute(path))],
            check=True, capture_output=True, text=True, timeout=timeout,
        )
        return json.loads(result.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
        raise MediaError("probe_failed") from None


def require_container(data):
    allowed = {"mov", "mp4", "m4a", "3gp", "3g2", "mj2", "matroska", "webm",
               "avi", "mpegts", "mpeg", "asf"}
    names = set(data.get("format", {}).get("format_name", "").split(","))
    if not names & allowed:
        raise MediaError("unsupported_container")


def sample_times(duration, interval=5, max_frames=60, mode="interval", samples=4):
    times = sample_timestamps(duration, samples, interval if mode == "interval" else 0,
                              max_frames)
    step = times[1] - times[0] if len(times) > 1 else duration
    return [round(t * 1000) for t in times], step


def frame(path, t_ms, timeout=60, reader="auto", checked=False):
    from .frames_ffmpeg import frame as fallback
    if not checked:
        require_container(probe(path, timeout))
    if reader != "ffmpeg":
        try:
            pixels = extract_frame(path, t_ms / 1000, checked=True)
            if pixels is not None:
                return bgr_to_pil(pixels)
        except Exception:
            # Decoder bindings can raise backend-specific exception classes.
            pass
    return fallback(path, t_ms, timeout)


def load_video(path, settings):
    started = time.monotonic()
    data = probe(path, min(60, settings["file_timeout_seconds"]))
    metadata = video_info(data)
    require_container(data)
    times, step = sample_times(
        metadata["duration"], settings["video_frame_interval_seconds"],
        settings["video_max_frames"], settings.get("video_sampling", "interval"),
        settings.get("video_samples_per_file", 4),
    )
    frames = []
    for t_ms in times:
        remaining = settings["video_timeout_seconds"] - (time.monotonic() - started)
        if remaining <= 0:
            break
        try:
            image = frame(path, t_ms, min(settings["frame_timeout_seconds"], remaining),
                          settings.get("frame_reader", "auto"), checked=True)
            frames.append(dict(image=image, t_ms=t_ms, **quality(image)))
        except MediaError:
            continue
    if not frames:
        raise MediaError("no_frames")
    return dict(metadata, sample_interval=step, frames=frames)

def video_info(data):
    try:
        video = next(s for s in data["streams"] if s["codec_type"] == "video")
        duration = float(data.get("format", {}).get("duration", video.get("duration", 0)))
        width, height = int(video["width"]), int(video["height"])
        if not math.isfinite(duration) or duration <= 0 or width <= 0 or height <= 0:
            raise ValueError
        rotation = float(video.get("tags", {}).get("rotate", 0))
        for side in video.get("side_data_list", []):
            rotation = side.get("rotation", rotation)
        if abs(rotation) % 180 == 90:
            width, height = height, width
        captured = video.get("tags", {}).get("creation_time") or data.get("format", {}).get("tags",
            {}).get("creation_time")
        return dict(width=width, height=height, duration=duration, orientation=orientation(width,
            height), captured_at=captured)
    except (KeyError, StopIteration, TypeError, ValueError):
        raise MediaError("probe_failed") from None
