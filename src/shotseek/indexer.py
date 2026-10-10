"""Bounded, resumable indexing with daemon workers and durable checkpoints."""
import json
import math
import os
import queue
import shutil
import signal
import sys
import threading
import time
from . import config
from .embed import get_embedder
from .errors import AppError, warning
from .media import MediaError, load
from .media.ffmpeg import require
from .names import env
from .paths import ensure_index, writable
from .store.db import Store, now, file_key
from .store.inflight import DecodeJournal
from .store.lock import Lock
from .walker import Discovery, RAW


class Workers:
    def __init__(self, count, settings, loader):
        self.jobs = queue.Queue()
        self.results = queue.Queue()
        self.closed = threading.Event()
        self.settings, self.loader = settings, loader
        for _ in range(count):
            self.spawn()

    def spawn(self):
        def work():
            while not self.closed.is_set():
                try:
                    token, entry, force_reader = self.jobs.get(timeout=.1)
                except queue.Empty:
                    continue
                if self.closed.is_set():
                    return
                self.results.put(("start", token, time.monotonic()))
                try:
                    settings = dict(self.settings,
                        frame_reader="ffmpeg") if force_reader else self.settings
                    result, reason = self.loader(entry, settings), None
                except MediaError as exc:
                    result, reason = None, exc.reason
                except OSError:
                    result, reason = None, "read_error"
                except Exception:
                    result, reason = None, "decode_failed"
                self.results.put(("done", token, (result, reason)))
        threading.Thread(target=work, daemon=True).start()


def unchanged(old, entry, settings, retry):
    if old["size"] != entry.size:
        return False
    if settings["change_detection"] == "size+mtime" and abs(old["mtime_ns"] - entry.mtime_ns) > settings["mtime_tolerance_seconds"] * 1e9:
        return False
    if old["status"] == "failed":
        if retry or old["fail_reason"] in {"timeout", "read_error",
            "interrupted_decode"} and old["fail_count"] < 3:
            return False
    return True


def entry_failure(entry):
    try:
        entry.relpath.encode("utf-8")
    except UnicodeError:
        return "path_not_utf8"
    if not all(-(2**63) <= value < 2**63 for value in (entry.size, entry.mtime_ns)):
        return "metadata_out_of_range"
    return None


def clear_index(index, libraries):
    ensure_index(index, libraries, create=False)
    for path in index.iterdir():
        if path.name in {"transcripts", "index.lock", "index.json"}:
            continue
        writable(path, libraries)
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()


def run(args, data, index, embedder=None, loader=None, stop=None, drain_seconds=30):
    require()
    if args.rebuild and not args.yes:
        raise AppError("confirmation_required", "Rebuilding requires --yes.")
    for key in ("workers", "batch_size", "max_files", "max_files_per_library", "time_budget"):
        value = getattr(args, key, None)
        if value is not None and (not math.isfinite(value) or value <= 0):
            raise AppError("usage", key.replace("_", "-") + " must be positive.")
    selected = args.library or [x["name"] for x in data["library"]]
    unknown = set(selected) - {x["name"] for x in data["library"]}
    if unknown:
        raise AppError("library_unknown", "Unknown library: " + sorted(unknown)[0])
    libraries = [x for x in data["library"] if x["name"] in selected]
    if not libraries:
        raise AppError("library_unreachable", "No library roots are configured.", exit_code=4)
    ensure_index(index, data["library"])
    stop = stop or threading.Event()
    settings = data["indexing"]
    workers = args.workers or settings["workers"] or min(8, os.cpu_count() or 1)
    started = time.monotonic()
    warnings = []
    with Lock(index / "index.lock", data["library"]):
        device = config.device(data, args.device)
        descriptor = None
        if not args.rebuild and (index / "meta.sqlite").exists():
            with Store(index) as reader:
                expected = "fake/color-v1" if os.environ.get(env("EMBEDDER")) == "fake" else data["model"]["name"] + "/" + data["model"]["pretrained"]
                if expected != reader.kv()["model_id"]:
                    raise AppError("index_model_mismatch",
                        "The configured model differs from the index.", "Use --rebuild --yes.", 3)
                descriptor = dict(data["model"], model_id=expected, dim=reader.kv()["dim"])
        model = embedder
        if descriptor is None:
            model = model or get_embedder(data["model"], device, args.offline,
                args.batch_size or data["model"]["batch_size"])
            descriptor = dict(data["model"], model_id=model.model_id, dim=model.dim)
        if args.rebuild:
            clear_index(index, data["library"])
        with Store(index, descriptor, write=True, libraries=data["library"],
            thumbnails=data["index"]["thumbnails"], max_edge=data["index"]["thumbnail_max_edge"],
            locked=True) as store:
            run_id = store.start_run(model.device if model else device)
            journal = DecodeJournal(index, data["library"])
            journal.recover(store, run_id)
            old = {(r["library"], r["relpath"]): r for r in store.files()}
            stats = {lib["name"]: dict(name=lib["name"], root=lib["root"], reachable=False,
                walk_complete=False, discovered=0, new=0, changed=0, unchanged=0, indexed=0,
                failed=0, unsupported=0, removed=0, prune_deferred=False) for lib in libraries}
            discovery = Discovery(libraries, settings, stop)
            pool = Workers(workers, settings, loader or load)
            inflight, pending, seen, failures = {}, [], [], []
            token = lost = consecutive_timeouts = 0
            indexed = vectors_added = failed = processed = 0
            last_checkpoint = last_progress = last_activity = time.monotonic()
            status, reason, code = "complete", None, 0
            stopping_at = None
            limited = set()
            deferred = []
            cap = getattr(args, "max_files_per_library", None)
            batch_size = args.batch_size or data["model"]["batch_size"] or getattr(model,
                "batch_size", 16)

            def observe_stop():
                nonlocal status, reason, code, stopping_at
                if stop.is_set() and stopping_at is None:
                    status, reason, code = "interrupted", "signal", 130
                    stopping_at = time.monotonic()

            def progress():
                return dict(discovered=sum(s["discovered"] for s in stats.values()),
                    processed=processed, indexed=indexed, failed=failed,
                    unchanged=sum(s["unchanged"] for s in stats.values()),
                    removed=sum(s["removed"] for s in stats.values()), vectors_added=vectors_added,
                    walk_complete=int(status == "complete" and discovery.done.is_set() and all(s["walk_complete"] for s in discovery.states.values())))

            def checkpoint():
                nonlocal last_checkpoint, model
                missing = [f for r in pending for f in r.get("frames", []) if "vector" not in f]
                if missing and model is None:
                    model = get_embedder(data["model"], device, args.offline,
                        args.batch_size or data["model"]["batch_size"])
                    with store.db:
                        store.update_run(run_id, dict(device=model.device))
                for offset in range(0, len(missing), batch_size):
                    batch = missing[offset:offset + batch_size]
                    values = model.images([f["image"] for f in batch])
                    for frame, vector in zip(batch, values, strict=True):
                        frame["vector"] = vector
                store.checkpoint(pending, seen, run_id, progress())
                journal.checkpoint({file_key(job["library"]["name"], job["entry"].relpath)
                                    for job in inflight.values()})
                pending.clear()
                seen.clear()
                last_checkpoint = time.monotonic()

            def finish(job, result, fail_reason, persist=True):
                nonlocal indexed, vectors_added, failed, processed, consecutive_timeouts
                library, entry = job["library"], job["entry"]
                stat = stats[library["name"]]
                record = dict(library=library["name"], relpath=entry.relpath, kind=entry.kind,
                    ext=entry.ext, size=entry.size, mtime_ns=entry.mtime_ns,
                    status="failed" if fail_reason else "indexed", fail_reason=fail_reason)
                if result:
                    record.update(result)
                    indexed += 1
                    stat["indexed"] += 1
                    vectors_added += len(result["frames"])
                    consecutive_timeouts = 0
                else:
                    failed += 1
                    stat["failed"] += 1
                    consecutive_timeouts = consecutive_timeouts + 1 if fail_reason == "timeout" else 0
                    if len(failures) < 20:
                        display = entry.relpath.encode("utf-8",
                            errors="backslashreplace").decode("utf-8")
                        failures.append(dict(library=library["name"], relative_path=display,
                            reason=fail_reason))
                    if fail_reason == "heic_support_missing" and not any(x["code"] == fail_reason for x in warnings):
                        warnings.append(warning(fail_reason,
                            "Install HEIC support to decode these images."))
                processed += 1
                if persist:
                    pending.append(record)

            try:
                while True:
                    current = time.monotonic()
                    observe_stop()
                    if not stop.is_set() and args.time_budget and current - started >= args.time_budget:
                        status, reason = "partial", "time_budget"
                        stop.set()
                        stopping_at = current - drain_seconds
                    if args.max_files and indexed >= args.max_files and not stop.is_set():
                        status, reason = "partial", "max_files"
                        stop.set()
                        stopping_at = current
                    handed = 0
                    while handed < 64 and not stop.is_set() and len(inflight) < 4 * workers and (not args.max_files or indexed + len(inflight) < args.max_files):
                        try:
                            library, entry = deferred.pop(0) if deferred else discovery.queue.get_nowait()
                        except queue.Empty:
                            break
                        handed += 1
                        if cap:
                            name = library["name"]
                            if stats[name]["indexed"] >= cap:
                                limited.add(name)
                                continue
                            active = sum(job["library"]["name"] == name for job in inflight.values())
                            if stats[name]["indexed"] + active >= cap:
                                deferred.append((library, entry))
                                break
                        last_activity = current
                        stat = stats[library["name"]]
                        stat["discovered"] += 1
                        previous = old.get((library["name"], entry.relpath))
                        fail_reason = entry_failure(entry)
                        if fail_reason:
                            stat["changed" if previous else "new"] += 1
                            finish(dict(library=library, entry=entry), None, fail_reason, persist=False)
                            if previous:
                                seen.append((library["name"], entry.relpath))
                            continue
                        if previous and unchanged(previous, entry, settings, args.retry_failed):
                            seen.append((library["name"], entry.relpath))
                            stat["unchanged"] += 1
                            processed += 1
                            continue
                        stat["changed" if previous and previous["status"] != "failed" else "new"] += 1
                        if entry.ext in RAW:
                            pending.append(dict(library=library["name"], relpath=entry.relpath,
                                kind=entry.kind, ext=entry.ext, size=entry.size,
                                mtime_ns=entry.mtime_ns, status="unsupported",
                                fail_reason="raw_not_supported"))
                            stat["unsupported"] += 1
                            processed += 1
                            continue
                        token += 1
                        inflight[token] = dict(library=library, entry=entry, deadline=None)
                        if entry.kind == "video":
                            journal.add(library["name"], entry)
                        force_reader = bool(previous and previous["fail_reason"] == "interrupted_decode")
                        pool.jobs.put((token, entry, force_reader))
                    while True:
                        try:
                            event, ident, value = pool.results.get_nowait()
                        except queue.Empty:
                            break
                        if ident not in inflight:
                            continue
                        last_activity = time.monotonic()
                        if event == "start":
                            seconds = settings["file_timeout_seconds"] if inflight[ident]["entry"].kind == "photo" else settings["video_timeout_seconds"] + 60
                            inflight[ident]["deadline"] = value + seconds
                        else:
                            finish(inflight.pop(ident), *value)
                    current = time.monotonic()
                    for ident, job in list(inflight.items()):
                        if job["deadline"] is not None and current > job["deadline"]:
                            inflight.pop(ident)
                            finish(job, None, "timeout")
                            lost += 1
                            pool.spawn()
                    walker_stalled = not stop.is_set() and not inflight and discovery.queue.empty() and not discovery.done.is_set() and current - last_activity > max(10,
                        settings["file_timeout_seconds"])
                    if lost >= 8 or consecutive_timeouts >= 5 or walker_stalled:
                        status, reason, code = "aborted", "storage_stalled", 4
                        stop.set()
                        stopping_at = current - drain_seconds
                    if len(pending) + len(seen) >= 64 or current - last_checkpoint >= 30:
                        checkpoint()
                    if current - last_progress >= 5 and args.progress != "none" and not getattr(args,
                        "quiet", False):
                        update = dict(progress(), rate=round(processed / max(current - started,
                            .001), 2), walking=not discovery.done.is_set())
                        print(json.dumps(update) if args.progress == "json" else f"{processed} files, {vectors_added} vectors, {failed} failures, {update['rate']} files/s, walking={update['walking']}",
                            file=sys.stderr)
                        last_progress = current
                    if stop.is_set():
                        observe_stop()
                        if not inflight or time.monotonic() - stopping_at >= drain_seconds:
                            break
                    if discovery.done.is_set() and discovery.queue.empty() and not deferred and not inflight:
                        break
                    time.sleep(.01)
                if cap and status == "complete" and (limited or any(
                        stat["indexed"] >= cap for stat in stats.values())):
                    status, reason = "partial", "max_files"
                checkpoint()
                observe_stop()
                # Discovery can finish well before decoding. Check the root again
                # before declaring success or pruning, without unbounded mount I/O.
                for library in libraries:
                    if not config.root_readable(library["root"], min(5, settings["file_timeout_seconds"])):
                        discovery.states[library["name"]].update(reachable=False,
                            walk_complete=False)
                        if status == "complete" and not code:
                            status, reason, code = "aborted", "library_unreachable", 4
                if status == "complete" and any(not state["reachable"] or state["listing_errors"]
                        for state in discovery.states.values()):
                    status, reason, code = "aborted", "library_unreachable", 4
                for name, state in discovery.states.items():
                    stats[name].update(reachable=state["reachable"],
                        walk_complete=state["walk_complete"] and status == "complete")
                    if state["listing_errors"] and not getattr(args, "quiet", False):
                        print("Directory listing errors in " + name + ": " + str(state["listing_errors"]),
                            file=sys.stderr)
                    if not state["reachable"]:
                        warnings.append(warning("library_unreachable",
                            "Library folder is unavailable or unreadable: " + name +
                            "; reconnect or check permissions and retry."))
                    elif state["listing_errors"]:
                        warnings.append(warning("library_unreachable",
                            "Directory listing failed in " + name + "; reconnect or check permissions and retry."))
                    elif stats[name]["walk_complete"] and not stats[name]["discovered"]:
                        warnings.append(warning("no_media_found",
                            "No supported media found in " + name + "; check the folder and exclusions."))
                if status == "complete" and not args.no_prune:
                    for name, stat in stats.items():
                        if not stat["walk_complete"]:
                            continue
                        records = store.files(name)
                        missing = [r["id"] for r in records if r["last_seen_run"] != run_id]
                        if len(missing) > 100 and len(missing) > len(records) / 2 and not args.prune_missing:
                            stat["prune_deferred"] = True
                            warnings.append(warning("prune_deferred",
                                "Many files are missing from " + name + "; use --prune-missing if this is expected."))
                        else:
                            store.remove_files(missing)
                            stat["removed"] = len(missing)
                if args.strict and failed and not code:
                    code = 8
                if failed:
                    warnings.append(warning("files_failed", str(failed) +
                        " files could not be indexed; see failures_sample and retry with --retry-failed. Use --strict for a failing exit status."))
                if not data["index"]["thumbnails"]:
                    warnings.append(warning("thumbnails_disabled", "Thumbnail storage is disabled."))
                observe_stop()
                with store.db:
                    store.update_run(run_id, dict(progress(), status=status, stop_reason=reason,
                        finished_at=now()))
                info = store.kv()
                if status == "complete" and info["dead_rows"] > 10000 and info["dead_rows"] > info["vector_rows"] * .2:
                    store.compact()
                    info = store.kv()
                result = dict(status=status, stop_reason=reason, device=model.device if model else device,
                    model=descriptor["model_id"], duration_seconds=round(time.monotonic() - started, 3),
                    libraries=list(stats.values()), totals=dict(files_indexed=indexed,
                    vectors_added=vectors_added, failed=failed,
                    removed=sum(s["removed"] for s in stats.values())), failures_sample=failures,
                    index=dict(dir=str(index),
                    files=store.db.execute("SELECT COUNT(*) FROM files WHERE status='indexed'").fetchone()[0],
                    vectors=info["vector_rows"] - info["dead_rows"],
                    searchable=info["vector_rows"] > info["dead_rows"]), warnings=warnings, _exit=code)
                if code:
                    error_code = {4: reason, 8: "files_failed", 130: "interrupted"}[code]
                    result.update(ok=False, error=AppError(error_code,
                        "Index run ended: " + (reason or "files failed"), exit_code=code).as_dict())
                return result
            finally:
                stop.set()
                pool.closed.set()


def command(args):
    data, path, index = config.load(args)
    if args.command == "compact":
        with Store(index, write=True, libraries=data["library"]) as store:
            return store.compact()
    stop = threading.Event()
    previous = {}
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous[sig] = signal.signal(sig, lambda *unused: stop.set())
    try:
        return run(args, data, index, stop=stop)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
