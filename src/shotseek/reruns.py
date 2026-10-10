"""Local, content-addressed B-roll revisions and deterministic edit reconciliation."""
from copy import deepcopy
import hashlib
import json
import re
from pathlib import Path
from .inputs import text, times
from .paths import atomic_write, writable

BEAT_FIELDS = ("id", "text", "start", "end", "segment_ids", "queries", "skipped", "skip_reason")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def beat_input(beat):
    return {field_name: beat[field_name] for field_name in BEAT_FIELDS}


def source_info(value):
    if not isinstance(value, dict) or value.get("kind") not in {"aroll", "transcript", "points",
        "beats"}:
        raise ValueError("source must describe an A-roll, transcript, points, or beats input")
    keys = {"kind", "path", "duration", "language", "whisper_model", "transcript_cached"}
    extra = {"size", "content_sample", "excluded_file_ids"}
    if not keys <= value.keys() or set(value) - keys - extra:
        raise ValueError("source has missing or unknown fields")
    for key in ("path", "language", "whisper_model"):
        if value[key] is not None:
            text(value[key], "source." + key)
    if value["kind"] == "aroll" and value["path"] is None:
        raise ValueError("source.path is required for an A-roll")
    if value["path"] is not None and not Path(value["path"]).is_absolute():
        raise ValueError("source.path must be absolute")
    if value["duration"] is not None:
        times(0, value["duration"], "source.duration")
    if type(value["transcript_cached"]) is not bool:
        raise ValueError("source.transcript_cached must be boolean")
    if "excluded_file_ids" in value:
        if not isinstance(value["excluded_file_ids"], list):
            raise ValueError("source.excluded_file_ids must be an array")
        for ident in value["excluded_file_ids"]:
            text(ident, "source.excluded_file_ids")
    if "size" in value and (type(value["size"]) is not int or value["size"] < 0):
        raise ValueError("source.size must be a nonnegative integer")
    if "content_sample" in value:
        text(value["content_sample"], "source.content_sample")
    return deepcopy(value)


class Revisions:
    def __init__(self, index, libraries):
        self.folder = writable(index / "broll", libraries)
        self.libraries = libraries

    def get(self, revision):
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{64}", revision):
            raise ValueError("revision must be a local B-roll revision identifier")
        try:
            value = json.loads((self.folder / (revision + ".json")).read_text())
            return value if digest(value) == revision else None
        except (OSError, ValueError):
            return None

    def put(self, value):
        key = digest(value)
        atomic_write(self.folder / (key + ".json"), json.dumps(value, ensure_ascii=False,
            allow_nan=False), self.libraries)
        return key


def reconcile(doc, previous):
    """Beat-array order wins; transcript-only changes flow into unedited linked beats."""
    doc = deepcopy(doc)
    if previous is None:
        return doc
    if doc.get("source") != previous["source"]:
        raise ValueError("source differs from its saved revision; start a new run from the source")
    old_beats = {b["id"]: b for b in previous["beats"]}
    old_segments = {s["id"]: s for s in previous["transcript"]["segments"]}
    current = {s["id"]: s for s in doc.get("transcript", {}).get("segments", []) if isinstance(s,
        dict) and type(s.get("id")) is int}
    transcript_changed = doc.get("transcript") != previous["transcript"]
    rows = []
    used = {row.get("id") for row in doc["beats"] if isinstance(row, dict)}
    for row in doc["beats"]:
        if not isinstance(row, dict):
            rows.append(row)
            continue
        old = old_beats.get(row.get("id"))
        if old is not None:
            linked = row.get("segment_ids", [])
            # Explicit beat text/timing wins over the linked transcript.
            own_edit = any(row.get(k) != old.get(k) for k in ("text", "start", "end", "segment_ids"))
            if transcript_changed and linked and not own_edit:
                remaining = [current[i] for i in linked if i in current]
                if not remaining:
                    continue
                row.update(text=" ".join(s["text"] for s in remaining),
                    start=remaining[0].get("start"), end=remaining[-1].get("end"),
                    segment_ids=[s["id"] for s in remaining])
            # A saved automatic query is derived data. Rebuild it after text edits.
            if "visual_queries" not in row and row.get("queries") == old["queries"] and all(q["source"] != "agent" for q in old["queries"]):
                row.pop("queries", None)
                row["_point"] = old["queries"][0]["source"] == "point"
            elif "visual_queries" not in row and isinstance(row.get("queries"), list):
                for number, query in enumerate(row["queries"]):
                    if (isinstance(query, dict) and query.get("source") in {"sentence", "keywords",
                        "point", "topic"}
                            and (number >= len(old["queries"]) or query != old["queries"][number])):
                        query["source"] = "agent"
            # An unchanged explicit query remains explicit.
        if "id" not in row:
            key = "b-" + digest({k: row.get(k) for k in ("text", "start", "end", "segment_ids")})[:12]
            base, count = key, 1
            while key in used:
                count += 1
                key = base + "-" + str(count)
            row["id"] = key
            used.add(key)
        rows.append(row)
    if transcript_changed:
        linked = {i for row in rows if isinstance(row, dict) for i in row.get("segment_ids", [])}
        for ident, segment in current.items():
            if ident in old_segments or ident in linked:
                continue
            key = "b-" + digest(segment)[:12]
            while key in used:
                key += "-new"
            used.add(key)
            rows.append(dict(id=key, text=segment["text"], start=segment.get("start"),
                end=segment.get("end"), segment_ids=[ident]))
    doc["beats"] = rows
    return doc


def context(search, args, identity):
    from .search import filters
    options = filters(args)
    for key in ("per_beat", "max_per_file", "min_clip_seconds", "max_clip_seconds",
        "include_filler", "dedupe_threshold", "no_dedupe", "min_score", "min_relevance", "min_need",
        "max_beats", "segmenter", "keep_near_duplicates"):
        options[key] = getattr(args, key, None)
    # The snapshot includes removals, rebuilds, metadata changes, and compaction.
    files = search.store.rows("SELECT * FROM files ORDER BY id")
    return digest(dict(version=4, index=str(search.index), info=search.info, files=files,
                       libraries=search.data["library"], options=options, source=identity))


def checks_unchanged(previous, search, accept):
    if accept is None:
        return True
    for key, expected in previous.get("checks", {}).items():
        row = search.store.db.execute("SELECT id FROM files WHERE file_key IN (?)", (key,)).fetchone()
        if row is None or accept(search.file(row[0])) != expected:
            return False
    return not any(w["code"] in {"library_unreachable", "index_stale"} for w in accept.warnings)
