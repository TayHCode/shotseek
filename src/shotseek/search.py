"""Exact chunked search, metadata filters, and sampled video moments."""
import csv
from datetime import date, datetime, timezone
import json
import re
from pathlib import Path
import sys
import numpy as np
from . import config
from .embed import get_embedder, normalise
from .errors import AppError, warning
from .inputs import seconds
from .output import finish
from .output.textout import timecode
from .paths import absolute, display_path, writable
from .store.db import Store, item_id
from .store.lock import active
from .store.querycache import QueryCache
from .store.thumbs import path as thumb_path

FILTER_KEYS = "media library under path_contains orientation min_width min_height min_megapixels min_duration max_duration after before exclude_id include_blank".split()


def filters(args):
    return {field_name: getattr(args, field_name, [] if field_name in {"library", "under", "path_contains",
        "exclude_id"} else False if field_name == "include_blank" else "any" if field_name == "media" else None) for field_name in FILTER_KEYS}


def validate_options(args):
    for key, upper in (("top_k", 500), ("per_beat", 50)):
        value = getattr(args, key, None)
        if value is not None and not 1 <= value <= upper:
            raise AppError("usage", key.replace("_", "-") + " is outside the accepted range.")
    if getattr(args, "offset", 0) < 0 or args.max_per_file < 1:
        raise AppError("usage", "Offset must be nonnegative and max-per-file must be positive.")
    if not 0 < args.min_clip_seconds <= args.max_clip_seconds:
        raise AppError("usage", "Clip limits must be positive and ordered.")
    threshold = getattr(args, "dedupe_threshold", .95)
    if not 0 <= threshold <= 1:
        raise AppError("usage", "Dedupe threshold must be between zero and one.")
    for key in ("min_width", "min_height", "min_megapixels", "min_duration", "max_duration"):
        value = getattr(args, key, None)
        if value is not None and (not np.isfinite(value) or value < 0):
            raise AppError("usage", "Size and duration filters must be finite and nonnegative.")
    for key in ("min_score", "min_relevance", "min_clip_seconds", "max_clip_seconds"):
        value = getattr(args, key, None)
        if value is not None and not np.isfinite(value):
            raise AppError("usage", "Numeric search options must be finite.")
    for key in ("min_duration", "max_duration", "min_clip_seconds", "max_clip_seconds"):
        value = getattr(args, key, None)
        if value is not None:
            try:
                seconds(value, key.replace("_", "-"))
            except ValueError as exc:
                raise AppError("usage", str(exc)) from None
    for key in ("after", "before"):
        value = getattr(args, key, None)
        if value:
            try:
                date.fromisoformat(value)
            except ValueError:
                raise AppError("usage", "Dates must use YYYY-MM-DD.") from None


def escaped_like(value):
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class Search:
    def __init__(self, data, index, args):
        self.data, self.index, self.args = data, index, args
        self.device = config.device(data, args.device, search=True)
        self.store = Store(index)
        self.cache = None
        self.embedder = None
        self.warnings = []
        try:
            self.info, self.matrix = self.store.snapshot()
            self.model = json.loads((index / "index.json").read_text())
            self.model["name"] = self.model.get("model")
            if self.info["vector_rows"] == self.info["dead_rows"]:
                raise AppError("index_empty", "The index has no searchable items.",
                    "Run index first.", 3)
            self.libraries = {lib["name"]: lib for lib in data["library"]}
            if set(args.library) - self.libraries.keys():
                raise AppError("library_unknown", "A requested library is not configured.")
            for name in args.library or self.libraries:
                if not config.root_readable(self.libraries[name]["root"]):
                    notice = warning("library_unreachable", "Library folder is unavailable or unreadable: " +
                        name + "; saved results may point to files you cannot open. Reconnect and retry.")
                    self.warnings.append(notice)
                    if args.format != "json" and not getattr(args, "quiet", False):
                        print(notice["message"], file=sys.stderr)
            last = self.store.db.execute("SELECT status,walk_complete FROM runs ORDER BY id DESC LIMIT 1").fetchone()
            state = "indexing" if active(index / "index.lock") else "partial" if last and (last[0] != "complete" or not last[1]) else "complete"
            if state != "complete":
                self.warnings.append(warning("index_incomplete",
                    "Search covers the committed part of the library."))
            if self.info["model_id"] == "fake/color-v1":
                self.warnings.append(warning("fake_embedder",
                    "This index uses the deterministic test embedder."))
            if (data["model"]["name"], data["model"]["pretrained"]) != (self.model["name"],
                self.model["pretrained"]):
                self.warnings.append(warning("config_model_differs",
                    "Search uses the model recorded in the index."))
            self.index_summary = dict(dir=str(index), model=self.info["model_id"],
                files=self.store.db.execute("SELECT COUNT(*) FROM files WHERE status='indexed'").fetchone()[0],
                vectors=self.info["vector_rows"] - self.info["dead_rows"], state=state)
            self._select()
        except Exception:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self.cache:
            self.cache.close()
        self.store.close()

    def _select(self):
        options = filters(self.args)
        names = options["library"] or list(self.libraries)
        conditions = ["l.name IN (" + ",".join("?" for _ in names) + ")", "f.status='indexed'"]
        parameters = list(names)
        if options["media"] != "any":
            conditions.append("f.kind=?")
            parameters.append(options["media"])
        if options["orientation"]:
            conditions.append("f.orientation=?")
            parameters.append(options["orientation"])
        for key, expression in {"min_width": "f.width>=?", "min_height": "f.height>=?",
            "min_megapixels": "f.width*f.height/1000000.0>=?", "min_duration": "f.duration>=?",
            "max_duration": "f.duration<=?"}.items():
            if options[key] is not None:
                conditions.append(expression)
                parameters.append(options[key])
        for value in options["path_contains"]:
            conditions.append("instr(lower(f.relpath),lower(?))>0")
            parameters.append(value)
        prefixes = []
        for value in options["under"]:
            if Path(value).is_absolute():
                for name, library in self.libraries.items():
                    if absolute(value).is_relative_to(absolute(library["root"])):
                        prefixes.append((name,
                            absolute(value).relative_to(absolute(library["root"])).as_posix()))
            else:
                if ".." in Path(value).parts:
                    raise AppError("usage", "Folder filters must stay inside a library.")
                prefixes.extend((name, value.replace("\\", "/").strip("/")) for name in names)
        if options["under"]:
            clauses = []
            for name, value in prefixes:
                if value in {"", "."}:
                    clauses.append("l.name=?")
                    parameters.append(name)
                else:
                    clauses.append("(l.name=? AND (f.relpath=? OR f.relpath LIKE ? ESCAPE '\\'))")
                    parameters.extend((name, value, escaped_like(value.rstrip("/")) + "/%"))
            conditions.append("(" + " OR ".join(clauses) + ")" if clauses else "0")
        for key, operator in (("after", ">="), ("before", "<=")):
            if options[key]:
                conditions.append("COALESCE(substr(f.captured_at,1,10),date(f.mtime_ns/1000000000,'unixepoch'))" + operator + "?")
                parameters.append(options[key])
        for excluded in options["exclude_id"]:
            if "@" in excluded:
                conditions.append("NOT (f.file_key || '@' || COALESCE(r.t_ms,-1) = ?)")
            else:
                conditions.append("f.file_key != ?")
            parameters.append(excluded)
        if not options["include_blank"]:
            conditions.append("r.brightness>=0.04 AND r.brightness<=0.98")
        sql = "SELECT r.row,r.file_id,COALESCE(r.t_ms,-1),r.brightness,r.sharpness,r.has_thumb FROM frames r JOIN files f ON f.id=r.file_id JOIN libraries l ON l.id=f.library_id WHERE " + " AND ".join(conditions)
        count = self.info["vector_rows"]
        self.row_file = np.full(count, -1, dtype=np.int32)
        self.frame_data = np.zeros(count, dtype=[("t_ms", "i8"), ("brightness", "f4"), ("sharpness",
            "f4"), ("has_thumb", "?")])
        for row, file_id, t_ms, brightness, sharpness, has_thumb in self.store.db.execute(sql,
            parameters):
            self.row_file[row] = file_id
            self.frame_data[row] = (t_ms, brightness, sharpness, has_thumb)
        self.mask = self.row_file >= 0
        self.metadata = {}

    def get_model(self):
        if self.embedder is None:
            self.embedder = get_embedder(self.model, self.device,
                self.args.offline, self.data["model"]["batch_size"])
        return self.embedder

    def text_vectors(self, texts):
        if any(len(text.split()) > 60 for text in texts):
            self.warnings.append(warning("query_truncated",
                "Long queries may be truncated by the image model."))
        if not getattr(self.args, "no_cache", False) and self.cache is None:
            self.cache = QueryCache(self.index, self.data["library"])
        values = [self.cache.get(self.info["model_id"], text,
            self.info["dim"]) if self.cache else None for text in texts]
        missing = [i for i, value in enumerate(values) if value is None]
        if missing:
            vectors = self.get_model().texts([texts[i] for i in missing])
            for i, vector in zip(missing, vectors, strict=True):
                values[i] = vector
                if self.cache:
                    self.cache.put(self.info["model_id"], texts[i], vector)
        return np.asarray(values, dtype=np.float32)

    def like_vector(self, ident):
        frame_id, _, stamp = ident.partition("@")
        if stamp and not stamp.isdecimal():
            raise AppError("unknown_id", "Unknown indexed item.")
        row = self.store.db.execute("SELECT r.row FROM frames r JOIN files f ON f.id=r.file_id WHERE f.file_key IN (?)" + (" AND r.t_ms=?" if stamp else "") + " ORDER BY r.row LIMIT 1",
            (frame_id, int(stamp)) if stamp else (frame_id,)).fetchone()
        if not row:
            raise AppError("unknown_id", "Unknown indexed item.")
        return normalise(self.matrix[row[0]].astype(np.float32)).reshape(1, -1)

    def score(self, queries):
        values = np.empty((len(self.matrix), len(queries)), dtype=np.float32)
        for offset in range(0, len(self.matrix), 32768):
            values[offset:offset + 32768] = self.matrix[offset:offset + 32768].astype(np.float32) @ queries.T
        return values

    def file(self, ident):
        if ident not in self.metadata:
            row = self.store.rows("SELECT f.*,l.name AS library FROM files f JOIN libraries l ON l.id=f.library_id WHERE f.id=?",
                (int(ident),))[0]
            self.metadata[ident] = dict(row)
        return self.metadata[ident]

    def result(self, row, score, mean, std, start=None, end=None, matched_frames=1):
        metadata = self.file(self.row_file[row])
        frame = self.frame_data[row]
        timestamp = float(frame["t_ms"]) / 1000 if metadata["kind"] == "video" else None
        ident = item_id(metadata["file_key"], int(frame["t_ms"]) if timestamp is not None else None)
        path, open_path = display_path(self.libraries[metadata["library"]], metadata["relpath"])
        thumbnail = thumb_path(self.index, ident)
        return dict(rank=0, item_id=ident, file_id=metadata["file_key"],
            media_type=metadata["kind"], score=round(float(score), 4),
            relevance=round(float((score - mean) / max(std, 1e-6)), 2), library=metadata["library"],
            relative_path=metadata["relpath"], path=path, open_path=open_path,
            filename=Path(metadata["relpath"]).name, width=metadata["width"],
            height=metadata["height"], orientation=metadata["orientation"],
            duration=metadata["duration"], size_bytes=metadata["size"],
            captured_at=metadata["captured_at"],
            modified_at=datetime.fromtimestamp(metadata["mtime_ns"] / 1e9,
            timezone.utc).isoformat(), timestamp=timestamp, start=round(start,
            3) if start is not None else None, end=round(end, 3) if end is not None else None,
            timecode=timecode(timestamp), matched_frames=matched_frames,
            thumbnail=str(thumbnail) if frame["has_thumb"] and thumbnail.exists() else None,
            quality=dict(brightness=round(float(frame["brightness"]), 4),
            sharpness=round(float(frame["sharpness"]), 4)), near_duplicates=0)

    def rank(self, scores, top_k=None, matched=None, texts=None, accept_file=None):
        top_k = top_k or getattr(self.args, "top_k", 20)
        offset = getattr(self.args, "offset", 0)
        rows = np.flatnonzero(self.mask)
        values = scores[rows]
        mean, std, maximum = (float(values.mean()), float(values.std()),
            float(values.max())) if len(values) else (0., 0., 0.)
        stats = dict(mean=round(mean, 4), std=round(std, 4), max=round(maximum, 4), candidates=len(rows))
        if not len(rows):
            return [], stats
        if getattr(self.args, "raw_frames", False):
            ordered = rows[np.argsort(values)[::-1]]
            results = []
            for row in ordered:
                metadata = self.file(int(self.row_file[row]))
                if accept_file is not None and not accept_file(metadata):
                    continue
                result = self.result(int(row), scores[row], mean, std)
                if getattr(self.args, "min_score",
                    None) is not None and result["score"] < self.args.min_score:
                    continue
                if getattr(self.args, "min_relevance",
                    None) is not None and result["relevance"] < self.args.min_relevance:
                    continue
                results.append(result)
                if len(results) >= offset + top_k:
                    break
            results = results[offset:offset + top_k]
            for position, result in enumerate(results, offset + 1):
                result["rank"] = position
            return results, stats
        pool_size = min(len(rows), max(200, 10 * (top_k + offset)))
        accepted = {}
        def eligible(metadata):
            ident = metadata["id"]
            if ident not in accepted:
                accepted[ident] = accept_file is None or accept_file(metadata)
            return accepted[ident]
        while True:
            pool = rows
            if pool_size < len(rows):
                threshold = np.partition(values, len(values) - pool_size)[len(values) - pool_size]
                greater = rows[values > threshold]
                tied = rows[values == threshold][:pool_size - len(greater)]
                pool = np.concatenate((greater, tied))
            pool = pool[np.lexsort((pool, -scores[pool]))]
            kept = self._rank_pool(pool, scores, mean, std, matched, texts, eligible)
            if len(kept) >= offset + top_k or pool_size == len(rows):
                break
            # Exclusions, duplicate groups, and per-file limits can consume
            # any fixed pool. Expand and regroup until enough survive.
            pool_size = min(len(rows), pool_size * 2)
        results = kept[offset:offset + top_k]
        for rank, result in enumerate(results, offset + 1):
            result["rank"] = rank
        return results, stats

    def _rank_pool(self, rows, scores, mean, std, matched, texts, accept_file):
        by_file = {}
        moments = []
        for row in rows:
            by_file.setdefault(int(self.row_file[row]), []).append(int(row))
        for ident, group in by_file.items():
            metadata = self.file(ident)
            if accept_file is not None and not accept_file(metadata):
                continue
            if metadata["kind"] == "photo":
                moments.append((group[0], None, None, 1))
                continue
            group.sort(key=lambda row: self.frame_data[row]["t_ms"])
            runs = []
            step = metadata["sample_interval"]
            for row in group:
                if not runs or (self.frame_data[row]["t_ms"] - self.frame_data[runs[-1][-1]]["t_ms"]) / 1000 > 1.5 * step:
                    runs.append([])
                runs[-1].append(row)
            for run in runs:
                anchor = min(run, key=lambda row: (-scores[row], row))
                time = float(self.frame_data[anchor]["t_ms"]) / 1000
                start = max(0, float(self.frame_data[run[0]]["t_ms"]) / 1000 - step / 2)
                end = min(metadata["duration"],
                    float(self.frame_data[run[-1]]["t_ms"]) / 1000 + step / 2)
                if end - start > self.args.max_clip_seconds:
                    start = max(start, min(time - self.args.max_clip_seconds / 2,
                        end - self.args.max_clip_seconds))
                    end = start + self.args.max_clip_seconds
                if end - start < self.args.min_clip_seconds:
                    start = max(0, min(start - (self.args.min_clip_seconds - (end - start)) / 2,
                        metadata["duration"] - self.args.min_clip_seconds))
                    end = min(metadata["duration"], start + self.args.min_clip_seconds)
                moments.append((anchor, start, end, len(run)))
        moments.sort(key=lambda m: (-scores[m[0]], m[0]))
        kept, anchors, per_file = [], [], {}
        for row, start, end, count in moments:
            ident = int(self.row_file[row])
            if per_file.get(ident, 0) >= self.args.max_per_file:
                continue
            score = round(float(scores[row]), 4)
            relevance = round(float((scores[row] - mean) / max(std, 1e-6)), 2)
            if getattr(self.args, "min_score", None) is not None and score < self.args.min_score:
                continue
            if getattr(self.args, "min_relevance",
                None) is not None and relevance < self.args.min_relevance:
                continue
            vector = normalise(self.matrix[row].astype(np.float32))
            if not getattr(self.args, "no_dedupe", False) and anchors:
                similarities = np.asarray(anchors) @ vector
                duplicates = np.flatnonzero(similarities >= getattr(self.args, "dedupe_threshold", .95))
                if len(duplicates):
                    kept[int(duplicates[0])]["near_duplicates"] += 1
                    continue
            result = self.result(row, scores[row], mean, std, start, end, count)
            if matched is not None:
                result["matched_query"] = texts[int(matched[row])]
            per_file[ident] = per_file.get(ident, 0) + 1
            kept.append(result)
            anchors.append(vector)
        return kept


def read_queries(args):
    texts = [{"text": text} for text in args.queries + args.query]
    if args.queries_file:
        try:
            if args.queries_file == "-":
                texts.extend({"text": line.strip()} for line in sys.stdin if line.strip())
            else:
                path = absolute(args.queries_file)
                with path.open(encoding="utf-8-sig", newline="") as stream:
                    if path.suffix.lower() == ".csv":
                        reader = csv.DictReader(stream, strict=True)
                        fields = reader.fieldnames
                        if not fields or "query" not in fields or len(set(fields)) != len(fields) or set(fields) - {"query",
                            "query_id"}:
                            raise AppError("usage",
                                "Query CSV needs a query column and an optional unique query_id column.")
                        for row in reader:
                            if None in row or any(value is None for value in row.values()) or not row["query"].strip():
                                raise AppError("usage",
                                    f"Query CSV row {reader.line_num} needs all declared cells and a nonempty query.")
                            texts.append(dict(text=row["query"], id=row.get("query_id")))
                    else:
                        texts.extend({"text": line.strip()} for line in stream if line.strip())
        except (OSError, UnicodeError):
            raise AppError("usage", "The query file cannot be read.") from None
        except csv.Error:
            raise AppError("usage", "The query CSV has invalid quoting or fields.") from None
    if args.like and texts or not args.like and not texts:
        raise AppError("usage", "Supply text queries or one --like item.")
    if any(not isinstance(q["text"], str) or not q["text"].strip() for q in texts):
        raise AppError("usage", "Queries must not be empty.")
    return [dict(id=q.get("id") or (re.sub(r"[^a-zA-Z0-9]+", "_",
        q["text"].strip().lower()).strip("_")[:80] or "search"), kind="text", text=q["text"]) for i,
        q in enumerate(texts, 1)]


def command(args):
    data, path, index = config.load(args)
    validate_options(args)
    if args.output:
        writable(args.output, data["library"])
    queries = read_queries(args)
    with Search(data, index, args) as search:
        if args.like:
            queries = [dict(id="q1", kind="like", text=args.like)]
            vectors = search.like_vector(args.like)
        else:
            vectors = search.text_vectors([q["text"] for q in queries])
        scores = search.score(vectors)
        for i, query in enumerate(queries):
            results, stats = search.rank(scores[:, i])
            query.update(score_stats=stats, returned=len(results), results=results)
        return finish(args, dict(index=search.index_summary, filters=filters(args), queries=queries,
            warnings=search.warnings), data["library"])


def show(args):
    data, path, index = config.load(args)
    frame_id, _, stamp = args.id.partition("@")
    with Store(index) as store:
        store.snapshot()
        records = store.rows("SELECT f.*,l.name AS library FROM files f JOIN libraries l ON l.id=f.library_id WHERE f.file_key IN (?)",
            (frame_id,))
        row = records[0] if records else None
        if not row or row["library"] not in {lib["name"] for lib in data["library"]}:
            raise AppError("unknown_id", "Unknown file identifier.")
        frames = store.rows("SELECT * FROM frames WHERE file_id=? ORDER BY t_ms,row", (row["id"],))
        if stamp and not any(str(f["t_ms"]) == stamp for f in frames):
            raise AppError("unknown_id", "Unknown frame identifier.")
        library = next(lib for lib in data["library"] if lib["name"] == row["library"])
        local, display = display_path(library, row["relpath"])
        output = dict(file=dict(file_id=frame_id, library=row["library"], relative_path=row["relpath"],
            path=local, open_path=display, media_type=row["kind"], width=row["width"],
            height=row["height"], orientation=row["orientation"], duration=row["duration"],
            captured_at=row["captured_at"], size_bytes=row["size"], status=row["status"]), frames=[])
        for frame in frames:
            ident = item_id(frame_id, frame["t_ms"])
            time = frame["t_ms"] / 1000 if frame["t_ms"] is not None else None
            thumb = thumb_path(index, ident)
            output["frames"].append(dict(item_id=ident, timestamp=time, timecode=timecode(time),
                thumbnail=str(thumb) if frame["has_thumb"] and thumb.exists() else None,
                quality=dict(brightness=frame["brightness"], sharpness=frame["sharpness"])))
        return output
