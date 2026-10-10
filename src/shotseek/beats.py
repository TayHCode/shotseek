"""Deterministic passage boundaries and simple visual-query suggestions."""
import numpy as np
from .errors import AppError
from .inputs import seconds, times
from .output.textout import timecode

from . import planner


def keywords(text):
    return planner._keywords(text)


def decorate(text, number, start=None, end=None, segment_ids=(), point=False, queries=None,
             segmenter="windows", min_need=.45, score_index=None, length=None):
    terms = keywords(text)
    duration = length if length is not None else (
        end - start if start is not None and end is not None else max(1, len(text.split())) / 2.5
    )
    score, reasons = planner._need_score(text, duration,
        number - 1 if score_index is None else score_index)
    topic = planner._topic_match(text)
    suggestion, search_terms = planner._suggestion_for(text)
    explicit = queries is not None and any(q.get("source", "agent") == "agent" for q in queries)
    lowered = text.lower().strip()
    filler = any(phrase in lowered for phrase in planner.META_PRODUCTION_PHRASES) or any(
        phrase == lowered or lowered.startswith(phrase + ".") for phrase in planner.LOW_VALUE_PHRASES
    )
    reason = None
    if not point and not explicit:
        if segmenter == "windows" and duration < 4:
            reason = "too_short"
        elif filler:
            reason = "filler"
        elif score < min_need:
            reason = "low_need"
    if queries is None:
        if point:
            queries = [dict(text=text, source="point")]
        else:
            queries = [dict(text=t, source="topic") for t in topic["search_terms"]] if topic else []
            if terms:
                queries.append(dict(text="a photo of " + ", ".join(terms[:5]), source="keywords"))
            queries.append(dict(text=" ".join(text.split()[:50]), source="sentence"))
    placement_end = round(start + min(6., max(3., duration)), 3) if start is not None else None
    return dict(id=f"b{number:02d}", start=start, end=end, timecode=timecode(start), text=text,
                segment_ids=list(segment_ids), keywords=terms, queries=queries,
                skipped=reason is not None, skip_reason=reason, need_score=round(score, 4),
                need_reasons=reasons, topic=topic["name"] if topic else None,
                suggested_broll=suggestion, search_terms=search_terms,
                placement=dict(start=start, end=placement_end))


def apply_limits(beats, maximum=12, minimum=.45, include_filler=False):
    if type(maximum) is not int or maximum < 0 or not np.isfinite(minimum) or not 0 <= minimum <= 1:
        raise AppError("usage",
            "max-beats must be nonnegative and min-need must be between zero and one.")
    eligible = [b for b in beats if not b["skipped"] and not any(
        q["source"] in {"agent", "point"} for q in b["queries"])]
    selected = {b["id"] for b in sorted(eligible, key=lambda b: -b["need_score"])[:maximum]}
    for beat in beats:
        if maximum and beat in eligible and beat["id"] not in selected:
            beat.update(skipped=True, skip_reason="over_limit")
        if include_filler:
            beat.update(skipped=False, skip_reason=None)
    return beats


def validate_limits(minimum, maximum, duration=None):
    try:
        seconds(minimum, "min-beat-seconds")
        seconds(maximum, "max-beat-seconds")
        if duration is not None:
            seconds(duration, "aroll-duration")
        if not 0 < minimum <= maximum or duration is not None and duration <= 0:
            raise ValueError("Beat durations must be positive and ordered")
    except ValueError as exc:
        raise AppError("usage", str(exc)) from None


def split_pauses(transcript, minimum=5, maximum=20, embedder=None, duration=None):
    validate_limits(minimum, maximum, duration)
    source = transcript["segments"]
    if not source:
        return []
    timed = transcript["timed"]
    working, cursor = [], 0.
    for row in source:
        try:
            times(row.get("start"), row.get("end"), "transcript segment")
        except ValueError as exc:
            raise AppError("usage", str(exc)) from None
        value = dict(row)
        if not timed:
            value["start"] = cursor
            cursor += max(1, len(row["text"].split())) / 2.5
            value["end"] = cursor
        working.append(value)
    similarity, threshold = None, None
    if embedder is not None and len(source) >= 4:
        vectors = embedder.texts([row["text"] for row in source])
        similarity = np.sum(vectors[:-1] * vectors[1:], axis=1)
        threshold = float(similarity.mean() - .5 * similarity.std())
    groups = [[working[0]]]
    for i, row in enumerate(working[1:], 1):
        current = groups[-1]
        force = row["end"] - current[0]["start"] > maximum or sum(len(s["text"].split()) for s in current) + len(row["text"].split()) > 60 or row.get("_break_before",
            False)
        want = row["start"] - current[-1]["end"] >= 1.5 or threshold is not None and similarity[i - 1] < threshold
        if force or want and current[-1]["end"] - current[0]["start"] >= minimum:
            groups.append([row])
        else:
            current.append(row)
    if len(groups) > 1:
        last, previous = groups[-1], groups[-2]
        if not last[0].get("_break_before",
            False) and last[-1]["end"] - last[0]["start"] < minimum and last[-1]["end"] - previous[0]["start"] <= 1.25 * maximum:
            groups[-2:] = [previous + last]
    scale = duration / cursor if duration is not None and not timed else 1
    result = []
    for i, group in enumerate(groups, 1):
        start = round(group[0]["start"] * scale, 3) if timed or duration is not None else None
        end = round(group[-1]["end"] * scale, 3) if timed or duration is not None else None
        result.append(decorate(" ".join(row["text"] for row in group), i, start, end,
            [row["id"] for row in group], segmenter="pauses",
                               length=(group[-1]["end"] - group[0]["start"]) * scale))
    return result


def split(transcript, minimum=5, maximum=20, embedder=None, duration=None,
          segmenter="windows", min_need=.45, max_beats=12):
    validate_limits(minimum, maximum, duration)
    apply_limits([], max_beats, min_need)
    if segmenter == "pauses":
        beats = split_pauses(transcript, minimum, maximum, embedder, duration)
        for beat in beats:
            explicit = any(q["source"] in {"agent", "point"} for q in beat["queries"])
            if not explicit and beat["skip_reason"] not in {"filler", "too_short"}:
                beat.update(skipped=beat["need_score"] < min_need,
                            skip_reason="low_need" if beat["need_score"] < min_need else None)
        return apply_limits(beats, max_beats, min_need)
    source = transcript["segments"]
    timed = transcript["timed"]
    working, cursor = [], 0.
    for row in source:
        try:
            times(row.get("start"), row.get("end"), "transcript segment")
        except ValueError as exc:
            raise AppError("usage", str(exc)) from None
        value = dict(row)
        if not timed:
            value["start"] = cursor
            cursor += max(1, len(value["text"].split())) / 2.5
            value["end"] = cursor
        working.append(value)
    scale = duration / cursor if duration is not None and not timed and cursor else 1
    for row in working:
        row["start"] *= scale
        row["end"] *= scale
    chunks = planner._chunk_transcript(working, min_duration=0)
    result, index = [], 0
    for number, chunk in enumerate(chunks, 1):
        length = chunk["end"] - chunk["start"]
        ids = [r["id"] for r in working if chunk["start"] <= r["start"] < chunk["end"]]
        start = round(chunk["start"], 3) if timed or duration is not None else None
        end = round(chunk["end"], 3) if timed or duration is not None else None
        result.append(decorate(chunk["text"], number, start, end, ids,
                               min_need=min_need, score_index=index, length=length))
        if length >= 4:
            index += 1
    return apply_limits(result, max_beats, min_need)
