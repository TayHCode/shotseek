"""Strict versioned configuration, without optional dependencies."""
import copy
import json
import os
import re
import tomllib
from .errors import AppError
from .probe import bounded_probe
from .names import NAME, env
from .paths import filesystem_path, absolute, config_path, index_path, writable, atomic_write, contained

DEFAULTS = {
    "config_version": 1,
    "index": {"dir": "", "thumbnails": True, "thumbnail_max_edge": 320},
    "model": {"name": "ViT-B-32", "pretrained": "laion2b_s34b_b79k", "device": "cpu", "batch_size": 0},
    "indexing": {"workers": 0, "video_frame_interval_seconds": 5.0, "video_max_frames": 60,
                 "file_timeout_seconds": 120, "frame_timeout_seconds": 60, "video_timeout_seconds": 900,
                 "change_detection": "size+mtime", "mtime_tolerance_seconds": 2,
                     "follow_symlinks": False,
                 "max_image_megapixels": 250, "exclude": [], "frame_reader": "auto",
                     "video_sampling": "interval",
                 "video_samples_per_file": 4},
    "transcribe": {"model": "base", "language": "", "device": ""},
    "library": [],
}
LIBRARY_DEFAULTS = {"name": "", "root": "", "display_root": "", "exclude": []}


def invalid(key):
    raise AppError("config_invalid", "Invalid configuration key or value: " + key)


def device_valid(value):
    return isinstance(value, str) and re.fullmatch(r"cpu|cuda(?::[0-9]+)?|mps|auto", value) is not None


def validate(data):
    if not isinstance(data, dict):
        invalid("root")
    for key in data:
        if key not in DEFAULTS:
            invalid(key)
    result = copy.deepcopy(DEFAULTS)
    for key, value in data.items():
        if isinstance(DEFAULTS[key], dict):
            if not isinstance(value, dict):
                invalid(key)
            for child, item in value.items():
                if child not in DEFAULTS[key]:
                    invalid(key + "." + child)
                expected = DEFAULTS[key][child]
                if isinstance(expected, bool):
                    valid = isinstance(item, bool)
                elif isinstance(expected, (int, float)):
                    valid = isinstance(item, (int, float)) and not isinstance(item, bool)
                    if isinstance(expected, int):
                        valid = valid and isinstance(item, int)
                    valid = valid and item >= (0 if child in {"workers", "batch_size",
                        "mtime_tolerance_seconds"} else 1e-9)
                elif isinstance(expected, list):
                    valid = isinstance(item, list) and all(isinstance(x, str) for x in item)
                else:
                    valid = isinstance(item, str)
                if not valid:
                    invalid(key + "." + child)
                result[key][child] = item
        else:
            result[key] = value
    if type(result["config_version"]) is not int or result["config_version"] != 1:
        invalid("config_version")
    if not device_valid(result["model"]["device"]):
        invalid("model.device")
    if result["transcribe"]["device"] and not device_valid(result["transcribe"]["device"]):
        invalid("transcribe.device")
    if result["indexing"]["change_detection"] not in {"size", "size+mtime"}:
        invalid("indexing.change_detection")
    for key, choices in [("frame_reader", {"auto", "opencv", "ffmpeg"}),
                         ("video_sampling", {"interval", "fixed"})]:
        if result["indexing"][key] not in choices:
            invalid("indexing." + key)
    if not isinstance(result["library"], list):
        invalid("library")
    libraries = []
    for record in result["library"]:
        if not isinstance(record, dict) or set(record) - LIBRARY_DEFAULTS.keys():
            invalid("library")
        library = dict(LIBRARY_DEFAULTS, **record)
        if not isinstance(library["name"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}",
            library["name"]):
            raise AppError("library_name_invalid",
                "Library names use 1 to 32 lower-case letters, digits, underscores, or hyphens.")
        if not isinstance(library["root"],
            str) or not library["root"] or not isinstance(library["display_root"], str):
            invalid("library.root")
        if not isinstance(library["exclude"], list) or not all(isinstance(x,
            str) for x in library["exclude"]):
            invalid("library.exclude")
        library["root"] = str(absolute(library["root"]))
        for previous in libraries:
            if library["name"] == previous["name"]:
                raise AppError("library_name_invalid", "Library names must be unique.")
            if contained(library["root"], previous["root"]) or contained(previous["root"],
                library["root"]):
                raise AppError("library_overlap", "Library roots must not overlap.")
        libraries.append(library)
    result["library"] = libraries
    return result


def dumps(data):
    def literal(value):
        if isinstance(value, bool):
            return "true" if value else "false"
        return json.dumps(value, ensure_ascii=False, allow_nan=False)
    lines = ["# Local media search configuration", "config_version = 1", ""]
    for key in ("index", "model", "indexing", "transcribe"):
        lines.append("[" + key + "]")
        lines.extend(k + " = " + literal(v) for k, v in data[key].items())
        lines.append("")
    for library in data["library"]:
        lines.append("[[library]]")
        lines.extend(k + " = " + literal(v) for k, v in library.items())
        lines.append("")
    text = "\n".join(lines)
    tomllib.loads(text)
    return text


def write(path, data):
    data = validate(data)
    atomic_write(path, dumps(data), data["library"])


def load(args=None, optional=False):
    path = config_path(getattr(args, "config", None))
    try:
        with path.open("rb") as stream:
            data = validate(tomllib.load(stream))
    except FileNotFoundError:
        if not optional:
            raise AppError("config_missing", "No configuration found.",
                "Run " + NAME + " init --library media=/path/to/media.") from None
        data = validate({})
    except (tomllib.TOMLDecodeError, OSError):
        raise AppError("config_invalid", "The configuration cannot be read or parsed.") from None
    index = index_path(getattr(args, "index_dir", None), data["index"]["dir"])
    writable(index, data["library"], "index_inside_library")
    return data, path, index


def device(data, flag=None, search=False, speech=False):
    configured = data["transcribe"]["device"] if speech else ""
    value = flag or os.environ.get(env("DEVICE")) or configured or ("cpu" if search else data["model"]["device"])
    if not device_valid(value):
        raise AppError("usage", "Invalid device; choose cpu, cuda, cuda:N, mps, or auto.")
    return value


def root_reachable(root):
    ok, value = bounded_probe(lambda: filesystem_path(root).is_dir(), .25)
    return bool(ok and value)


def root_readable(root, timeout=.25):
    def check():
        with os.scandir(filesystem_path(root)):
            return True
    ok, value = bounded_probe(check, timeout)
    return bool(ok and value)


def listed(data):
    return [dict(record, reachable=root_reachable(record["root"])) for record in data["library"]]


def require_root(root):
    if not root_reachable(root):
        raise AppError("library_unreachable", "The library root is not a reachable folder.", exit_code=4)


def command(args):
    if args.command == "init":
        data = validate({})
        path = config_path(getattr(args, "config", None))
        if path.exists() and not args.force:
            raise AppError("config_exists", "The configuration already exists.",
                "Use shotseek library add NAME PATH to add a folder. "
                "init --force replaces the whole config, including existing libraries and settings.")
        for entry in args.library:
            if "=" not in entry:
                raise AppError("usage", "Use --library NAME=PATH.")
            name, root = entry.split("=", 1)
            require_root(root)
            data["library"].append(dict(LIBRARY_DEFAULTS, name=name, root=root))
        for entry in args.display_root:
            if "=" not in entry:
                raise AppError("usage", "Use --display-root NAME=PATH.")
            name, root = entry.split("=", 1)
            matches = [x for x in data["library"] if x["name"] == name]
            if not matches:
                raise AppError("library_unknown", "Unknown library: " + name)
            matches[0]["display_root"] = root
        data = validate(data)
        index = index_path(getattr(args, "index_dir", None))
        writable(index, data["library"], "index_inside_library")
        data["index"]["dir"] = str(index)
        write(path, data)
        return dict(config_path=str(path), index_dir=str(index), libraries=listed(data),
            next_steps=[NAME + " doctor", NAME + " index"])
    data, path, index = load(args)
    if args.action == "add":
        require_root(args.path)
        data["library"].append(dict(name=args.name, root=args.path, display_root=args.display_root,
            exclude=args.exclude))
        data = validate(data)
        writable(index, data["library"], "index_inside_library")
        write(path, data)
    elif args.action == "remove":
        if args.name not in {x["name"] for x in data["library"]}:
            raise AppError("library_unknown", "Unknown library: " + args.name)
        if args.purge:
            from .store.db import purge_library
            purge_library(index, args.name, data["library"])
        data["library"] = [x for x in data["library"] if x["name"] != args.name]
        write(path, data)
    return {"libraries": listed(data)}
