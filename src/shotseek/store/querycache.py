import sqlite3
import numpy as np
from ..paths import writable, ensure_index


class QueryCache:
    def __init__(self, index, libraries=()):
        ensure_index(index, libraries, create=False)
        self.db = sqlite3.connect(writable(index / "cache.sqlite", libraries), timeout=5)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS queries(model_id TEXT, text TEXT, vector BLOB, PRIMARY KEY(model_id,text))")

    def get(self, model_id, text, dim):
        row = self.db.execute("SELECT vector FROM queries WHERE model_id=? AND text=?", (model_id,
            text)).fetchone()
        if row:
            value = np.frombuffer(row[0], dtype="<f4").copy()
            if len(value) == dim and np.isfinite(value).all():
                return value
        return None

    def put(self, model_id, text, vector):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO queries VALUES(?,?,?)", (model_id, text,
                np.asarray(vector, dtype="<f4").tobytes()))

    def close(self):
        self.db.close()
