from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any


STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "are",
    "because",
    "been",
    "before",
    "being",
    "but",
    "can",
    "could",
    "did",
    "does",
    "doing",
    "for",
    "from",
    "get",
    "got",
    "had",
    "has",
    "have",
    "here",
    "how",
    "into",
    "just",
    "like",
    "more",
    "not",
    "now",
    "our",
    "out",
    "over",
    "really",
    "see",
    "she",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "too",
    "was",
    "way",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "will",
    "with",
    "would",
    "you",
    "your",
}

LOW_VALUE_PHRASES = {
    "all right",
    "okay",
    "thank you",
    "thanks",
    "yeah",
    "yes",
    "no",
}

META_PRODUCTION_PHRASES = {
    "ask you the question",
    "repeat the question",
    "question back to me",
    "answer it",
    "say that again",
    "start over",
    "look at me",
    "look at the camera",
    "holding the phone",
    "having a conversation",
    "i'm sorry",
    "sorry",
    "start that",
    "start again",
    "a lot of stuff",
}

TOPIC_PATTERNS = [
    {
        "name": "school",
        "terms": {"school", "student", "students", "teacher", "teachers", "class", "classes",
            "classroom", "education"},
        "brief": "School exterior, classroom activity, students walking halls, teacher helping a student, close-ups of notebooks or classroom details.",
        "search_terms": ["school exterior", "classroom students", "teacher helping student",
            "students walking hallway"],
    },
    {
        "name": "place",
        "terms": {"city", "community", "campus", "neighborhood", "building", "place", "area"},
        "brief": "Location-establishing footage, exterior building shots, street or neighborhood context, signage, wide shots of the area.",
        "search_terms": ["establishing shot", "building exterior", "city street", "local signage"],
    },
    {
        "name": "history",
        "terms": {"past", "years", "history", "before", "used", "remember", "legacy", "story"},
        "brief": "Archival-style visuals, old photos, previous event footage, timeline graphic, slow push-in on historical images or documents.",
        "search_terms": ["archival photos", "old event footage", "history montage", "timeline graphic"],
    },
    {
        "name": "work_team",
        "terms": {"work", "working", "team", "teams", "opportunity", "job", "serve", "help",
            "support", "staff"},
        "brief": "People collaborating, staff at work, close-ups of hands doing the task, candid interaction, behind-the-scenes process shots.",
        "search_terms": ["team collaboration", "staff working", "behind the scenes",
            "hands working close up"],
    },
    {
        "name": "options_process",
        "terms": {"ways", "process", "step", "steps", "program", "application", "apply",
            "different", "option", "options"},
        "brief": "Simple visual breakdown of the options, paperwork or application close-ups, website/form interaction, montage of each path mentioned.",
        "search_terms": ["application form close up", "options graphic", "process steps",
            "website form"],
    },
]


def _words(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z][a-zA-Z'-]{2,}", text.lower())


def _keywords(text: str, limit: int = 8) -> list[str]:
    counts: dict[str, int] = {}
    for word in _words(text):
        if word in STOPWORDS:
            continue
        if len(word) < 4:
            continue
        counts[word] = counts.get(word, 0) + 1
    return [
        word
        for word, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def _chunk_transcript(
    transcript: list[dict[str, Any]],
    min_duration: float = 4.0,
    max_duration: float = 10.0,
) -> list[dict[str, Any]]:
    chunks = []
    current: list[dict[str, Any]] = []

    for segment in transcript:
        if not current:
            current = [segment]
            continue

        start = float(current[0]["start"])
        next_end = float(segment["end"])
        if next_end - start <= max_duration:
            current.append(segment)
        else:
            chunks.append(_merge_segments(current))
            current = [segment]

    if current:
        chunks.append(_merge_segments(current))

    expanded = []
    for chunk in chunks:
        if chunk["end"] - chunk["start"] >= min_duration:
            expanded.append(chunk)
    return expanded


def _merge_segments(segments: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "start": float(segments[0]["start"]),
        "end": float(segments[-1]["end"]),
        "text": " ".join(str(segment["text"]).strip() for segment in segments).strip(),
    }


def _topic_match(text: str) -> dict[str, Any] | None:
    words = set(_words(text))
    scored = []
    for pattern in TOPIC_PATTERNS:
        matches = sorted(words & set(pattern["terms"]))
        if matches:
            scored.append((len(matches), pattern, matches))
    if not scored:
        return None
    _count, pattern, matches = max(scored, key=lambda item: item[0])
    return {**pattern, "matched_terms": matches}


def _need_score(text: str, duration: float, index: int) -> tuple[float, list[str]]:
    lowered = text.lower().strip()
    reasons = []
    score = 0.2

    if any(phrase in lowered for phrase in META_PRODUCTION_PHRASES):
        return 0.05, ["Production/setup instruction, not an editorial b-roll moment."]

    if any(phrase == lowered or lowered.startswith(f"{phrase}.") for phrase in LOW_VALUE_PHRASES):
        return 0.05, ["Low-value filler phrase."]

    keywords = _keywords(text)
    if len(keywords) >= 3:
        score += 0.2
        reasons.append("Transcript contains visualizable subject matter.")

    topic = _topic_match(text)
    if topic:
        score += 0.25
        reasons.append(f"Topic maps to concrete visuals: {', '.join(topic['matched_terms'])}.")

    if "?" in text:
        score += 0.1
        reasons.append("Question or setup moment can benefit from a visual cover or title-style support.")

    if duration >= 7:
        score += 0.1
        reasons.append("Longer talking segment could use b-roll for pacing.")

    if index % 2 == 1:
        score += 0.05
        reasons.append("Placement helps keep visual rhythm across the edit.")

    return min(score, 1.0), reasons or ["General pacing and visual support opportunity."]


def _suggestion_for(text: str) -> tuple[str, list[str]]:
    topic = _topic_match(text)
    keywords = _keywords(text)
    if topic:
        terms = list(dict.fromkeys(topic["search_terms"] + keywords[:4]))
        return topic["brief"], terms

    if keywords:
        phrase = ", ".join(keywords[:5])
        return (
            f"Relevant cutaway footage that shows or supports: {phrase}. Use a stable 3-6 second shot with a clear subject.",
            keywords[:6],
        )

    return (
        "Neutral pacing b-roll: exterior, environment, hands/detail shots, or a simple title/graphic that supports the speaker.",
        ["environment cutaway", "detail shot", "simple title graphic"],
    )


def plan_broll_placements(
    transcript: list[dict[str, Any]],
    max_placements: int = 12,
    min_score: float = 0.45,
) -> list[dict[str, Any]]:
    chunks = _chunk_transcript(transcript)
    placements = []

    for index, chunk in enumerate(chunks):
        duration = float(chunk["end"]) - float(chunk["start"])
        score, reasons = _need_score(str(chunk["text"]), duration, index)
        if score < min_score:
            continue

        brief, search_terms = _suggestion_for(str(chunk["text"]))
        placement_duration = min(6.0, max(3.0, duration))
        placements.append(
            {
                "aroll_start": round(float(chunk["start"]), 3),
                "aroll_end": round(float(chunk["start"]) + placement_duration, 3),
                "score": round(score, 4),
                "matched_transcript_start": round(float(chunk["start"]), 3),
                "matched_transcript_end": round(float(chunk["end"]), 3),
                "matched_transcript_text": chunk["text"],
                "reason": " ".join(reasons),
                "suggested_broll": brief,
                "search_terms": search_terms,
            }
        )

    placements.sort(key=lambda item: item["score"], reverse=True)
    return placements[:max_placements]


def write_plan_json(source_video: str, transcript: list[dict[str, Any]], placements: list[dict[str,
    Any]], output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_video": source_video,
        "mode": "aroll_broll_needed_plan",
        "placements": placements,
        "transcript": transcript,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_batch_summary(rows: list[dict[str, Any]], output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "video",
        "placement_count",
        "top_aroll_start",
        "top_aroll_end",
        "top_score",
        "top_transcript",
        "top_suggested_broll",
        "top_search_terms",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
