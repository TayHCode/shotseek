from .csvout import rows


def timecode(seconds):
    if seconds is None:
        return None
    total = int(round(seconds * 1000))
    hours, rest = divmod(total, 3600000)
    minutes, rest = divmod(rest, 60000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def format_document(document):
    lines = []
    for row in rows(document):
        span = "" if row["start"] is None else f" {timecode(row['start'])}-{timecode(row['end'])}"
        lines.append(f"{row['rank']}. {row['score']:.4f} ({row['relevance']:.2f}) {row['media_type']}{span} {row['open_path']}")
    return "\n".join(lines) + ("\n" if lines else "")
