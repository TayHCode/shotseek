"""Path rules and the shared write boundary."""
import json
import os
from pathlib import Path
import tempfile
import unicodedata
from .names import NAME, CONFIG_FILE, env
from .errors import AppError


def absolute(path):
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def windows_extended(path):
    """Use Win32 extended paths for filesystem calls without changing OS policy."""
    text = str(path)
    if text.startswith("\\\\?\\"):
        return text
    return "\\\\?\\UNC\\" + text[2:] if text.startswith("\\\\") else "\\\\?\\" + text


def filesystem_path(path):
    path = absolute(path)
    return Path(windows_extended(path)) if os.name == "nt" else path


def config_path(flag=None):
    base = os.environ.get("APPDATA") if os.name == "nt" else os.environ.get("XDG_CONFIG_HOME")
    return absolute(flag or os.environ.get(env("CONFIG")) or (Path(base or Path.home() / ".config") / NAME / CONFIG_FILE))


def index_path(flag=None, configured=""):
    base = os.environ.get("LOCALAPPDATA") if os.name == "nt" else os.environ.get("XDG_DATA_HOME")
    return absolute(flag or os.environ.get(env("INDEX_DIR")) or configured or (Path(base or Path.home() / ".local/share") / NAME / "index"))


def same_directory_spelling(left, right):
    """Prove alternate spellings with listings when a provider invents inodes."""
    def folded(value):
        return unicodedata.normalize("NFC", value).casefold()
    if left == right:
        return True
    if folded(str(left)) != folded(str(right)) or not same_directory_spelling(left.parent, right.parent):
        return False
    if left.name == right.name:
        return True
    try:
        matches = []
        with os.scandir(left.parent) as entries:
            for count, entry in enumerate(entries):
                if count >= 10000:
                    raise AppError("library_unreachable",
                        "The directory inspection limit prevented verification of a case-alias path.",
                        "Use the library's original path spelling and retry.", 4)
                if folded(entry.name) == folded(left.name):
                    matches.append(entry.name)
        return len(matches) == 1
    except OSError:
        raise AppError("library_unreachable",
            "The directory listing needed to verify a case-alias path is unavailable.",
            "Reconnect storage or check permissions and retry.", 4) from None


def contained(path, root):
    if absolute(path).is_relative_to(absolute(root)):
        return True
    path, root = filesystem_path(path).resolve(), filesystem_path(root).resolve()
    if path.is_relative_to(root):
        return True
    # POSIX clients can expose a case-insensitive share while resolve() keeps
    # the caller's spelling. Compare existing directory identities as well,
    # including ancestors of a destination that has not been created yet.
    try:
        identity = root.stat()
    except OSError:
        return False
    for candidate in (path, *path.parents):
        try:
            stat = candidate.stat()
        except OSError:
            continue
        if identity.st_ino and stat.st_ino and (stat.st_dev, stat.st_ino) == (identity.st_dev, identity.st_ino):
            return True
        if same_directory_spelling(candidate, root):
            return True
    return False


def writable(path, libraries=(), code="output_inside_library"):
    path = absolute(path)
    for library in libraries:
        root = library["root"] if isinstance(library, dict) else library
        if contained(path, root) or code == "index_inside_library" and contained(root, path):
            raise AppError(code, "The write destination is inside a media library.",
                "Choose a path outside every library.")
    return path


def atomic_write(path, data, libraries=()):
    path = writable(path, libraries)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data.encode("utf-8") if isinstance(data, str) else data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return path


def ensure_index(path, libraries=(), create=True):
    path = writable(path, libraries, "index_inside_library")
    marker = path / "index.json"
    if path.exists():
        if not path.is_dir():
            raise AppError("index_dir_not_empty", "The index destination is not a folder.")
        if marker.exists():
            try:
                data = json.loads(marker.read_text())
            except (OSError, ValueError):
                raise AppError("index_dir_not_empty", "The folder has no valid index marker.") from None
            if data.get("tool") != NAME:
                raise AppError("index_dir_not_empty", "The folder belongs to another application.")
            if data.get("format_version") != 1:
                raise AppError("index_format_unsupported", "Unsupported index format.", exit_code=3)
            return path
        if any(path.iterdir()):
            raise AppError("index_dir_not_empty", "The index folder contains unrelated files.")
    if create:
        path.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timezone
        data = dict(tool=NAME, format_version=1, model=None, pretrained=None, model_id=None,
            dim=None, dtype="float16", created_at=datetime.now(timezone.utc).isoformat())
        atomic_write(marker, json.dumps(data), libraries)
    return path


def display_path(library, relpath):
    path = str(absolute(library["root"]) / Path(relpath))
    display = library.get("display_root", "")
    if not display:
        return path, path
    separator = "\\" if "\\" in display and "/" not in display else "/"
    return path, display.rstrip("/\\") + separator + relpath.replace("/", separator)
