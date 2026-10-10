"""Conservative A-roll identity checks without full-file reads."""
import hashlib
import os
import stat as file_mode
import time
import numpy as np
from .embed import normalise
from .errors import AppError, warning
from .media import MediaError
from .media.videos import probe, video_info, sample_times, frame
from .paths import absolute, filesystem_path
from .probe import bounded_call, bounded_probe

HASH_BLOCK = 65536
MAX_SOURCE_FRAMES = 12
SOURCE_SIMILARITY = .985
SOURCE_COVERAGE = .8
CANDIDATE_IO_BUDGET = 5.0
CANDIDATE_TIMEOUT = 1.0


def signature(stat):
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def content_sample(path, expected):
    """Hash at most 192 KiB, including size and offsets; never claim full equality."""
    digest = hashlib.sha256()
    size = expected.st_size
    digest.update(str(size).encode("ascii"))
    with path.open("rb") as stream:
        if signature(os.fstat(stream.fileno())) != signature(expected):
            raise OSError("File changed during identity check")
        offsets = [0] if size <= 3 * HASH_BLOCK else [0, (size - HASH_BLOCK) // 2, size - HASH_BLOCK]
        for offset in offsets:
            stream.seek(offset)
            wanted = min(size, 3 * HASH_BLOCK) if len(offsets) == 1 else HASH_BLOCK
            block = stream.read(wanted)
            if len(block) != wanted:
                raise OSError("Incomplete identity read")
            digest.update(str(offset).encode("ascii") + b":" + block)
        if signature(os.fstat(stream.fileno())) != signature(expected):
            raise OSError("File changed during identity check")
    return digest.hexdigest()


def near_source(candidate, source):
    similarities = normalise(candidate) @ normalise(source).T
    return bool(np.mean(similarities.max(axis=1) >= SOURCE_SIMILARITY) >= SOURCE_COVERAGE
                and np.mean(similarities.max(axis=0) >= SOURCE_SIMILARITY) >= SOURCE_COVERAGE)


class SourceFilter:
    def __init__(self, path, libraries, warnings, excluded, search=None, keep_near_duplicates=False):
        self.deadline = time.monotonic() + CANDIDATE_IO_BUDGET
        self.path = absolute(path)
        self.file_path = filesystem_path(path)
        self.roots = {lib["name"]: filesystem_path(lib["root"]) for lib in libraries}
        self.warnings, self.excluded, self.search = warnings, excluded, search
        ok, source = bounded_probe(self.file_path.stat, timeout=1)
        if not ok or not file_mode.S_ISREG(source.st_mode):
            raise AppError("aroll_not_found", "The A-roll identity cannot be checked.",
                "Check the file and mount, then retry.", 7)
        self.source = source
        ok, self.digest = bounded_probe(lambda: content_sample(self.file_path, source), timeout=1)
        if not ok:
            raise AppError("aroll_not_found", "The A-roll content cannot be checked.",
                "Check the file and mount, then retry.", 7)
        self.checked = {}
        self.io_remaining = CANDIDATE_IO_BUDGET
        self.stalled_libraries = set()
        self.vectors = None
        if search is not None and not keep_near_duplicates:
            ok, info = bounded_probe(lambda: probe(self.file_path), timeout=max(.001,
                self.deadline - time.monotonic()))
            if not ok:
                raise AppError("aroll_not_found", "The A-roll video identity cannot be checked.",
                    exit_code=7)
            if any(s.get("codec_type") == "video" for s in info.get("streams", [])):
                metadata = video_info(info)
                stamps, _ = sample_times(metadata["duration"], 5, MAX_SOURCE_FRAMES)
                try:
                    images = [frame(self.file_path, stamp, timeout=max(.001,
                        self.deadline - time.monotonic()), reader="ffmpeg") for stamp in stamps]
                except MediaError:
                    raise AppError("aroll_not_found", "The A-roll frames cannot be checked.",
                        "Check the file and retry.", 7) from None
                self.vectors = normalise(search.get_model().images(images))

    @property
    def identity(self):
        return dict(path=str(self.path), stat=list(signature(self.source)), digest=self.digest)

    def warn(self, code, message):
        if not any(w["code"] == code for w in self.warnings):
            self.warnings.append(warning(code, message))

    def candidate_probe(self, library, call):
        if library in self.stalled_libraries or self.io_remaining <= 0 or time.monotonic() >= self.deadline:
            self.warn("library_unreachable",
                "Candidates were omitted after the source-check I/O budget or a library deadline was reached.")
            return False, None
        started = time.monotonic()
        try:
            return True, bounded_call(call, min(CANDIDATE_TIMEOUT, self.io_remaining, max(.001,
                self.deadline - time.monotonic())))
        except TimeoutError:
            # One stalled path is enough to stop waiting on this library.
            self.stalled_libraries.add(library)
            return False, None
        except Exception:
            return False, None
        finally:
            self.io_remaining -= time.monotonic() - started

    def __call__(self, metadata):
        key = metadata["file_key"]
        if key in self.checked:
            return self.checked[key]
        candidate = self.roots[metadata["library"]] / metadata["relpath"]
        ok, stat = self.candidate_probe(metadata["library"], candidate.stat)
        self.checked[key] = False
        if not ok or not file_mode.S_ISREG(stat.st_mode):
            self.warn("library_unreachable",
                "Candidates whose file identity could not be checked were omitted.")
            return False
        same = bool(stat.st_ino and self.source.st_ino) and (
            stat.st_dev, stat.st_ino) == (self.source.st_dev, self.source.st_ino)
        if not same and stat.st_size == self.source.st_size:
            ok, digest = self.candidate_probe(metadata["library"], lambda: content_sample(candidate,
                stat))
            if not ok:
                self.warn("library_unreachable",
                    "Candidates whose content could not be checked were omitted.")
                return False
            same = digest == self.digest
        if same:
            self.excluded.append(key)
            self.warn("aroll_excluded",
                "The A-roll, physical aliases, and matching size/content samples are excluded from candidates.")
            return False
        if "size" in metadata and (stat.st_size, stat.st_mtime_ns) != (metadata["size"],
            metadata["mtime_ns"]):
            self.warn("index_stale",
                "Changed candidate files were omitted; index again before retrying.")
            return False
        if self.vectors is not None and metadata["kind"] == "video":
            rows = [r[0] for r in self.search.store.db.execute("SELECT row FROM frames WHERE file_id=? ORDER BY t_ms,row",
                (metadata["id"],))]
            if len(rows) > MAX_SOURCE_FRAMES:
                rows = [rows[i] for i in np.linspace(0, len(rows) - 1, MAX_SOURCE_FRAMES, dtype=int)]
            if rows and near_source(self.search.matrix[rows].astype(np.float32), self.vectors):
                self.excluded.append(key)
                self.warn("aroll_near_duplicate",
                    "A video was excluded as a near-duplicate of the A-roll (frame cosine >= 0.985, at least 80% coverage in both directions).")
                return False
        self.checked[key] = True
        return True


def source_filter(path, libraries, warnings, excluded, search=None, keep_near_duplicates=False):
    return SourceFilter(path, libraries, warnings, excluded, search, keep_near_duplicates)
