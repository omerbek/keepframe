"""czkawka-style file tools. All are read-only: they only *find* things.

Every tool returns a ``ToolResult``: a list of groups of ``Item``. Tools whose results
are independent (big files, empty files, ...) return one item per group; duplicate
files return real groups where at least one member must always be kept.
"""

from __future__ import annotations

import os
import threading
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import discovery
from .discovery import ScanScope
from .features.hashes import PARTIAL, file_hash

Progress = Callable[[str, int, int], None]


@dataclass
class Item:
    path: Path
    size: int = 0
    mtime: float = 0.0
    info: str = ""                 # e.g. "real type: png" or an error message
    is_dir: bool = False


@dataclass
class ToolResult:
    tool: str
    groups: list[list[Item]] = field(default_factory=list)
    keep_one: bool = False         # duplicate-style groups: never check every member
    errors: int = 0

    @property
    def items(self) -> list[Item]:
        return [i for g in self.groups for i in g]


def _files(scope: ScanScope, cancel, progress, stats=None) -> list[discovery.FileEntry]:
    out = []
    for fe in discovery.walk(scope, stats=stats, cancel=cancel):
        out.append(fe)
        if len(out) % 200 == 0 and progress:
            progress("discover", len(out), 0)
    return out


# --- duplicate files -----------------------------------------------------------------
def duplicate_files(scope: ScanScope, cancel=None, progress: Progress | None = None,
                    workers: int = 8) -> ToolResult:
    cancel = cancel or threading.Event()
    files = [f for f in _files(scope, cancel, progress) if f.size > 0]
    by_size: dict[int, list] = defaultdict(list)
    for f in files:
        by_size[f.size].append(f)
    cand = [f for v in by_size.values() if len(v) > 1 for f in v]
    res = ToolResult("duplicates", keep_one=True)

    def stage(items, limit, key_name):
        out: dict[tuple, list] = defaultdict(list)
        with ThreadPoolExecutor(workers) as ex:
            futs = []
            for s in range(0, len(items), 256):
                if cancel.is_set():
                    return {}
                futs = [(f, ex.submit(_safe_hash, f.path, limit)) for f in items[s : s + 256]]
                for f, fu in futs:
                    h = fu.result()
                    if h is None:
                        res.errors += 1
                        continue
                    out[(f.size, h)].append(f)
                if progress:
                    progress(key_name, min(s + 256, len(items)), len(items))
        return out

    pre = stage(cand, PARTIAL, "prehash")
    small_done = [v for (sz, _), v in pre.items() if len(v) > 1 and sz <= PARTIAL]
    need_full = [f for (sz, _), v in pre.items() if len(v) > 1 and sz > PARTIAL for f in v]
    full = stage(need_full, 0, "hash")
    groups = small_done + [v for v in full.values() if len(v) > 1]
    res.groups = [[Item(f.path, f.size, f.mtime) for f in sorted(g, key=lambda f: str(f.path))]
                  for g in sorted(groups, key=lambda g: -g[0].size * (len(g) - 1))]
    return res


def _safe_hash(p: Path, limit: int):
    try:
        return file_hash(p, limit=limit)
    except OSError:
        return None


# --- big / empty / temporary --------------------------------------------------------
def big_files(scope: ScanScope, cancel=None, progress=None, count: int = 200) -> ToolResult:
    files = _files(scope, cancel, progress)
    files.sort(key=lambda f: -f.size)
    return ToolResult("big", [[Item(f.path, f.size, f.mtime)] for f in files[:count]])


def empty_files(scope: ScanScope, cancel=None, progress=None) -> ToolResult:
    s = ScanScope(**{**scope.__dict__, "min_size": 0, "max_size": 0})
    files = [f for f in _files(s, cancel, progress) if f.size == 0]
    return ToolResult("empty_files", [[Item(f.path, 0, f.mtime)] for f in files])


TEMP_PATTERNS = ("*.tmp", "*.temp", "~$*", "~*.tmp", "*.~*", "*.bak", "*.old", "*.part",
                 "*.crdownload", "*.download", "thumbs.db", "ehthumbs.db", "ehthumbs_vista.db",
                 ".ds_store", "._*", "desktop.ini.bak", "*.dmp")


def temporary_files(scope: ScanScope, cancel=None, progress=None) -> ToolResult:
    import fnmatch

    s = ScanScope(**{**scope.__dict__, "extensions": None, "min_size": 0, "skip_hidden": False})
    out = []
    for f in _files(s, cancel, progress):
        n = f.path.name.lower()
        if any(fnmatch.fnmatch(n, p) for p in TEMP_PATTERNS):
            out.append([Item(f.path, f.size, f.mtime)])
    return ToolResult("temp", out)


def empty_folders(scope: ScanScope, cancel=None, progress=None) -> ToolResult:
    """Folders whose whole subtree contains no files (deepest first)."""
    s = ScanScope(**{**scope.__dict__, "extensions": None, "min_size": 0, "skip_hidden": False})
    has_files: set[str] = set()
    dirs: list[Path] = []
    for fe in discovery.walk(s, cancel=cancel, dirs_out=dirs):
        p = os.path.normcase(str(fe.path.parent))
        while p and p not in has_files:
            has_files.add(p)
            parent = os.path.dirname(p)
            if parent == p:
                break
            p = parent
    roots = {os.path.normcase(str(r)) for r in discovery.normalize_roots(scope.roots)}
    out = []
    for d in sorted(dirs, key=lambda d: -len(str(d))):
        k = os.path.normcase(str(d))
        if k in roots or k in has_files:
            continue
        try:
            if any(e.is_file() for e in os.scandir(d)):   # hidden/system files count too
                continue
        except OSError:
            continue
        out.append([Item(d, 0, d.stat().st_mtime if d.exists() else 0, is_dir=True)])
    return ToolResult("empty_folders", out)


# --- broken images / wrong extensions -------------------------------------------------
SIGNATURES = [
    (b"\xff\xd8\xff", ".jpg"), (b"\x89PNG\r\n\x1a\n", ".png"), (b"GIF8", ".gif"),
    (b"BM", ".bmp"), (b"II*\x00", ".tif"), (b"MM\x00*", ".tif"), (b"RIFF", ".webp"),
]
EQUIV = {".jpeg": ".jpg", ".jpe": ".jpg", ".tiff": ".tif", ".heif": ".heic"}
RAWLIKE_TIFF = {".dng", ".nef", ".cr2", ".arw", ".orf", ".pef", ".srw", ".nrw", ".rw2"}


def sniff(path: Path) -> str | None:
    try:
        with open(path, "rb") as f:
            head = f.read(32)
    except OSError:
        return None
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"heic", b"heix", b"hevc", b"heim", b"heis", b"mif1", b"msf1"):
            return ".heic"
        if brand in (b"avif", b"avis"):
            return ".avif"
        if brand.startswith(b"qt"):
            return ".mov"
        return ".mp4"
    for sig, ext in SIGNATURES:
        if head.startswith(sig):
            if ext == ".webp" and head[8:12] != b"WEBP":
                return None
            return ext
    return None


def wrong_extensions(scope: ScanScope, cancel=None, progress=None) -> ToolResult:
    s = ScanScope(**{**scope.__dict__, "extensions": discovery.IMAGE_EXT | discovery.RAW_EXT})
    out = []
    files = _files(s, cancel, progress)
    for n, f in enumerate(files, 1):
        if cancel is not None and cancel.is_set():
            break
        real = sniff(f.path)
        ext = EQUIV.get(f.path.suffix.lower(), f.path.suffix.lower())
        if real is None or real == ext:
            continue
        if real == ".tif" and ext in RAWLIKE_TIFF:
            continue
        if real == ".mp4" and ext == ".heic":
            continue
        out.append([Item(f.path, f.size, f.mtime, info=real)])
        if progress and n % 200 == 0:
            progress("check", n, len(files))
    return ToolResult("bad_ext", out)


def broken_images(scope: ScanScope, cancel=None, progress=None, workers: int = 8) -> ToolResult:
    from PIL import Image

    from .decode import pillow_heif  # noqa: F401  (registers HEIC)

    s = ScanScope(**{**scope.__dict__, "extensions": discovery.IMAGE_EXT})
    files = _files(s, cancel, progress)

    def check(f):
        try:
            with Image.open(f.path) as im:
                im.verify()
            with Image.open(f.path) as im:      # verify() misses truncated data
                im.draft("RGB", (64, 64)) if im.format == "JPEG" else None
                im.load()
            return None
        except Exception as e:
            return f"{type(e).__name__}: {e}"[:200]

    out = []
    with ThreadPoolExecutor(workers) as ex:
        for st in range(0, len(files), 256):
            if cancel is not None and cancel.is_set():
                break
            chunk = files[st : st + 256]
            for f, err in zip(chunk, ex.map(check, chunk), strict=False):
                if err:
                    out.append([Item(f.path, f.size, f.mtime, info=err)])
            if progress:
                progress("check", min(st + 256, len(files)), len(files))
    return ToolResult("broken", out)


TOOLS: dict[str, Callable[..., ToolResult]] = {
    "duplicates": duplicate_files,
    "big": big_files,
    "empty_files": empty_files,
    "empty_folders": empty_folders,
    "temp": temporary_files,
    "broken": broken_images,
    "bad_ext": wrong_extensions,
}
