"""Stage 3: open each file ONCE, read metadata and decode a small oriented proxy."""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from . import metadata
from .assets import is_raw

try:  # HEIC / HEIF / AVIF support
    import pillow_heif

    pillow_heif.register_heif_opener()
    try:
        pillow_heif.options.DECODE_THREADS = 1   # we already decode in parallel
    except Exception:
        pass
except ImportError:  # pragma: no cover
    pillow_heif = None

PROXY_SIZE = 512


@dataclass
class Decoded:
    image: Image.Image          # RGB, oriented, longest side <= PROXY_SIZE
    meta: metadata.Meta


def _orient(im: Image.Image) -> Image.Image:
    try:
        if im.getexif().get(274, 1) not in (1, None):
            return ImageOps.exif_transpose(im) or im
    except Exception:
        pass
    return im


def _raw(path: Path, mtime: float) -> Decoded:
    import rawpy  # optional dependency

    with open(path, "rb") as fh, rawpy.imread(fh) as raw:
        im = None
        try:
            th = raw.extract_thumb()
            if th.format == rawpy.ThumbFormat.JPEG:
                im = Image.open(io.BytesIO(th.data))
                im.load()
            else:
                im = Image.fromarray(th.data)
            if max(im.size) < PROXY_SIZE:
                im = None
        except Exception:
            im = None
        if im is None:
            im = Image.fromarray(raw.postprocess(half_size=True, use_camera_wb=True))
        flip = getattr(raw.sizes, "flip", 0)
    meta = metadata.from_image(im, path, mtime)
    im = _orient(im)
    if flip in (3, 5, 6):
        im = im.rotate({3: 180, 5: 90, 6: -90}[flip], expand=True)
    im = im.convert("RGB")
    im.thumbnail((PROXY_SIZE, PROXY_SIZE), Image.Resampling.BILINEAR, reducing_gap=2.0)
    meta.width, meta.height = max(meta.width, im.width), max(meta.height, im.height)
    return Decoded(im, meta)


def decode(path: Path, mtime: float = 0.0, size: int = PROXY_SIZE) -> Decoded:
    if is_raw(path):
        return _raw(path, mtime)
    with Image.open(path) as src:
        meta = metadata.from_image(src, path, mtime)
        if src.format == "JPEG":
            src.draft("RGB", (size, size))   # libjpeg-turbo DCT scaling: 4-8x faster
        src.load()
        im = _orient(src)
        if im.mode not in ("RGB", "L"):
            if "A" in im.getbands():
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im.convert("RGBA"), mask=im.convert("RGBA").getchannel("A"))
                im = bg
            else:
                im = im.convert("RGB")
        im = im.convert("RGB")
        im.thumbnail((size, size), Image.Resampling.BILINEAR, reducing_gap=2.0)
    return Decoded(im, meta)


def load_proxy(path: Path, size: int = PROXY_SIZE) -> Image.Image:
    return decode(path, 0.0, size).image


def gray(im: Image.Image) -> np.ndarray:
    return np.asarray(im.convert("L"))
