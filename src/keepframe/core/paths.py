"""Per-user data locations."""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    base = os.environ.get("KEEPFRAME_DATA") or os.environ.get("LOCALAPPDATA")
    p = Path(base) / "KeepFrame" if base else Path.home() / ".local" / "share" / "KeepFrame"
    p.mkdir(parents=True, exist_ok=True)
    return p


def thumbs_dir() -> Path:
    p = data_dir() / "thumbs"
    p.mkdir(parents=True, exist_ok=True)
    return p
