"""Persist video jobs before they reach an in-process decoder."""
import json
import os
from ..paths import atomic_write, writable
from .db import file_key


class DecodeJournal:
    def __init__(self, index, libraries):
        self.path = writable(index / "inflight.jsonl", libraries)
        self.libraries = libraries
        self.records = {}
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                record = json.loads(line)
                self.records[record["file_key"]] = record

    def recover(self, store, run_id):
        records = [dict(record, status="failed", fail_reason="interrupted_decode")
                   for record in self.records.values()]
        if records:
            store.checkpoint(records, run=run_id)
        self.records.clear()
        self.rewrite()

    def add(self, library, entry):
        key = file_key(library, entry.relpath)
        record = dict(file_key=key, library=library, relpath=entry.relpath,
                      kind=entry.kind, ext=entry.ext, size=entry.size, mtime_ns=entry.mtime_ns)
        with self.path.open("a") as stream:
            stream.write(json.dumps(record) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        self.records[key] = record

    def checkpoint(self, active):
        self.records = {key: record for key, record in self.records.items() if key in active}
        self.rewrite()

    def rewrite(self):
        if self.records:
            text = "".join(json.dumps(record) + "\n" for record in self.records.values())
            atomic_write(self.path, text, self.libraries)
        else:
            self.path.unlink(missing_ok=True)
