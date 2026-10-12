"""Stage 6: decide whether a candidate pair is the same shot."""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class Thresholds:
    """Similarity thresholds. AI values are DINOv2 cosine; dHash values are 1 - bits/64."""

    high: float = 0.92
    low: float = 0.80
    group_mean: float = 0.85
    orb_min_inliers: int = 25
    orb_min_ratio: float = 0.30
    auto_link_dt: float = 1e9        # auto-link only within this many seconds

    @classmethod
    def ai(cls, s: float) -> Thresholds:
        """``s`` = strictness slider, 0 = loose, 1 = strict."""
        sh = (min(max(s, 0.0), 1.0) - 0.5) * 0.10
        return cls(high=0.92 + sh, low=0.80 + sh, group_mean=0.85 + sh)

    @classmethod
    def dhash(cls, s: float) -> Thresholds:
        # dHash is much weaker: auto-link only near-identical hashes shot within 3 s,
        # everything else must pass the geometric check.
        sh = (min(max(s, 0.0), 1.0) - 0.5) * 0.06
        return cls(high=0.94 + sh, low=0.78 + sh, group_mean=0.80 + sh,
                   orb_min_inliers=40, orb_min_ratio=0.35, auto_link_dt=3.0)


class OrbCache:
    """ORB keypoints/descriptors computed once per thumbnail (LRU)."""

    def __init__(self, max_items: int = 4000):
        self.max = max_items
        self.data: OrderedDict[str, tuple] = OrderedDict()
        self.lock = threading.Lock()
        self.local = threading.local()

    def _orb(self):
        if not hasattr(self.local, "orb"):
            self.local.orb = cv2.ORB_create(nfeatures=1200)
        return self.local.orb

    def get(self, thumb: Path):
        k = str(thumb)
        with self.lock:
            if k in self.data:
                self.data.move_to_end(k)
                return self.data[k]
        buf = np.fromfile(str(thumb), dtype=np.uint8)       # unicode-safe on Windows
        g = cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)
        val = (None, None) if g is None else self._orb().detectAndCompute(g, None)
        with self.lock:
            self.data[k] = val
            if len(self.data) > self.max:
                self.data.popitem(last=False)
        return val


def orb_match(cache: OrbCache, a: Path, b: Path) -> tuple[int, float]:
    """Lowe-ratio matching + MAGSAC homography. Returns (inliers, inlier_ratio)."""
    ka, da = cache.get(a)
    kb, db = cache.get(b)
    if da is None or db is None or len(ka) < 12 or len(kb) < 12:
        return 0, 0.0
    matches = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(da, db, k=2)
    good = [m[0] for m in matches if len(m) == 2 and m[0].distance < 0.75 * m[1].distance]
    if len(good) < 12:
        return 0, 0.0
    src = np.float32([ka[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kb[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    method = getattr(cv2, "USAC_MAGSAC", cv2.RANSAC)
    _, mask = cv2.findHomography(src, dst, method, 3.0)
    if mask is None:
        return 0, 0.0
    inl = int(mask.sum())
    floor = max(0, int(0.15 * min(len(ka), len(kb))))
    return (inl if inl >= floor else 0), inl / len(good)


def decide(sim: float, dt: float, th: Thresholds, geometric=None) -> tuple[bool, bool]:
    """Return (linked, verified_by_geometry). ``geometric`` is evaluated lazily."""
    if sim >= th.high and dt <= th.auto_link_dt:
        return True, False
    if sim < th.low or geometric is None:
        return False, False
    inliers, ratio = geometric()
    ok = inliers >= th.orb_min_inliers and ratio >= th.orb_min_ratio
    return ok, ok
