"""Exact-content hashes."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
from PIL import Image

from .quality import dhash as _dhash_gray

PARTIAL = 64 * 1024


def file_hash(path: Path, chunk: int = 1 << 20, limit: int = 0) -> str:
    """BLAKE2b of the whole file, or of the first ``limit`` bytes (pre-hash)."""
    h = hashlib.blake2b(digest_size=20)
    read = 0
    with open(path, "rb") as f:
        while block := f.read(chunk if not limit else min(chunk, limit - read)):
            h.update(block)
            read += len(block)
            if limit and read >= limit:
                break
    return h.hexdigest()


def sha256_file(path: Path) -> str:   # kept for compatibility
    return file_hash(path)


def dhash(im: Image.Image) -> int:
    return _dhash_gray(np.asarray(im.convert("L")))


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()
