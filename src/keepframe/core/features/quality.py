"""Cheap, license-free quality signals used for best-shot ranking (OpenCV, GIL-free)."""

from __future__ import annotations

import cv2
import numpy as np

cv2.setNumThreads(1)


def sharpness(gray: np.ndarray) -> float:
    """Variance of the Laplacian on the centre 60% after a light blur (noise-robust).

    Compare only *within a group*; absolute values depend on content.
    """
    h, w = gray.shape[:2]
    if h < 8 or w < 8:
        return 0.0
    y0, y1, x0, x1 = int(h * .2), int(h * .8), int(w * .2), int(w * .8)
    c = cv2.GaussianBlur(gray[y0:y1, x0:x1], (3, 3), 0)
    return float(cv2.Laplacian(c, cv2.CV_32F).var())


def exposure_clip(gray: np.ndarray, lo: int = 3, hi: int = 252) -> float:
    """Fraction of pixels that are crushed black or blown white."""
    return float(np.mean((gray <= lo) | (gray >= hi)))


def dhash(gray: np.ndarray) -> int:
    """64-bit difference hash."""
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA).astype(np.int16)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    return int.from_bytes(np.packbits(bits).tobytes(), "big")
