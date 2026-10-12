"""Feature cache: makes the second scan of a library take seconds.

Keyed by normcase(path) with (size, mtime_ns) validation. Embeddings are stored with the
model version, so swapping the model invalidates only them. The cache is disposable:
if the file is corrupt it is renamed and recreated.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .paths import data_dir

CACHE_VERSION = 2
COLS = ("path", "size", "mtime_ns", "taken_at", "time_source", "camera", "burst_id", "width",
        "height", "rating", "dhash", "sharp", "exposure", "ok", "emb", "model_ver")
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS fcache_v{CACHE_VERSION}(
  path TEXT PRIMARY KEY, size INTEGER, mtime_ns INTEGER,
  taken_at REAL, time_source TEXT, camera TEXT, burst_id TEXT,
  width INTEGER, height INTEGER, rating INTEGER,
  dhash INTEGER, sharp REAL, exposure REAL, ok INTEGER,
  emb BLOB, model_ver TEXT);
"""
TABLE = f"fcache_v{CACHE_VERSION}"


@dataclass
class Row:
    taken_at: float | None
    time_source: str
    camera: str
    burst_id: str
    width: int
    height: int
    rating: int
    dhash: int
    sharp: float
    exposure: float
    ok: bool
    emb: np.ndarray | None = None
    model_ver: str = ""


def _key(path: str) -> str:
    return os.path.normcase(path)


def _ns(mtime: float) -> int:
    return int(round(mtime * 1e9))


class FeatureCache:
    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "cache.db"
        self.lock = threading.Lock()
        try:
            self._open()
        except sqlite3.DatabaseError:
            self.path.replace(self.path.with_suffix(".corrupt"))
            self._open()

    def _open(self):
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)

    def get_many(self, entries: list[tuple[str, int, float]]) -> dict[str, Row]:
        with self.lock:
            idx = {r[0]: (r[1], r[2]) for r in
                   self.db.execute(f"SELECT path, size, mtime_ns FROM {TABLE}")}
        valid = [p for p, s, m in entries
                 if idx.get(_key(p)) == (s, _ns(m))]
        out: dict[str, Row] = {}
        bykey = {_key(p): p for p in valid}
        keys = list(bykey)
        with self.lock:
            for i in range(0, len(keys), 500):
                chunk = keys[i : i + 500]
                q = f"SELECT {','.join(COLS)} FROM {TABLE} WHERE path IN ({','.join('?' * len(chunk))})"
                for r in self.db.execute(q, chunk):
                    d = dict(zip(COLS, r, strict=False))
                    emb = np.frombuffer(d["emb"], dtype=np.float16) if d["emb"] else None
                    dh = d["dhash"] or 0
                    out[bykey[d["path"]]] = Row(
                        d["taken_at"], d["time_source"] or "", d["camera"] or "",
                        d["burst_id"] or "", d["width"] or 0, d["height"] or 0,
                        d["rating"] or 0, dh & (2**64 - 1), d["sharp"] or 0.0,
                        d["exposure"] or 0.0, bool(d["ok"]), emb, d["model_ver"] or "")
        return out

    def put(self, path: str, size: int, mtime: float, row: Row) -> None:
        emb = row.emb.astype(np.float16).tobytes() if row.emb is not None else None
        dh = row.dhash - 2**64 if row.dhash >= 2**63 else row.dhash
        with self.lock:
            self.db.execute(
                f"INSERT OR REPLACE INTO {TABLE}({','.join(COLS)}) VALUES({','.join('?' * len(COLS))})",
                (_key(path), size, _ns(mtime), row.taken_at, row.time_source, row.camera,
                 row.burst_id, row.width, row.height, row.rating, dh, row.sharp,
                 row.exposure, int(row.ok), emb, row.model_ver))

    def set_emb(self, path: str, emb: np.ndarray, model_ver: str) -> None:
        with self.lock:
            self.db.execute(f"UPDATE {TABLE} SET emb=?, model_ver=? WHERE path=?",
                            (emb.astype(np.float16).tobytes(), model_ver, _key(path)))

    def commit(self) -> None:
        with self.lock:
            self.db.commit()

    def clear(self) -> None:
        with self.lock:
            self.db.execute(f"DELETE FROM {TABLE}")
            self.db.commit()

    def count(self) -> int:
        with self.lock:
            return self.db.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]

    def close(self) -> None:
        self.commit()
        self.db.close()
