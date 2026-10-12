"""SQLite catalog: cache of files, assets, features, user decisions and action log."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .paths import data_dir

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS library(
  id INTEGER PRIMARY KEY, root_path TEXT UNIQUE NOT NULL,
  added_at REAL NOT NULL, excluded_globs TEXT DEFAULT '');

CREATE TABLE IF NOT EXISTS asset(
  id INTEGER PRIMARY KEY, primary_path TEXT UNIQUE NOT NULL,
  taken_at REAL, camera TEXT DEFAULT '', serial TEXT DEFAULT '', burst_id TEXT DEFAULT '',
  width INTEGER DEFAULT 0, height INTEGER DEFAULT 0, size INTEGER DEFAULT 0,
  mtime REAL DEFAULT 0, is_favorite INTEGER DEFAULT 0, rating INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_asset_time ON asset(camera, taken_at);

CREATE TABLE IF NOT EXISTS file(
  id INTEGER PRIMARY KEY, asset_id INTEGER REFERENCES asset(id) ON DELETE CASCADE,
  path TEXT UNIQUE NOT NULL, size INTEGER, mtime REAL, kind TEXT);

CREATE TABLE IF NOT EXISTS feature(
  asset_id INTEGER PRIMARY KEY REFERENCES asset(id) ON DELETE CASCADE,
  sha256 TEXT, pdq BLOB, pdq_q INTEGER, dhash INTEGER,
  emb BLOB, model_ver TEXT, sharp REAL, exposure REAL,
  faces_json TEXT, eyes_open REAL, smile REAL, computed_at REAL);
CREATE INDEX IF NOT EXISTS ix_feature_sha ON feature(sha256);

CREATE TABLE IF NOT EXISTS grp(
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, scan_id INTEGER,
  status TEXT NOT NULL DEFAULT 'open');
CREATE TABLE IF NOT EXISTS grp_member(
  grp_id INTEGER REFERENCES grp(id) ON DELETE CASCADE, asset_id INTEGER,
  score REAL, reasons_json TEXT, suggested TEXT, user_action TEXT,
  PRIMARY KEY(grp_id, asset_id));

CREATE TABLE IF NOT EXISTS ignored_pair(
  a INTEGER NOT NULL, b INTEGER NOT NULL, created_at REAL, PRIMARY KEY(a, b));

CREATE TABLE IF NOT EXISTS ignored_paths(
  a TEXT NOT NULL, b TEXT NOT NULL, created_at REAL, PRIMARY KEY(a, b));

CREATE TABLE IF NOT EXISTS action_log(
  id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, asset_id INTEGER, op TEXT NOT NULL,
  src_path TEXT NOT NULL, dst_path TEXT, ts REAL NOT NULL, undone INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS scan(
  id INTEGER PRIMARY KEY, started_at REAL, finished_at REAL,
  settings_json TEXT, stats_json TEXT);
"""


def default_path() -> Path:
    return data_dir() / "catalog.db"


class Catalog:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else default_path()
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)
        self.db.execute("INSERT OR IGNORE INTO meta VALUES('schema_version', ?)",
                        (str(SCHEMA_VERSION),))
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # --- user decisions -------------------------------------------------
    def ignore_pair(self, a: int, b: int) -> None:
        import time
        a, b = min(a, b), max(a, b)
        self.db.execute("INSERT OR IGNORE INTO ignored_pair VALUES(?,?,?)", (a, b, time.time()))
        self.db.commit()

    def ignored_pairs(self) -> set[tuple[int, int]]:
        return {(r[0], r[1]) for r in self.db.execute("SELECT a, b FROM ignored_pair")}

    def ignore_paths(self, a: str, b: str) -> None:
        """Remember "not duplicates" by normalised path (stable across scans)."""
        import time
        x, y = sorted((os.path.normcase(a), os.path.normcase(b)))
        self.db.execute("INSERT OR IGNORE INTO ignored_paths VALUES(?,?,?)", (x, y, time.time()))
        self.db.commit()

    def ignored_path_pairs(self) -> set[tuple[str, str]]:
        return {(r[0], r[1]) for r in self.db.execute("SELECT a, b FROM ignored_paths")}

    def clear_ignored(self) -> None:
        self.db.execute("DELETE FROM ignored_paths")
        self.db.commit()

    def sessions(self, limit: int = 50) -> list[tuple[str, float, int, int]]:
        """(session_id, time, files, undone_files) newest first."""
        q = ("SELECT session_id, MIN(ts), COUNT(*), SUM(CASE WHEN undone=1 THEN 1 ELSE 0 END)"
             " FROM action_log WHERE undone >= 0 GROUP BY session_id ORDER BY MIN(ts) DESC LIMIT ?")
        return [tuple(r) for r in self.db.execute(q, (limit,))]
