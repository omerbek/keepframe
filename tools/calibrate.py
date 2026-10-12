"""Calibrate similarity thresholds from labeled pairs.

Input CSV (semicolon separated): path_a;path_b;label   (label: 1 = same shot, 0 = different)
Prints precision/recall for a sweep of cosine thresholds and suggests ``high`` and ``low``:
  * high = lowest threshold with precision >= 0.99  (auto-link)
  * low  = threshold keeping recall >= 0.97          (send to ORB check)

    python tools/calibrate.py pairs.csv
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from keepframe.core.decode import load_proxy  # noqa: E402
from keepframe.core.features.embedder import Embedder  # noqa: E402


def main(path: str) -> None:
    rows = list(csv.reader(open(path, encoding="utf-8-sig"), delimiter=";"))
    model = Embedder()
    cache: dict[str, np.ndarray] = {}

    def vec(p: str) -> np.ndarray:
        if p not in cache:
            cache[p] = model.embed([load_proxy(Path(p))])[0].astype(np.float32)
        return cache[p]

    sims = np.array([vec(a) @ vec(b) for a, b, _ in rows])
    labels = np.array([int(lab) for *_, lab in rows])

    print(f"{'thr':>6} {'prec':>6} {'recall':>6}")
    high = low = None
    for t in np.arange(0.70, 0.995, 0.01):
        pred = sims >= t
        tp = int((pred & (labels == 1)).sum())
        prec = tp / max(int(pred.sum()), 1)
        rec = tp / max(int((labels == 1).sum()), 1)
        print(f"{t:6.2f} {prec:6.3f} {rec:6.3f}")
        if high is None and prec >= 0.99:
            high = t
        if rec >= 0.97:
            low = t
    print(f"\nSuggested: high={high} low={low}")


if __name__ == "__main__":
    main(sys.argv[1])
