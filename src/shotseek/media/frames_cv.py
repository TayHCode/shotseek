from pathlib import Path
import os
from PIL import Image


def backend():
    os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "protocol_whitelist;file")
    import cv2
    return cv2


def extract_frame(video_path: Path, timestamp: float, checked=False):
    if not checked:
        from .videos import probe, require_container
        from . import MediaError
        try:
            require_container(probe(video_path))
        except MediaError:
            return None
    cv2 = backend()
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        cap.release()
        return None
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(timestamp * fps))
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        return None
    height, width = frame.shape[:2]
    if max(width, height) > 448:
        scale = 448 / max(width, height)
        frame = cv2.resize(frame, (max(1, int(width * scale)), max(1, int(height * scale))),
                           interpolation=cv2.INTER_AREA)
    return frame


def save_thumbnail(frame, path: Path, max_width: int = 640) -> None:
    cv2 = backend()
    path.parent.mkdir(parents=True, exist_ok=True)
    height, width = frame.shape[:2]
    if width > max_width:
        scale = max_width / width
        frame = cv2.resize(frame, (max_width, int(height * scale)), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])


def bgr_to_pil(frame) -> Image.Image:
    cv2 = backend()
    return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

