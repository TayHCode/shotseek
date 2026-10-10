"""Transcript readers for plain text, timed cues, and JSON documents."""
from pathlib import Path
import re
import sys
from ..errors import AppError
from ..inputs import json_document, text as valid_text, times

TIME = r"(?:\d{1,3}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?"


def seconds(value):
    parts = value.replace(",", ".").split(":")
    result = 0.
    for part in parts:
        result = result * 60 + float(part)
    return result


def clean(text):
    return re.sub(r"<[^>]*>", "", text).strip()


def segments(data, preserve_ids=False):
    declared_timed = None
    if isinstance(data, dict):
        if "segments" not in data:
            data = data.get("transcript")
        if not isinstance(data, dict):
            raise ValueError("transcript must be an object containing segments")
        if "timed" in data:
            declared_timed = data["timed"]
            if not isinstance(declared_timed, bool):
                raise ValueError("transcript.timed must be a boolean")
        data = data.get("segments")
    if not isinstance(data, list):
        raise ValueError("segments must be an array")
    result = []
    ids = set()
    for number, row in enumerate(data, 1):
        field = f"segments[{number - 1}]"
        if not isinstance(row, dict):
            raise ValueError(field + " must be an object")
        text = clean(valid_text(row.get("text"), field + ".text", nonempty=False))
        ident = row.get("id", number)
        if type(ident) is not int or ident < 1 or ident in ids:
            raise ValueError(field + ".id must be a unique positive integer")
        ids.add(ident)
        start, end = row.get("start"), row.get("end")
        times(start, end, field)
        if declared_timed is not None and declared_timed != (start is not None):
            raise ValueError("transcript.timed must agree with segment times")
        if start is not None or end is not None:
            start, end = round(start, 3), round(end, 3)
        if text:
            result.append(dict(id=ident if preserve_ids else len(result) + 1, start=start, end=end,
                text=text))
    if result and any(r["start"] is None for r in result) and any(r["start"] is not None for r in result):
        raise ValueError("Segment times must be consistently timed or untimed")
    if result and result[0]["start"] is not None:
        result.sort(key=lambda r: r["start"])
        if not preserve_ids:
            for number, row in enumerate(result, 1):
                row["id"] = number
    return result


def parse(text, extension=""):
    text = text.lstrip("\ufeff").strip()
    structured = extension.lower() == ".json" or text.startswith(("{",
        "[")) and not re.match(r"\[" + TIME, text)
    if not text:
        if structured:
            raise AppError("usage", "The JSON transcript is empty.",
                "Supply an array of segments or an object containing segments.")
        raise AppError("transcript_empty", "The transcript is empty.", exit_code=7)
    try:
        if structured:
            result = segments(json_document(text))
        elif extension.lower() in {".srt", ".vtt"} or " --> " in text:
            result = []
            pattern = re.compile(r"(" + TIME + r")\s*-->\s*(" + TIME + r")[^\n]*\n(.*?)(?=\n\s*\n|\Z)",
                re.S)
            for match in pattern.finditer(text):
                result.append(dict(start=seconds(match[1]), end=seconds(match[2]),
                    text=clean(" ".join(match[3].splitlines()))))
            result = segments(result)
            if not result:
                raise ValueError
        else:
            lines = text.splitlines()
            timed = [re.match(r"^\[?(" + TIME + r")\]?\s+(.+)$",
                line.strip()) for line in lines if line.strip()]
            if timed and all(timed):
                result = [dict(id=i + 1, start=seconds(m[1]),
                    end=seconds(timed[i + 1][1]) if i + 1 < len(timed) else seconds(m[1]) + 5,
                    text=clean(m[2])) for i, m in enumerate(timed)]
                result = segments(result)
            else:
                result = []
                for paragraph in re.split(r"\n\s*\n", text):
                    for i, sentence in enumerate(re.split(r"(?<=[.!?])\s+|\n", paragraph)):
                        if sentence.strip():
                            result.append(dict(id=len(result) + 1, start=None, end=None,
                                text=sentence.strip(), _break_before=bool(result) and i == 0))
        if not result:
            raise AppError("transcript_empty", "The transcript has no text.", exit_code=7)
        return dict(timed=result[0]["start"] is not None, segments=result)
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        if structured:
            raise AppError("usage", "Invalid JSON transcript: " + str(exc),
                "Check segment text, IDs, and start/end times.") from None
        raise AppError("transcript_unparseable", "The transcript format is invalid.",
            exit_code=7) from None


def read(path):
    try:
        if str(path) == "-":
            return parse(sys.stdin.read())
        path = Path(path).expanduser().absolute()
        return parse(path.read_text(encoding="utf-8-sig"), path.suffix)
    except (OSError, UnicodeError):
        if str(path).lower().endswith(".json"):
            raise AppError("usage", "The JSON transcript file cannot be read as UTF-8.") from None
        raise AppError("transcript_unparseable", "The transcript file cannot be read.",
            exit_code=7) from None
