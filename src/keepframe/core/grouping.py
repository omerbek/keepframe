"""Stage 7: build groups from verified edges, with an anti-chaining guard.

Plain union-find chains A≈B≈C≈D into one group even when A and D look nothing alike
(e.g. a slow pan). We merge strongest edges first and only join two clusters when the
*average* similarity between them stays above ``min_mean`` AND no cross pair falls
below ``min_pair``. Pairs confirmed by geometry count as ``min_mean``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable


def build_groups(
    edges: Iterable[tuple[int, int, float]],
    similarity: Callable[[int, int], float],
    min_mean: float = 0.85,
    min_pair: float = 0.0,
    verified: set[tuple[int, int]] | None = None,
    max_cross: int = 64,
) -> list[list[int]]:
    verified = verified or set()
    cluster: dict[int, int] = {}
    members: dict[int, list[int]] = {}

    def find(x: int) -> int:
        if x not in cluster:
            cluster[x] = x
            members[x] = [x]
        return cluster[x]

    def sim(x: int, y: int) -> float:
        if (min(x, y), max(x, y)) in verified:
            return max(similarity(x, y), min_mean)
        return similarity(x, y)

    for a, b, _ in sorted(edges, key=lambda e: e[2], reverse=True):
        ca, cb = find(a), find(b)
        if ca == cb:
            continue
        ma, mb = members[ca], members[cb]
        if len(ma) > 1 or len(mb) > 1:
            xs, ys = ma[:max_cross], mb[:max_cross]
            vals = [sim(x, y) for x in xs for y in ys]
            if sum(vals) / len(vals) < min_mean or min(vals) < min_pair:
                continue
        if len(ma) < len(mb):
            ca, cb, ma, mb = cb, ca, mb, ma
        for x in mb:
            cluster[x] = ca
        ma.extend(mb)
        del members[cb]

    groups = [sorted(m) for m in members.values() if len(m) > 1]
    groups.sort(key=len, reverse=True)
    return groups


def split_large(group: list[int], times: dict[int, float | None], max_size: int = 40,
                gap: float = 5.0) -> list[list[int]]:
    """Split oversized groups into time-contiguous runs."""
    if len(group) <= max_size:
        return [group]
    ordered = sorted(group, key=lambda i: times.get(i) or 0.0)
    runs, cur = [], [ordered[0]]
    for prev, x in zip(ordered, ordered[1:], strict=False):
        if (times.get(x) or 0) - (times.get(prev) or 0) > gap or len(cur) >= max_size:
            runs.append(cur)
            cur = []
        cur.append(x)
    runs.append(cur)
    return [r for r in runs if len(r) > 1]
