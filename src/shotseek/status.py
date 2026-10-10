from datetime import datetime, timezone
from . import config
from .paths import filesystem_path
from .errors import AppError, warning
from .probe import bounded_call, bounded_probe
from .store.db import Store
from .store.lock import active


def command(args):
    try:
        return bounded_call(lambda: inspect(args), timeout=2)
    except TimeoutError:
        raise AppError("storage_stalled", "Status checks exceeded two seconds.",
            "Check the configured paths and keep the index on a local disk.", 4) from None


def inspect(args):
    data, path, index = config.load(args)
    exists = (index / "meta.sqlite").exists()
    output = dict(config=dict(path=str(path)), index=dict(dir=str(index), exists=exists,
        searchable=False, format_version=1, model=None, dim=None, vectors=0, dead_vectors=0,
        size_bytes=0, thumbnails=data["index"]["thumbnails"]), run=dict(active=False),
        last_run=None, libraries=[])
    files = []
    warnings = []
    if exists:
        with Store(index) as store:
            info = store.kv()
            files = store.files()
            counts = dict(store.db.execute("SELECT file_id,COUNT(*) FROM frames GROUP BY file_id"))
            recent = store.rows("SELECT * FROM runs ORDER BY id DESC LIMIT 1")
            last = recent[0] if recent else None
            output["last_run"] = dict(last) if last else None
            if output["last_run"] is not None:
                output["last_run"].setdefault("not_reached", 0)
            output["index"].update(model=info["model_id"], dim=info["dim"],
                vectors=info["vector_rows"] - info["dead_rows"], dead_vectors=info["dead_rows"],
                searchable=info["vector_rows"] > info["dead_rows"])
        output["run"]["active"] = active(index / "index.lock")
        if output["run"]["active"] and last:
            output["run"].update({field_name: last[field_name] for field_name in ("started_at", "updated_at",
                "discovered", "processed", "indexed", "failed", "walk_complete")})
            output["run"]["not_reached"] = last.get("not_reached", 0)
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(last["started_at"])).total_seconds()
            output["run"]["files_per_minute"] = round(last["processed"] * 60 / max(elapsed, .001), 2)
    if index.exists():
        output["index"]["size_bytes"] = sum(p.stat().st_size for p in index.rglob("*") if p.is_file())
    for library in data["library"]:
        rows = [r for r in files if r["library"] == library["name"]]
        reasons = {}
        for row in rows:
            if row["status"] == "failed":
                reasons[row["fail_reason"]] = reasons.get(row["fail_reason"], 0) + 1
        totals = {status: sum(r["status"] == status for r in rows) for status in ("indexed",
            "failed", "unsupported")}
        totals.update(photos=sum(r["status"] == "indexed" and r["kind"] == "photo" for r in rows),
            videos=sum(r["status"] == "indexed" and r["kind"] == "video" for r in rows))
        ok, reachable = bounded_probe(filesystem_path(library["root"]).is_dir, timeout=.25)
        if not ok or not reachable:
            warnings.append(warning("library_unreachable",
                "Library reachability could not be confirmed within 0.25 seconds: " + library["name"]))
        output["libraries"].append(dict(name=library["name"], root=library["root"],
            reachable=bool(ok and reachable), files=totals, vectors=sum(counts.get(r["id"],
            0) for r in rows) if exists else 0, failures_by_reason=reasons))
    output["warnings"] = warnings
    return output
