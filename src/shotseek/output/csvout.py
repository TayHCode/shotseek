import csv
import io
from pathlib import PurePosixPath
import unicodedata

SEARCH_COLUMNS = "query_id query rank score relevance media_type path open_path filename folder timestamp start end timecode duration width height orientation captured_at thumbnail item_id library review_status notes".split()
BROLL_COLUMNS = "beat_id beat_start beat_end beat_timecode beat_text matched_query rank recommended score relevance media_type path open_path filename clip_start clip_end clip_timecode duration width height thumbnail item_id review_status notes".split()


def safe_cell(key, value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, str) and key not in {"path", "open_path", "thumbnail"}:
        first = next((c for c in value if not c.isspace() and unicodedata.category(c) not in {"Cc",
            "Cf"}), "")
        if first in {"=", "+", "-", "@"}:
            return "'" + value
    return value


def rows(document):
    if document["command"] == "search":
        for query in document["queries"]:
            for result in query["results"]:
                yield dict(result, query_id=query["id"], query=query["text"],
                    folder=str(PurePosixPath(result["relative_path"]).parent), review_status="",
                    notes="")
    else:
        for beat in document["beats"]:
            for result in beat.get("candidates", []):
                yield dict(result, beat_id=beat["id"], beat_start=beat["start"],
                    beat_end=beat["end"], beat_timecode=beat["timecode"], beat_text=beat["text"],
                    clip_start=result["start"], clip_end=result["end"],
                    clip_timecode=result["timecode"], review_status="", notes="")


def format_document(document):
    fields = SEARCH_COLUMNS if document["command"] == "search" else BROLL_COLUMNS
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows(document):
        writer.writerow({key: safe_cell(key, row.get(key)) for key in fields})
    return stream.getvalue()
