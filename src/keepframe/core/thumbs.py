"""Disk thumbnail cache.

Thumbnails are written during the scan (the proxy is decoded anyway), so the review
screen opens instantly: a 512 px JPEG loads in a few milliseconds, even when the
original is a 50 MB RAW or a HEIC that Qt cannot decode itself.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image

from .paths import thumbs_dir

THUMB_SIZE = 512


def key(path: Path, size: int, mtime: float) -> str:
    raw = f"{str(path).lower()}|{size}|{int(mtime)}".encode()
    return hashlib.blake2b(raw, digest_size=12).hexdigest()


def thumb_path(path: Path, size: int, mtime: float, root: Path | None = None) -> Path:
    k = key(path, size, mtime)
    return (root or thumbs_dir()) / k[:2] / f"{k}.jpg"


def save(im: Image.Image, dst: Path) -> None:
    if dst.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    t = im.copy()
    t.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.Resampling.BILINEAR)
    tmp = dst.with_suffix(".tmp")
    t.convert("RGB").save(tmp, "JPEG", quality=85, optimize=False)
    tmp.replace(dst)
