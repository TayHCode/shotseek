"""Stable command line and JSON error boundary; backends load on demand."""
import argparse
import contextlib
import io
import json
import sys
import traceback
from . import __version__
from .names import NAME
from .errors import AppError


class Parser(argparse.ArgumentParser):
    def error(self, message):
        hint = "Use shotseek library add NAME PATH; init --library uses NAME=PATH." if self.prog.endswith(
            "library add") else "Use --help for accepted arguments."
        raise AppError("usage", message, hint)


def globals_on(p):
    for flag in ("config", "index-dir"):
        p.add_argument("--" + flag, default=argparse.SUPPRESS)
    for flag in ("quiet", "verbose"):
        p.add_argument("--" + flag, action="store_true", default=argparse.SUPPRESS)


def backend_options(p):
    p.add_argument("--device")
    p.add_argument("--offline", action="store_true")


def filters_on(p, media="any"):
    p.add_argument("--media", choices=["photo", "video", "any"], default=media)
    for key in ("library", "under", "path-contains", "exclude-id"):
        p.add_argument("--" + key, action="append", default=[])
    p.add_argument("--orientation", choices=["landscape", "portrait", "square"])
    for key in ("min-width", "min-height"):
        p.add_argument("--" + key, type=int)
    for key in ("min-megapixels", "min-duration", "max-duration"):
        p.add_argument("--" + key, type=float)
    for key in ("after", "before"):
        p.add_argument("--" + key)
    p.add_argument("--include-blank", action="store_true")


def results_on(p, per_file):
    p.add_argument("--max-per-file", type=int, default=per_file)
    p.add_argument("--min-clip-seconds", type=float, default=2)
    p.add_argument("--max-clip-seconds", type=float, default=12)
    p.add_argument("--format", choices=["json", "csv", "text"], default="json")
    p.add_argument("--output")


def speech_options(p):
    p.add_argument("--segmenter", choices=["windows", "pauses"], default="windows")
    p.add_argument("--min-need", type=float, default=.45)
    p.add_argument("--max-beats", type=int, default=12)
    p.add_argument("--whisper-model")
    p.add_argument("--language")
    p.add_argument("--min-beat-seconds", type=float, default=5)
    p.add_argument("--max-beat-seconds", type=float, default=20)
    p.add_argument("--save-transcript")


def build_parser():
    root = Parser(prog=NAME)
    globals_on(root)
    root.add_argument("--version", action="version", version=f"{NAME} {__version__}")
    sub = root.add_subparsers(dest="command", required=True, parser_class=Parser)
    commands = {}
    for name in ("init", "library", "index", "status", "search", "broll", "transcribe", "show",
        "doctor", "compact", "schema", "agent-prompt"):
        p = sub.add_parser(name)
        globals_on(p)
        commands[name] = p
    p = commands["init"]
    p.add_argument("--library", action="append", required=True)
    p.add_argument("--display-root", action="append", default=[])
    p.add_argument("--force", action="store_true")
    actions = commands["library"].add_subparsers(dest="action", required=True, parser_class=Parser)
    for name in ("add", "list", "remove"):
        p = actions.add_parser(name)
        globals_on(p)
        if name != "list":
            p.add_argument("name")
        if name == "add":
            p.add_argument("path")
            p.add_argument("--display-root", default="")
            p.add_argument("--exclude", action="append", default=[])
        if name == "remove":
            p.add_argument("--purge", action="store_true")
    p = commands["index"]
    backend_options(p)
    p.add_argument("--library", action="append", default=[])
    for key in ("workers", "batch-size", "max-files", "max-files-per-library"):
        p.add_argument("--" + key, type=int)
    p.add_argument("--time-budget", type=float)
    for key in ("retry-failed", "prune-missing", "no-prune", "rebuild", "yes", "strict"):
        p.add_argument("--" + key, action="store_true")
    p.add_argument("--progress", choices=["text", "json", "none"], default="text")
    p = commands["search"]
    backend_options(p)
    filters_on(p)
    results_on(p, 3)
    p.add_argument("queries", nargs="*")
    p.add_argument("--query", action="append", default=[])
    p.add_argument("--queries-file")
    p.add_argument("--like")
    p.add_argument("--top-k", type=int, default=20)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--dedupe-threshold", type=float, default=.95)
    for key in ("min-score", "min-relevance"):
        p.add_argument("--" + key, type=float)
    p.add_argument("--raw-frames", action="store_true")
    p.add_argument("--no-dedupe", action="store_true")
    p.add_argument("--no-cache", action="store_true")
    p = commands["broll"]
    backend_options(p)
    filters_on(p, "video")
    results_on(p, 1)
    speech_options(p)
    modes = p.add_mutually_exclusive_group(required=True)
    for key in ("aroll", "transcript", "points-file", "beats"):
        modes.add_argument("--" + key)
    modes.add_argument("--point", action="append")
    p.add_argument("--aroll-duration", type=float)
    p.add_argument("--per-beat", type=int, default=5)
    p.add_argument("--keep-near-duplicates", action="store_true")
    p.add_argument("--include-filler", action="store_true")
    p.add_argument("--no-transcript-cache", action="store_true")
    p = commands["transcribe"]
    p.add_argument("file")
    backend_options(p)
    speech_options(p)
    commands["show"].add_argument("id")
    commands["doctor"].add_argument("--offline", action="store_true")
    commands["doctor"].add_argument("--device")
    commands["doctor"].add_argument("--report", action="store_true")
    commands["schema"].add_argument("name", nargs="?")
    commands["agent-prompt"].add_argument("--target", choices=["claude-skill", "codex", "generic"],
        default="generic")
    return root


def envelope(command, ok=True, warnings=None):
    return dict(schema_version=1, tool=NAME, tool_version=__version__, command=command, ok=ok,
        warnings=warnings or [])


def dispatch(args):
    if args.command in {"init", "library"}:
        from .config import command
        return command(args)
    if args.command in {"index", "compact"}:
        from .indexer import command
        return command(args)
    if args.command == "status":
        from .status import command
        return command(args)
    if args.command == "search":
        from .search import command
        return command(args)
    if args.command == "show":
        from .search import show
        return show(args)
    if args.command == "broll":
        from .broll import command
        return command(args)
    if args.command == "transcribe":
        from .transcribe import command
        return command(args)
    if args.command == "doctor":
        from .doctor import command
        return command(args)
    if args.command == "agent-prompt":
        from .agent import command
        return command(args)
    if args.command == "schema":
        from importlib.resources import files
        folder = files("shotseek").joinpath("schemas")
        names = sorted(p.name[:-5] for p in folder.iterdir() if p.name.endswith(".json"))
        if args.name is None:
            return {"schemas": names}
        if args.name not in names:
            raise AppError("usage", "Unknown schema name.")
        return {"_raw": folder.joinpath(args.name + ".json").read_text().rstrip("\n")}
    raise AppError("usage", "Unknown command.")


def main(argv=None):
    # Machine-readable output uses UTF-8 even through a legacy Windows pipe.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    argv = sys.argv[1:] if argv is None else argv
    args = None
    command = next((v for v in argv if v in {"init", "library", "index", "status", "search",
        "broll", "transcribe", "show", "doctor", "compact", "schema", "agent-prompt"}), "")
    try:
        if sys.version_info < (3, 11):
            raise AppError("python_unsupported", "shotseek requires Python 3.11 or newer.",
                "Use uv venv --python 3.12, then uv pip install .; uv can download Python.", 6)
        args = build_parser().parse_args(argv)
        with contextlib.redirect_stderr(io.StringIO()) if getattr(args, "quiet",
            False) else contextlib.nullcontext():
            with contextlib.redirect_stdout(sys.stderr):
                payload = dispatch(args)
        code = payload.pop("_exit", 0)
        if code and "error" in payload and not getattr(args, "quiet", False):
            print(payload["error"]["message"], file=sys.stderr)
        raw = payload.pop("_raw", None)
        doc = envelope(args.command)
        doc.update(payload)
        print(raw if raw is not None else json.dumps(doc, ensure_ascii=False, allow_nan=False))
        return code
    except AppError as exc:
        doc = envelope(command, False)
        doc["error"] = exc.as_dict()
        print(json.dumps(doc, ensure_ascii=False))
        if not (getattr(args, "quiet", False) or "--quiet" in argv):
            print(exc.message, file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        doc = envelope(command, False)
        doc["error"] = AppError("interrupted", "Interrupted.", exit_code=130).as_dict()
        print(json.dumps(doc))
        return 130
    except Exception:
        doc = envelope(command, False)
        doc["error"] = AppError("internal", "An internal error occurred.",
            "Use --verbose for details.", 1).as_dict()
        print(json.dumps(doc))
        if "--verbose" in argv:
            traceback.print_exc(file=sys.stderr)
        elif "--quiet" not in argv:
            print(doc["error"]["message"], file=sys.stderr)
        return 1
