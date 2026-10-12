"""Merge technical file sets into one logical photo (asset).

Rules (same folder, same stem, case-insensitive):
  * RAW + JPG/HEIC       -> one asset, primary = JPG/HEIC (fast to decode)
  * HEIC/JPG + MOV       -> Live Photo, primary = still image
  * any + .xmp           -> sidecar companion
A lone RAW becomes its own asset (primary = RAW, preview via embedded thumbnail).
A lone video is ignored (v1 does not handle videos).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

from .discovery import IMAGE_EXT, RAW_EXT, SIDECAR_EXT, VIDEO_COMPANION_EXT
from .types import FileEntry


def group_files(entries: Iterable[FileEntry]) -> list[tuple[FileEntry, list[FileEntry]]]:
    """Return ``(primary, companions)`` tuples."""
    buckets: dict[tuple[str, str], list[FileEntry]] = defaultdict(list)
    for fe in entries:
        key = (str(fe.path.parent).lower(), fe.path.stem.lower())
        buckets[key].append(fe)

    out: list[tuple[FileEntry, list[FileEntry]]] = []
    for files in buckets.values():
        def ext(f: FileEntry) -> str:
            return f.path.suffix.lower()

        stills = [f for f in files if ext(f) in IMAGE_EXT]
        raws = [f for f in files if ext(f) in RAW_EXT]
        anchor = (stills or raws or files)[0].mtime
        # .mov = Live Photo half. Other videos only when written within 3 s of the
        # still (Android motion photos); an unrelated clip with the same name stays out.
        others = [f for f in files if ext(f) in SIDECAR_EXT or ext(f) == ".mov"
                  or (ext(f) in VIDEO_COMPANION_EXT and abs(f.mtime - anchor) <= 3)]

        if stills:
            # Two different stills with the same stem (photo.jpg + photo.png) are NOT merged.
            primary, *extra_stills = sorted(stills, key=lambda f: f.path.suffix.lower())
            out.append((primary, raws + others))
            for s in extra_stills:
                out.append((s, []))
        elif raws:
            primary, *extra = raws
            out.append((primary, extra + others))
        # videos / sidecars without a still are skipped
    return out


def is_raw(path: Path) -> bool:
    return path.suffix.lower() in RAW_EXT
