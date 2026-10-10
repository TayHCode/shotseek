from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import numpy as np
from ..errors import AppError
from ..paths import ensure_index, atomic_write, writable
from .lock import Lock
from . import vectors, thumbs

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS libraries(id INTEGER PRIMARY KEY, name TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS files(
 id INTEGER PRIMARY KEY, library_id INTEGER, relpath TEXT, file_key TEXT UNIQUE,
 kind TEXT, ext TEXT, size INTEGER, mtime_ns INTEGER, status TEXT,
 fail_reason TEXT, fail_count INTEGER, width INTEGER, height INTEGER,
 orientation TEXT, duration REAL, sample_interval REAL, captured_at TEXT,
 frame_count INTEGER, indexed_at TEXT, last_seen_run INTEGER,
 UNIQUE(library_id, relpath));
CREATE TABLE IF NOT EXISTS frames(row INTEGER PRIMARY KEY, file_id INTEGER, t_ms INTEGER,
 brightness REAL, sharpness REAL, has_thumb INTEGER);
CREATE INDEX IF NOT EXISTS frames_file ON frames(file_id);
CREATE INDEX IF NOT EXISTS files_library ON files(library_id);
CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, started_at TEXT, updated_at TEXT,
 finished_at TEXT, status TEXT, stop_reason TEXT, device TEXT, discovered INTEGER,
 processed INTEGER, indexed INTEGER, failed INTEGER, unchanged INTEGER, removed INTEGER,
 vectors_added INTEGER, walk_complete INTEGER);
"""


def now():
    return datetime.now(timezone.utc).isoformat()


def file_key(library, relpath):
    return hashlib.sha1((library + "\0" + relpath).encode()).hexdigest()[:16]


def item_id(key, t_ms):
    return key if t_ms is None else key + "@" + str(t_ms)


class Store:
    def __init__(self, index, model=None, write=False, libraries=(), thumbnails=True, max_edge=320,
        locked=False):
        self.index = Path(index)
        self.libraries = libraries
        self.write = write
        self.thumbnails = thumbnails
        self.max_edge = max_edge
        self.lock = None
        self.db = None
        try:
            if (not write or model is None) and not (self.index / "meta.sqlite").exists():
                raise AppError("index_not_found", "No built index exists.", "Run index first.", 3)
            ensure_index(self.index, libraries, create=write)
            if write:
                if not locked:
                    self.lock = Lock(self.index / "index.lock", libraries)
                    self.lock.__enter__()
                self.db = sqlite3.connect(writable(self.index / "meta.sqlite", libraries), timeout=5)
                self.db.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA busy_timeout=5000;" + SCHEMA)
                if not self.kv():
                    if not model:
                        raise AppError("index_corrupt", "The index has no model descriptor.",
                            exit_code=3)
                    with self.db:
                        for key, value in dict(format_version=1, model_id=model["model_id"],
                            dim=model["dim"], vector_gen=1, vector_rows=0, dead_rows=0).items():
                            self.set(key, value)
                info = self.kv()
                if model and info["model_id"] != model["model_id"]:
                    raise AppError("index_model_mismatch",
                        "The configured model differs from the index.",
                        "Use --rebuild --yes to build a new index.", 3)
                vectors.truncate(vectors.vector_path(self.index, info["vector_gen"]),
                    info["vector_rows"], info["dim"], libraries)
                if model:
                    marker = json.loads((self.index / "index.json").read_text())
                    marker.update(model=model.get("name"), pretrained=model.get("pretrained"),
                        model_id=model["model_id"], dim=model["dim"])
                    atomic_write(self.index / "index.json", json.dumps(marker), libraries)
            else:
                self.db = sqlite3.connect((self.index / "meta.sqlite").as_uri() + "?mode=ro",
                    uri=True, timeout=5)
                self.db.execute("PRAGMA query_only=ON")
                self.db.execute("PRAGMA busy_timeout=5000")
            if self.kv().get("format_version") != 1:
                raise AppError("index_format_unsupported", "Unsupported database format.", exit_code=3)
        except sqlite3.DatabaseError:
            self.close()
            raise AppError("index_corrupt", "The index database cannot be read.", exit_code=3) from None
        except Exception:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if self.db:
            self.db.close()
            self.db = None
        if self.lock:
            self.lock.__exit__()
            self.lock = None

    def kv(self):
        data = dict(self.db.execute("SELECT key,value FROM kv"))
        for key in ("format_version", "dim", "vector_gen", "vector_rows", "dead_rows"):
            if key in data:
                try:
                    data[key] = int(data[key])
                except (ValueError, TypeError):
                    raise AppError("index_corrupt", "Invalid index metadata.", exit_code=3) from None
        required = {"format_version", "dim", "model_id", "vector_gen", "vector_rows", "dead_rows"}
        if data and (not required <= data.keys() or data.get("dim",
            0) <= 0 or data.get("vector_gen", 0) <= 0 or not 0 <= data.get("dead_rows",
            -1) <= data.get("vector_rows", -1)):
            raise AppError("index_corrupt", "Invalid index metadata.", exit_code=3)
        return data

    def set(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO kv VALUES(?,?)", (key, str(value)))

    def library_id(self, name):
        self.db.execute("INSERT OR IGNORE INTO libraries(name) VALUES(?)", (name,))
        return self.db.execute("SELECT id FROM libraries WHERE name=?", (name,)).fetchone()[0]

    def rows(self, sql, parameters=()):
        cursor = self.db.execute(sql, parameters)
        columns = [column[0] for column in cursor.description]
        return [dict(zip(columns, row)) for row in cursor]

    def files(self, library=None):
        sql = "SELECT files.*, libraries.name AS library FROM files JOIN libraries ON libraries.id=files.library_id"
        params = ()
        if library is not None:
            sql += " WHERE libraries.name=?"
            params = (library,)
        return self.rows(sql, params)

    def start_run(self, device):
        with self.db:
            cursor = self.db.execute("INSERT INTO runs(started_at,updated_at,status,device,discovered,processed,indexed,failed,unchanged,removed,vectors_added,walk_complete) VALUES(?,?,'running',?,0,0,0,0,0,0,0,0)",
                (now(), now(), device))
        return cursor.lastrowid

    def update_run(self, run, values):
        allowed = {"status", "stop_reason", "finished_at", "discovered", "processed", "indexed",
            "failed", "unchanged", "removed", "vectors_added", "walk_complete"}
        fields = {key: value for key, value in values.items() if key in allowed}
        fields["updated_at"] = now()
        self.db.execute("UPDATE runs SET " + ",".join(key + "=?" for key in fields) + " WHERE id=?",
            (*fields.values(), run))

    def checkpoint(self, records=(), seen=(), run=None, progress=None, fault=None):
        info = self.kv()
        start = info["vector_rows"]
        frames = [frame for record in records for frame in record.get("frames", [])]
        values = np.asarray([frame["vector"] for frame in frames], dtype=np.float32).reshape((-1,
            info["dim"]))
        total = vectors.append(vectors.vector_path(self.index, info["vector_gen"]), start,
            info["dim"], values, self.libraries)
        if fault:
            fault("vectors")
        for record in records:
            file_identity = file_key(record["library"], record["relpath"])
            for frame in record.get("frames", []):
                if self.thumbnails and frame.get("image") is not None:
                    thumbs.write(self.index, item_id(file_identity, frame.get("t_ms")), frame["image"],
                        self.max_edge, self.libraries)
        if fault:
            fault("thumbs")
        with self.db:
            dead = info["dead_rows"]
            row_number = start
            for record in records:
                lib_id = self.library_id(record["library"])
                file_identity = file_key(record["library"], record["relpath"])
                old = self.db.execute("SELECT id, fail_count FROM files WHERE file_key IN (?)", (file_identity,
                    )).fetchone()
                if old:
                    dead += self.db.execute("SELECT COUNT(*) FROM frames WHERE file_id=?", (old[0],
                        )).fetchone()[0]
                    self.db.execute("DELETE FROM frames WHERE file_id=?", (old[0],))
                fail_count = ((old[1] or 0) + 1 if old else 1) if record["status"] == "failed" else 0
                columns = ["library_id", "relpath", "file_key", "kind", "ext", "size", "mtime_ns",
                    "status", "fail_reason", "fail_count", "width", "height", "orientation",
                    "duration", "sample_interval", "captured_at", "frame_count", "indexed_at",
                    "last_seen_run"]
                values = dict(record, library_id=lib_id, file_key=file_identity, fail_count=fail_count,
                    frame_count=len(record.get("frames", [])), indexed_at=now(), last_seen_run=run or 0)
                self.db.execute("INSERT INTO files(" + ",".join(columns) + ") VALUES(" + ",".join("?" for _ in columns) + ") ON CONFLICT(file_key) DO UPDATE SET " + ",".join(c + "=excluded." + c for c in columns),
                    [values.get(c) for c in columns])
                file_id = self.db.execute("SELECT id FROM files WHERE file_key IN (?)", (file_identity,)).fetchone()[0]
                rows = []
                for frame in record.get("frames", []):
                    rows.append((row_number, file_id, frame.get("t_ms"), frame.get("brightness",
                        .5), frame.get("sharpness", 0),
                        int(self.thumbnails and frame.get("image") is not None)))
                    row_number += 1
                self.db.executemany("INSERT INTO frames VALUES(?,?,?,?,?,?)", rows)
            for library, relpath in seen:
                self.db.execute("UPDATE files SET last_seen_run=? WHERE library_id=(SELECT id FROM libraries WHERE name=?) AND relpath=?",
                    (run, library, relpath))
            self.set("vector_rows", total)
            self.set("dead_rows", dead)
            if run is not None:
                self.update_run(run, progress or {})
            if fault:
                fault("transaction")

    def remove_files(self, ids):
        removed_thumbs = []
        with self.db:
            dead = self.kv()["dead_rows"]
            for file_id in ids:
                for row in self.db.execute("SELECT file_key,t_ms FROM files JOIN frames ON frames.file_id=files.id WHERE files.id=?",
                    (file_id,)):
                    removed_thumbs.append(item_id(row[0], row[1]))
                dead += self.db.execute("SELECT COUNT(*) FROM frames WHERE file_id=?", (file_id,
                    )).fetchone()[0]
                self.db.execute("DELETE FROM frames WHERE file_id=?", (file_id,))
                self.db.execute("DELETE FROM files WHERE id=?", (file_id,))
            self.set("dead_rows", dead)
        for ident in removed_thumbs:
            thumbs.remove(self.index, ident, self.libraries)

    def snapshot(self):
        for attempt in range(2):
            self.db.rollback()
            self.db.execute("BEGIN")
            info = self.kv()
            try:
                matrix = vectors.read(vectors.vector_path(self.index, info["vector_gen"]),
                    info["vector_rows"], info["dim"])
                return info, matrix
            except FileNotFoundError:
                self.db.rollback()
                if attempt:
                    raise AppError("index_corrupt", "The committed vector file is missing.",
                        exit_code=3) from None
                time.sleep(.2)

    def compact(self):
        info = self.kv()
        old = vectors.vector_path(self.index, info["vector_gen"])
        new = vectors.vector_path(self.index, info["vector_gen"] + 1)
        matrix = vectors.read(old, info["vector_rows"], info["dim"])
        rows = self.rows("SELECT * FROM frames ORDER BY row")
        vectors.truncate(new, 0, info["dim"], self.libraries)
        count = 0
        for offset in range(0, len(rows), 32768):
            chunk = rows[offset:offset + 32768]
            values = matrix[[r["row"] for r in chunk]]
            count = vectors.append(new, count, info["dim"], values, self.libraries)
        with self.db:
            self.db.execute("DELETE FROM frames")
            self.db.executemany("INSERT INTO frames VALUES(?,?,?,?,?,?)", [(i, r["file_id"],
                r["t_ms"], r["brightness"], r["sharpness"], r["has_thumb"]) for i, r in enumerate(rows)])
            self.set("vector_gen", info["vector_gen"] + 1)
            self.set("vector_rows", len(rows))
            self.set("dead_rows", 0)
        del matrix
        ensure_index(self.index, self.libraries, create=False)
        writable(old, self.libraries).unlink()
        return dict(rows_before=info["vector_rows"], rows_after=len(rows))


def purge_library(index, name, libraries):
    if not (Path(index) / "meta.sqlite").exists():
        return
    with Store(index, write=True, libraries=libraries) as store:
        store.remove_files([r["id"] for r in store.files(name)])
