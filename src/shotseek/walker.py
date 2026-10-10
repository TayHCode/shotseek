"""Streaming discovery with bounded buffering and explicit traversal state."""
from dataclasses import dataclass
import fnmatch
import os
from pathlib import Path
import queue
import threading
from .paths import filesystem_path

PHOTOS = set(".jpg .jpeg .png .webp .bmp .gif .tif .tiff .heic .heif .avif".split())
VIDEOS = set(".mp4 .mov .m4v .mkv .avi .webm .mts .m2ts .mpg .mpeg .wmv .3gp".split())
RAW = set(".cr2 .cr3 .nef .arw .dng .raf .orf .rw2 .srw .pef".split())
SKIP_DIRS = {"@eaDir", "#recycle", "$RECYCLE.BIN", "System Volume Information", "lost+found",
    ".Trashes", ".tmp.drivedownload", ".tmp.driveupload"}


@dataclass
class Entry:
    path: Path
    relpath: str
    kind: str
    ext: str
    size: int
    mtime_ns: int


def classify(path):
    ext = Path(path).suffix.lower()
    return "photo" if ext in PHOTOS | RAW else "video" if ext in VIDEOS else None


def walk(library, settings, state, stop=None):
    root = filesystem_path(library["root"])
    stack = [root]
    visited = set()
    state.update(reachable=False, walk_complete=False, listing_errors=0)
    while stack and not (stop and stop.is_set()):
        directory = stack.pop()
        try:
            if settings["follow_symlinks"]:
                stat = directory.stat()
                # Some mounted providers do not expose usable inode numbers.
                filesystem_id = (stat.st_dev, stat.st_ino) if stat.st_ino else (
                    "path", os.path.normcase(str(directory.resolve())))
                if filesystem_id in visited:
                    continue
                visited.add(filesystem_id)
            with os.scandir(directory) as entries:
                if directory == root:
                    state["reachable"] = True
                for item in entries:
                    if stop and stop.is_set():
                        return
                    rel = Path(item.path).relative_to(root).as_posix()
                    if item.name.startswith(".") or item.name in SKIP_DIRS or any(fnmatch.fnmatchcase(rel,
                        pat) for pat in settings["exclude"] + library.get("exclude", [])):
                        continue
                    try:
                        if not settings["follow_symlinks"] and item.is_symlink():
                            continue
                        if item.is_dir(follow_symlinks=settings["follow_symlinks"]):
                            stack.append(Path(item.path))
                        else:
                            kind = classify(item.path)
                            if kind and item.is_file():
                                stat = item.stat()
                                yield Entry(Path(item.path), rel, kind,
                                    Path(item.path).suffix.lower(), stat.st_size, stat.st_mtime_ns)
                    except OSError:
                        state["listing_errors"] += 1
        except OSError:
            state["listing_errors"] += 1
    state["walk_complete"] = state["reachable"] and not state["listing_errors"] and not (stop and stop.is_set())


class Discovery:
    def __init__(self, libraries, settings, stop):
        self.queue = queue.Queue(maxsize=10000)
        self.states = {lib["name"]: {"reachable": False, "walk_complete": False,
            "listing_errors": 0} for lib in libraries}
        self.done = threading.Event()
        self.stop = stop

        def produce():
            try:
                for library in libraries:
                    for entry in walk(library, settings, self.states[library["name"]], stop):
                        while not stop.is_set():
                            try:
                                self.queue.put((library, entry), timeout=.1)
                                break
                            except queue.Full:
                                pass
                        if stop.is_set():
                            return
            finally:
                self.done.set()
        self.thread = threading.Thread(target=produce, daemon=True)
        self.thread.start()


def discover_video_files(roots, max_videos=0, max_videos_per_root=0):
    from .config import DEFAULTS
    found = []
    for root in roots:
        root = Path(root)
        if root.is_file():
            candidates = [root] if classify(root) == "video" else []
        else:
            candidates = (entry.path for entry in walk(
                {"root": str(root)}, DEFAULTS["indexing"], {}
            ) if entry.kind == "video")
        count = 0
        for path in candidates:
            found.append(path)
            count += 1
            if max_videos and len(found) >= max_videos:
                return found
            if max_videos_per_root and count >= max_videos_per_root:
                break
    return found
