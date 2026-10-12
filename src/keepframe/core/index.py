"""Vector index for the optional cross-session "same photo on different days" pass.

Uses usearch (HNSW) when installed, otherwise an exact blocked matrix product.
"""

from __future__ import annotations

import numpy as np


def knn_pairs(ids: np.ndarray, emb: np.ndarray, k: int = 10,
              min_sim: float = 0.95) -> list[tuple[int, int, float]]:
    """Return (a, b, cosine) for neighbours with similarity >= min_sim (a < b)."""
    emb = emb.astype(np.float32)
    out: dict[tuple[int, int], float] = {}
    try:
        from usearch.index import Index

        idx = Index(ndim=emb.shape[1], metric="cos", dtype="f16")
        idx.add(ids, emb)
        res = idx.search(emb, k + 1)
        for qi, row_keys, row_d in zip(ids, res.keys, res.distances, strict=False):
            for key, d in zip(row_keys, row_d, strict=False):
                sim = 1.0 - float(d)
                if key != qi and sim >= min_sim:
                    a, b = sorted((int(qi), int(key)))
                    out[(a, b)] = sim
    except ImportError:
        block = 2048
        for s in range(0, len(emb), block):
            sims = emb[s : s + block] @ emb.T
            for r, row in enumerate(sims):
                qi = int(ids[s + r])
                for j in np.argpartition(-row, min(k + 1, len(row) - 1))[: k + 1]:
                    if j != s + r and row[j] >= min_sim:
                        a, b = sorted((qi, int(ids[j])))
                        out[(a, b)] = float(row[j])
    return [(a, b, s) for (a, b), s in out.items()]
