from copy import deepcopy
import numpy as np
from . import config
from . import reruns
from .beats import decorate, split, validate_limits, apply_limits
from .probe import bounded_probe
from .source_identity import source_filter
from .errors import AppError, warning
from .inputs import json_document, text as valid_text, times
from .output import finish
from .paths import absolute, writable
from .search import Search, filters, validate_options
from .transcribe import transcribe_file, public_transcript, save
from .transcribe.parse import read, segments


def edited(path, revisions=None, args=None):
    try:
        doc = json_document(absolute(path).read_text(encoding="utf-8-sig"))
        if not isinstance(doc, dict):
            raise ValueError("The document must be an object containing beats")
        if not isinstance(doc.get("beats"), list):
            raise ValueError("beats must be an array")
        if "transcript" in doc and not isinstance(doc["transcript"], dict):
            raise ValueError("transcript must be an object")
        if not isinstance(doc.get("filters", {}), dict):
            raise ValueError("filters must be an object")
        previous = revisions.get(doc["revision"]) if revisions and "revision" in doc else None
        had_revision = "revision" in doc
        doc = reruns.reconcile(doc, previous)
        rows = doc.get("beats")
        if not isinstance(rows, list) or not rows and not had_revision:
            raise ValueError("beats must be a nonempty array")
        transcript = dict(timed=False, segments=[])
        if "transcript" in doc:
            supplied = doc["transcript"]
            if not isinstance(supplied, dict) or not isinstance(supplied.get("timed"),
                bool) or "segments" not in supplied:
                raise ValueError("transcript must contain a boolean timed field and a segments array")
            transcript = dict(timed=supplied["timed"], segments=segments(supplied, preserve_ids=True))
        result = []
        ids = set()
        score_index = 0
        for i, row in enumerate(rows, 1):
            field = f"beats[{i - 1}]"
            if not isinstance(row, dict):
                raise ValueError(field + " must be an object")
            text = valid_text(row.get("text"), field + ".text")
            queries = None
            point = row.get("_point", False)
            if "visual_queries" in row:
                supplied = row["visual_queries"]
                if not isinstance(supplied, list) or not supplied:
                    raise ValueError(field + ".visual_queries must be a nonempty array of strings")
                queries = [dict(text=valid_text(q, field + ".visual_queries text"),
                    source="agent") for q in supplied]
            elif "queries" in row:
                supplied = row["queries"]
                if not isinstance(supplied, list) or not supplied or any(not isinstance(q,
                    dict) for q in supplied):
                    raise ValueError(field + ".queries must be a nonempty array of objects")
                explicit = []
                for q in supplied:
                    valid_text(q.get("text"), field + ".queries text")
                    origin = q.get("source", "agent")
                    if origin not in ("agent", "sentence", "keywords", "point", "topic"):
                        raise ValueError(field + ".queries source is invalid")
                    if origin == "agent":
                        explicit.append(dict(text=q["text"], source="agent"))
                point = all(q.get("source") == "point" for q in supplied)
                # Tool-generated queries remain derived data, including older
                # documents without a local revision. Explicit queries win.
                queries = explicit or None
            start, end = row.get("start"), row.get("end")
            times(start, end, field)
            segment_ids = row.get("segment_ids", [])
            if not isinstance(segment_ids,
                list) or any(type(n) is not int or n < 1 for n in segment_ids) or len(set(segment_ids)) != len(segment_ids):
                raise ValueError(field + ".segment_ids must be an array of unique positive integers")
            if "transcript" in doc and set(segment_ids) - {s["id"] for s in transcript["segments"]}:
                raise ValueError(field + ".segment_ids must refer to supplied transcript segments")
            beat = decorate(text, i, start, end, segment_ids, point=point, queries=queries,
                            segmenter=getattr(args, "segmenter", "windows"),
                            min_need=getattr(args, "min_need", .45), score_index=score_index)
            length = end - start if start is not None else max(1, len(text.split())) / 2.5
            if getattr(args, "segmenter", "windows") == "pauses" or length >= 4:
                score_index += 1
            ident = valid_text(row.get("id", beat["id"]), field + ".id")
            if ident in ids:
                raise ValueError(field + ".id must be unique")
            ids.add(ident)
            beat["id"] = ident
            result.append(beat)
        source = reruns.source_info(doc["source"]) if "source" in doc else None
        exclusions = doc.get("filters", {}).get("exclude_id", [])
        if not isinstance(exclusions, list):
            raise ValueError("filters.exclude_id must be an array")
        for value in exclusions:
            valid_text(value, "filters.exclude_id")
        return result, transcript, source, previous, exclusions, had_revision
    except (OSError, UnicodeError):
        raise AppError("usage", "The beats file cannot be read as UTF-8.") from None
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        raise AppError("usage", "Invalid beats file: " + str(exc),
            "Check beat text, queries, IDs, and start/end times.") from None


def command(args):
    data, path, index = config.load(args)
    validate_options(args)
    validate_limits(args.min_beat_seconds, args.max_beat_seconds, args.aroll_duration)
    for target in (args.output, args.save_transcript):
        if target:
            writable(target, data["library"])
    apply_limits([], args.max_beats, args.min_need)
    warnings = []
    transcript = dict(timed=False, segments=[])
    beats = None
    previous = None
    revisions = reruns.Revisions(index, data["library"])
    source = dict(kind="points", path=None, duration=None, language=None, whisper_model=None,
        transcript_cached=False)
    if args.aroll:
        source, transcript, warnings = transcribe_file(args.aroll, data, index, args)
    elif args.transcript:
        transcript = read(args.transcript)
        source.update(kind="transcript",
            path=str(absolute(args.transcript)) if args.transcript != "-" else None)
    elif args.beats:
        beats, transcript, original, previous, exclusions, had_revision = edited(args.beats,
            revisions, args)
        source = original or dict(source, kind="beats", path=str(absolute(args.beats)))
        args.exclude_id = sorted(set(args.exclude_id) | set(exclusions))
        if had_revision and previous is None:
            warnings.append(warning("rerun_history_missing",
                "Local revision history is unavailable; supplied beats are authoritative and all results are recomputed."))
    else:
        points = args.point
        if args.points_file:
            try:
                points = [line.strip() for line in absolute(args.points_file).read_text().splitlines() if line.strip()]
            except (OSError, UnicodeError):
                raise AppError("transcript_unparseable", "The points file cannot be read.",
                    exit_code=7) from None
        if not points or any(not text.strip() for text in points):
            raise AppError("transcript_empty", "Supply at least one talking point.", exit_code=7)
        beats = [decorate(text, i, point=True) for i, text in enumerate(points, 1)]
    saved_exclusions = source.get("excluded_file_ids", [])
    args.exclude_id = sorted(set(args.exclude_id) | set(saved_exclusions))
    with Search(data, index, args) as search:
        accept = None
        if source["kind"] == "aroll":
            ok, exists = bounded_probe(lambda: absolute(source["path"]).is_file(), .25)
            if ok and exists:
                if not args.keep_near_duplicates:
                    search.get_model()
                accept = source_filter(source["path"], data["library"], warnings, [], search,
                                       keep_near_duplicates=args.keep_near_duplicates)
            elif not args.beats:
                raise AppError("aroll_not_found", "The A-roll identity cannot be checked.", exit_code=7)
            else:
                warnings.append(warning("library_unreachable",
                    "Saved source exclusions remain active while the A-roll is unavailable."))
        identity = accept.identity if accept else source
        if previous and accept and previous["identity"] != identity:
            raise AppError("usage", "The original A-roll changed since this revision.",
                "Start a new run with --aroll to refresh its transcript and source protection.")
        if beats is None:
            beats = split(transcript, args.min_beat_seconds, args.max_beat_seconds,
                          search.get_model() if args.segmenter == "pauses" else None,
                          args.aroll_duration, args.segmenter, args.min_need, args.max_beats)
            if not transcript["timed"] and args.aroll_duration is not None:
                warnings.append(warning("times_estimated",
                    "Beat times are estimated from the supplied duration."))
        beats = apply_limits(beats, args.max_beats, args.min_need, args.include_filler)
        inputs = {beat["id"]: reruns.beat_input(beat) for beat in beats}
        context = reruns.context(search, args, identity)
        reuse = previous is not None and previous["context"] == context and reruns.checks_unchanged(previous,
            search, accept)
        old = {beat["id"]: beat for beat in previous["beats"]} if reuse else {}
        pending = [b for b in beats if b["id"] not in old or inputs[b["id"]] != previous["inputs"].get(b["id"])]
        pending_ids = {b["id"] for b in pending}
        all_queries = [q["text"] for beat in pending if not beat["skipped"] or args.include_filler for q in beat["queries"]]
        values = search.text_vectors(all_queries) if all_queries else np.empty((0, search.info["dim"]))
        offset = 0
        for beat in beats:
            if beat["id"] not in pending_ids:
                saved = old[beat["id"]]
                beat.update(candidates=deepcopy(saved["candidates"]),
                    score_stats=deepcopy(saved["score_stats"]))
                continue
            beat["candidates"] = []
            beat["score_stats"] = dict(mean=0., std=0., max=0., candidates=0)
            if beat["skipped"] and not args.include_filler:
                continue
            texts = [q["text"] for q in beat["queries"]]
            scores = search.score(values[offset:offset + len(texts)])
            offset += len(texts)
            results, stats = search.rank(scores.max(axis=1), args.per_beat,
                matched=scores.argmax(axis=1), texts=texts, accept_file=accept)
            beat.update(candidates=results, score_stats=stats)
        # Selection depends on current beat order, including reused candidates.
        recommended = set()
        for beat in beats:
            if args.include_filler:
                beat.update(skipped=False, skip_reason=None)
            results = beat["candidates"]
            if not beat["skipped"] and len(results) < args.per_beat:
                warnings.append(warning("insufficient_candidates",
                    f"Beat {beat['id']}: {len(results)} of {args.per_beat} requested candidates are available in the indexed library after filters, source checks, duplicate grouping, and per-file limits."))
            choice = next((r for r in results if r["file_id"] not in recommended),
                results[0] if results else None)
            for result in results:
                result.update(recommended=result is choice,
                    repeat=result is choice and result["file_id"] in recommended)
            if choice:
                recommended.add(choice["file_id"])
        if accept:
            source.update(size=accept.source.st_size, content_sample=accept.digest,
                          excluded_file_ids=sorted(set(saved_exclusions) | set(accept.excluded)))
        revision = revisions.put(dict(source=source, identity=identity,
            transcript=public_transcript(transcript),
                                      beats=beats, inputs=inputs, context=context,
                                          checks=accept.checked if accept else {}))
        save(args, data, source, transcript, beats)
        payload = dict(schema_version=1, revision=revision, source=source,
            transcript=public_transcript(transcript), beats=beats, index=search.index_summary,
            filters=filters(args), warnings=warnings + search.warnings)
        return finish(args, payload, data["library"])
