"""Fast, non-blocking image loading for the review UI.

* Thumbnails come from the scan's 512 px JPEG cache and are read with QImageReader's
  scaled decode (DCT scaling): ~1-3 ms each, on a thread pool.
* Full previews are decoded with Pillow (HEIC/RAW support) at screen size in the
  background; the view shows the thumbnail instantly and swaps in the sharp image.
* Decoded pixmaps live in a byte-bounded LRU. Stale requests are skipped.
"""

from __future__ import annotations

import os
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage, QImageReader, QPixmap


class _Emitter(QObject):
    done = Signal(str, QImage)


def pil_to_qimage(im) -> QImage:
    im = im.convert("RGB")
    data = im.tobytes("raw", "RGB")
    q = QImage(data, im.width, im.height, im.width * 3, QImage.Format_RGB888)
    return q.copy()          # detach from the Python buffer


def decode_full(path: Path, max_side: int) -> QImage:
    from PIL import Image, ImageOps

    from ..core.assets import is_raw
    from ..core.decode import decode, pillow_heif  # noqa: F401  (registers HEIC)

    if is_raw(path):
        return pil_to_qimage(decode(path, 0.0, max_side).image)
    with Image.open(path) as im:
        if im.format == "JPEG":
            im.draft("RGB", (max_side, max_side))
        im.load()
        im = ImageOps.exif_transpose(im) or im
        im = im.convert("RGB")
        if max(im.size) > max_side:
            im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        return pil_to_qimage(im)


def read_scaled(path: Path, size: int) -> QImage:
    r = QImageReader(str(path))
    r.setAutoTransform(True)
    s = r.size()
    if s.isValid() and max(s.width(), s.height()) > size:
        s.scale(QSize(size, size), Qt.KeepAspectRatio)
        r.setScaledSize(s)
    img = r.read()
    return img


class _Job(QRunnable):
    def __init__(self, loader: ImageLoader, key: str, path: Path, fallback: Path | None,
                 size: int, full: bool, gen: int):
        super().__init__()
        self.loader, self.key, self.path, self.fallback = loader, key, path, fallback
        self.size, self.full, self.gen = size, full, gen
        self.setAutoDelete(True)

    def run(self) -> None:
        if not self.full and self.gen < self.loader.min_gen:
            self.loader._drop(self.key)
            return
        img = QImage()
        try:
            if self.full:
                img = decode_full(self.path, self.size)
            else:
                if self.path and self.path.exists():
                    img = read_scaled(self.path, self.size)
                if img.isNull() and self.fallback is not None:
                    img = decode_full(self.fallback, self.size)
        except Exception:
            img = QImage()
        try:
            self.loader._emitter.done.emit(self.key, img)
        except RuntimeError:    # loader deleted while we worked
            pass


class ImageLoader(QObject):
    loaded = Signal(str)                 # key

    def __init__(self, budget_mb: int = 400, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(max(2, (os.cpu_count() or 4) // 2))
        self.full_pool = QThreadPool(self)
        self.full_pool.setMaxThreadCount(2)
        self.cache: OrderedDict[str, QPixmap] = OrderedDict()
        self.bytes = 0
        self.budget = budget_mb * 1024 * 1024
        self.pending: set[str] = set()
        self.failed: set[str] = set()
        self.gen = 0
        self.min_gen = 0
        self._emitter = _Emitter()
        self._emitter.done.connect(self._on_done)

    @staticmethod
    def key(path: Path | str, size: int, full: bool = False) -> str:
        return f"{'F' if full else 'T'}{size}|{path}"

    def bump(self) -> None:
        """Invalidate queued thumbnail requests (e.g. after jumping to another group)."""
        self.gen += 1
        self.min_gen = self.gen

    def get(self, thumb: Path | None, original: Path, size: int, full: bool = False,
            priority: int = 0) -> QPixmap | None:
        src = original if full else (thumb or original)
        k = self.key(src, size, full)
        pm = self.cache.get(k)
        if pm is not None:
            self.cache.move_to_end(k)
            return pm
        if k in self.pending or k in self.failed:
            return None
        self.pending.add(k)
        job = _Job(self, k, original if full else thumb, original, size, full, self.gen)
        (self.full_pool if full else self.pool).start(job, priority)
        return None

    def peek(self, thumb: Path | None, original: Path, size: int, full: bool = False):
        k = self.key(original if full else (thumb or original), size, full)
        return self.cache.get(k)

    def _drop(self, key: str) -> None:
        self.pending.discard(key)

    def _on_done(self, key: str, img: QImage) -> None:
        self.pending.discard(key)
        if img.isNull():
            self.failed.add(key)
            self.loaded.emit(key)
            return
        pm = QPixmap.fromImage(img)
        self.cache[key] = pm
        self.bytes += pm.width() * pm.height() * 4
        while self.bytes > self.budget and len(self.cache) > 1:
            _, old = self.cache.popitem(last=False)
            self.bytes -= old.width() * old.height() * 4
        self.loaded.emit(key)

    def clear(self) -> None:
        self.cache.clear()
        self.failed.clear()
        self.bytes = 0
