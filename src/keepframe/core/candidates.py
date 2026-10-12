"""Stage 5: candidate pairs without O(n²) all-pairs comparison.

Sources:
  1. Time window: same camera, high-confidence capture time, Δt <= max_dt.
  2. Cross-device: any camera, Δt <= cross_dt (family phones shooting the same moment).
  3. Near-copies across the whole library: dHash multi-index buckets (re-encoded,
     resized, WhatsApp copies with stripped EXIF).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from .metadata import HIGH_CONFIDENCE
from .types import Asset

MAX_DT = 20.0
NEIGHBORS = 40
CROSS_DT = 10.0
NEAR_COPY_BITS = 4
MAX_BUCKET = 400          # ignore degenerate hash buckets (flat images)


def _timed(assets: Iterable[Asset], use_low_confidence: bool) -> list[Asset]:
    ok = HIGH_CONFIDENCE | ({"name_day", "mtime"} if use_low_confidence else set())
    return [a for a in assets if a.taken_at is not None and a.time_source in ok]


def time_pairs(assets: list[Asset], max_dt: float = MAX_DT, k: int = NEIGHBORS,
               same_camera: bool = True) -> Iterable[tuple[int, int]]:
    by_cam: dict[str, list[Asset]] = defaultdict(list)
    for a in assets:
        by_cam[a.camera if same_camera else ""].append(a)
    for items in by_cam.values():
        items.sort(key=lambda a: a.taken_at)
        for i, a in enumerate(items):
            for b in items[i + 1 : i + 1 + k]:
                if b.taken_at - a.taken_at > max_dt:
                    break
                yield a.id, b.id


def sessions(assets: Iterable[Asset], gap: float = 60.0) -> list[list[Asset]]:
    """Split assets into capture sessions per camera (used for stats / UI)."""
    by_cam: dict[str, list[Asset]] = defaultdict(list)
    for a in assets:
        if a.taken_at is not None:
            by_cam[a.camera].append(a)
    out: list[list[Asset]] = []
    for items in by_cam.values():
        items.sort(key=lambda a: a.taken_at)
        cur: list[Asset] = []
        for a in items:
            if cur and a.taken_at - cur[-1].taken_at > gap:
                out.append(cur)
                cur = []
            cur.append(a)
        if cur:
            out.append(cur)
    return [s for s in out if len(s) > 1]


def near_copy_pairs(hashes: dict[int, int], bits: int = NEAR_COPY_BITS) -> set[tuple[int, int]]:
    """Pairs whose 64-bit dHash differ by <= ``bits``.

    Multi-index hashing: split into bits+1 bands; two hashes within ``bits`` share at
    least one identical band (pigeonhole), so only bucket-mates are compared.
    """
    nb = bits + 1
    width = 64 // nb
    buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
    for aid, h in hashes.items():
        for b in range(nb):
            shift = b * width
            w = width if b < nb - 1 else 64 - shift
            buckets[(b, (h >> shift) & ((1 << w) - 1))].append(aid)
    out: set[tuple[int, int]] = set()
    for ids in buckets.values():
        if len(ids) < 2 or len(ids) > MAX_BUCKET:
            continue
        for i, x in enumerate(ids):
            hx = hashes[x]
            for y in ids[i + 1 :]:
                if (hx ^ hashes[y]).bit_count() <= bits:
                    out.add((min(x, y), max(x, y)))
    return out


def candidate_pairs(assets: list[Asset], max_dt: float = MAX_DT, cross_device: bool = True,
                    use_low_confidence: bool = False,
                    include_screenshots: bool = False) -> set[tuple[int, int]]:
    pool = [a for a in assets if include_screenshots or not a.is_screenshot]
    timed = _timed(pool, use_low_confidence)
    pairs: set[tuple[int, int]] = set()
    for x, y in time_pairs(timed, max_dt):
        pairs.add((min(x, y), max(x, y)))
    if cross_device:
        for x, y in time_pairs(timed, CROSS_DT, k=10, same_camera=False):
            pairs.add((min(x, y), max(x, y)))
    return pairs
