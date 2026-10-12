"""Stage 1: walk folders and list files (safe against overlapping roots and hardlinks)."""

from __future__ import annotations

import fnmatch
import os
import threading
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .types import FileEntry

IMAGE_EXT = {
    ".jpg", ".jpeg", ".jpe", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff", ".bmp",
    ".avif", ".gif",
}
RAW_EXT = {
    ".cr2", ".cr3", ".nef", ".nrw", ".arw", ".dng", ".orf", ".rw2", ".raf", ".pef", ".srw",
}
VIDEO_COMPANION_EXT = {".mov", ".mp4"}   # Live Photo halves
SIDECAR_EXT = {".xmp"}
PHOTO_EXT = IMAGE_EXT | RAW_EXT | VIDEO_COMPANION_EXT | SIDECAR_EXT

SKIP_DIRS = {"$recycle.bin", "system volume information", "_keepframe_quarantine",
             ".thumbnails", "$windows.~bt", "$windows.~ws"}

# Windows file attributes (os.stat_result.st_file_attributes)
FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
FILE_ATTRIBUTE_OFFLINE = 0x1000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x40000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x400000
CLOUD_ONLY = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | \
    FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS


@dataclass
class ScanScope:
    roots: list[Path]
    excluded: list[str] = field(default_factory=list)   # wildcards on folder name or full path
    extensions: set[str] | None = None                  # None = every file
    min_size: int = 0
    max_size: int = 0                                    # 0 = no limit
    recursive: bool = True
    skip_hidden: bool = True
    include_cloud_only: bool = False                     # OneDrive placeholders


@dataclass
class WalkStats:
    files: int = 0
    skipped_cloud: int = 0
    skipped_dupe_path: int = 0
    errors: int = 0


def norm(p: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(p)))


def normalize_roots(roots: Iterable[str | Path]) -> list[Path]:
    """Resolve, de-duplicate and drop roots that live inside another root."""
    out: list[str] = []
    for r in sorted({norm(os.path.realpath(str(r))) for r in roots}, key=len):
        if not any(r == o or r.startswith(o.rstrip("\\/") + os.sep) for o in out):
            out.append(r)
    return [Path(r) for r in out]


def _excluded(name: str, full: str, patterns: list[str]) -> bool:
    low, lowfull = name.lower(), full.lower().replace("\\", "/")
    for pat in patterns:
        p = pat.lower().replace("\\", "/")
        if fnmatch.fnmatch(low, p) or fnmatch.fnmatch(lowfull, p):
            return True
    return False


def walk(scope: ScanScope | Iterable[str | Path], excluded: Iterable[str] = (),
         stats: WalkStats | None = None, cancel: threading.Event | None = None,
         dirs_out: list[Path] | None = None) -> Iterator[FileEntry]:
    """Yield every matching file under the scope's roots, each physical file once."""
    if not isinstance(scope, ScanScope):
        scope = ScanScope(roots=[Path(r) for r in scope], excluded=list(excluded),
                          extensions=PHOTO_EXT)
    stats = stats or WalkStats()
    seen: set[tuple[int, int]] = set()
    seen_paths: set[str] = set()
    stack = list(reversed(normalize_roots(scope.roots)))
    while stack:
        if cancel is not None and cancel.is_set():
            return
        d = stack.pop()
        if dirs_out is not None:
            dirs_out.append(d)
        try:
            it = os.scandir(d)
        except OSError:
            stats.errors += 1
            continue
        with it:
            subdirs = []
            for n_, e in enumerate(it):
                if n_ % 256 == 255 and cancel is not None and cancel.is_set():
                    return
                try:
                    attrs = 0
                    st = e.stat(follow_symlinks=False)
                    attrs = getattr(st, "st_file_attributes", 0)
                    if e.is_dir(follow_symlinks=False):
                        name = e.name.lower()
                        if (name in SKIP_DIRS or name.startswith(".")
                                or attrs & FILE_ATTRIBUTE_REPARSE_POINT
                                or (scope.skip_hidden and attrs & FILE_ATTRIBUTE_HIDDEN)
                                or _excluded(e.name, e.path, scope.excluded)):
                            continue
                        if scope.recursive:
                            subdirs.append(Path(e.path))
                        continue
                    if not e.is_file(follow_symlinks=False):
                        continue
                    ext = os.path.splitext(e.name)[1].lower()
                    if scope.extensions is not None and ext not in scope.extensions:
                        continue
                    if scope.skip_hidden and attrs & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM):
                        continue
                    if _excluded(e.name, e.path, scope.excluded):
                        continue
                    if attrs & CLOUD_ONLY and not scope.include_cloud_only:
                        stats.skipped_cloud += 1
                        continue
                    size = st.st_size
                    if size < scope.min_size or (scope.max_size and size > scope.max_size):
                        continue
                    key = (st.st_dev, st.st_ino)
                    np_ = norm(e.path)
                    if (st.st_ino and key in seen) or np_ in seen_paths:
                        stats.skipped_dupe_path += 1
                        continue
                    if st.st_ino:
                        seen.add(key)
                    seen_paths.add(np_)
                    stats.files += 1
                    yield FileEntry(Path(e.path), size, st.st_mtime_ns / 1e9)
                except OSError:
                    stats.errors += 1
            stack.extend(reversed(sorted(subdirs)))
