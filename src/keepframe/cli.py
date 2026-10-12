"""Command-line interface (read-only: it reports, it never moves files).

    keepframe-cli scan  D:\\Photos [E:\\More] [--csv out.csv] [--strictness 0.5] [--no-ai]
    keepframe-cli tool  duplicates|big|empty_files|empty_folders|temp|broken|bad_ext  D:\\Photos
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from .core import pipeline, tools
from .core.discovery import ScanScope


def _progress(stage: str, done: int, total: int) -> None:
    if total:
        print(f"\r{stage:<10} {done}/{total}   ", end="", file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="keepframe-cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="find similar / duplicate photos")
    s.add_argument("roots", nargs="+", type=Path)
    s.add_argument("--csv", type=Path)
    s.add_argument("--strictness", type=float, default=0.5)
    s.add_argument("--max-dt", type=float, default=20.0, help="seconds between similar shots")
    s.add_argument("--no-ai", action="store_true")
    s.add_argument("--cpu", action="store_true")
    tl = sub.add_parser("tool", help="run a file tool")
    tl.add_argument("name", choices=sorted(tools.TOOLS))
    tl.add_argument("roots", nargs="+", type=Path)
    tl.add_argument("--csv", type=Path)
    a = p.parse_args(argv)

    rows: list[list] = []
    if a.cmd == "scan":
        res = pipeline.run(pipeline.ScanOptions(roots=a.roots, strictness=a.strictness,
                                                max_dt=a.max_dt, use_ai=not a.no_ai,
                                                device="cpu" if a.cpu else "auto"), _progress)
        print(f"\n{res.stats.photos} photos · {len(res.groups)} groups · {res.device} · "
              f"{res.stats.seconds:.1f}s", file=sys.stderr)
        header = ["group", "kind", "suggested", "score", "similarity", "reasons", "path"]
        for gi, g in enumerate(res.groups, 1):
            for m in sorted(g.members, key=lambda m: -m.score):
                rows.append([gi, g.kind.value, int(m.suggested), f"{m.score:.3f}",
                             f"{m.similarity:.3f}", ",".join(m.reasons),
                             str(res.assets[m.asset_id].primary)])
    else:
        r = tools.TOOLS[a.name](ScanScope(roots=a.roots, extensions=None), None, _progress)
        print(f"\n{len(r.items)} items", file=sys.stderr)
        header = ["group", "path", "size", "info"]
        for gi, g in enumerate(r.groups, 1):
            for it in g:
                rows.append([gi, str(it.path), it.size, it.info])
    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(header)
            w.writerows(rows)
    else:
        for r_ in rows:
            print("\t".join(map(str, r_)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
