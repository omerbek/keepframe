"""Stage 2: capture metadata.

Times are stored as *wall-clock* seconds (the naive local time read as if it were UTC),
so an original with an OffsetTime tag and an exported copy without one still line up,
and DST / the PC's timezone never shift them.

Fallback order for the capture time (``time_source``):
  exif      DateTimeOriginal / DateTimeDigitized (+ SubSec)
  name      a date-time in the file name (IMG20251129104752, PXL_20251129_104752123, ...)
  name_day  a date only (IMG-20251129-WA0003)  -> low confidence
  mtime     file modified time                 -> low confidence
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

TAG_MAKE = 271
TAG_MODEL = 272
TAG_SOFTWARE = 305
TAG_ORIENTATION = 274
TAG_RATING = 18246
IFD_EXIF = 0x8769
TAG_DT_ORIGINAL = 36867
TAG_DT_DIGITIZED = 36868
TAG_SUBSEC_ORIGINAL = 37521
TAG_BODY_SERIAL = 42033

HIGH_CONFIDENCE = {"exif", "name"}

_NAME_DT = [
    # IMG20251129104752, IMG_20251129_104752, PXL_20251129_104752123, VID_..., Screenshot_...
    re.compile(r"(?:^|[^0-9])(20\d{2})(\d{2})(\d{2})[_-]?(\d{2})(\d{2})(\d{2})(\d{0,3})"),
    # 2025-11-29 10.47.52 / 2025-11-29_10-47-52
    re.compile(r"(20\d{2})-(\d{2})-(\d{2})[ _T](\d{2})[.\-:](\d{2})[.\-:](\d{2})()"),
]
_NAME_DAY = re.compile(r"(?:IMG|VID|PTT|AUD)-(20\d{2})(\d{2})(\d{2})-WA\d+", re.I)
_SCREENSHOT = re.compile(r"screenshot|screen[_ ]?shot|ekran[_ ]?g[oö]r[uü]nt|scrnli|screen_recording",
                         re.I)


@dataclass
class Meta:
    taken_at: float | None = None
    time_source: str = ""
    camera: str = ""
    serial: str = ""
    burst_id: str = ""
    width: int = 0
    height: int = 0
    rating: int = 0
    software: str = ""
    is_screenshot: bool = False


def _wall(dt: datetime) -> float:
    return dt.replace(tzinfo=timezone.utc).timestamp()


def _parse_exif_time(dt, subsec) -> float | None:
    if not dt:
        return None
    try:
        t = datetime.strptime(str(dt).strip().rstrip("\x00")[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    if t.year < 1990:
        return None
    ts = _wall(t)
    digits = "".join(c for c in str(subsec or "") if c.isdigit())
    if digits:
        ts += int(digits) / (10 ** len(digits))
    return ts


def time_from_name(name: str) -> tuple[float | None, str]:
    for rx in _NAME_DT:
        m = rx.search(name)
        if m:
            y, mo, d, h, mi, s, ms = m.groups()
            try:
                t = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s))
            except ValueError:
                continue
            ts = _wall(t)
            if ms:
                ts += int(ms) / (10 ** len(ms))
            return ts, "name"
    m = _NAME_DAY.search(name)
    if m:
        try:
            return _wall(datetime(*map(int, m.groups()))), "name_day"
        except ValueError:
            pass
    return None, ""


def from_image(im: Image.Image, path: Path, mtime: float) -> Meta:
    """Read metadata from an already opened image (the file is opened only once)."""
    m = Meta()
    m.width, m.height = im.size
    try:
        exif = im.getexif()
    except Exception:
        exif = {}
    try:
        sub = exif.get_ifd(IFD_EXIF) if exif else {}
    except Exception:
        sub = {}
    m.taken_at = _parse_exif_time(sub.get(TAG_DT_ORIGINAL), sub.get(TAG_SUBSEC_ORIGINAL))
    if m.taken_at is None:
        m.taken_at = _parse_exif_time(sub.get(TAG_DT_DIGITIZED), None)
    if m.taken_at is not None:
        m.time_source = "exif"
    make = str(exif.get(TAG_MAKE, "") or "").strip("\x00 ")
    model = str(exif.get(TAG_MODEL, "") or "").strip("\x00 ")
    m.camera = f"{make} {model}".strip()
    m.serial = str(sub.get(TAG_BODY_SERIAL, "") or "").strip("\x00 ")
    m.software = str(exif.get(TAG_SOFTWARE, "") or "").strip("\x00 ")
    try:
        m.rating = int(exif.get(TAG_RATING, 0) or 0)
    except (TypeError, ValueError):
        m.rating = 0
    if exif.get(TAG_ORIENTATION) in (5, 6, 7, 8):
        m.width, m.height = m.height, m.width

    if m.taken_at is None:
        m.taken_at, m.time_source = time_from_name(path.name)
    if m.taken_at is None:
        m.taken_at, m.time_source = mtime, "mtime"
    m.is_screenshot = bool(_SCREENSHOT.search(path.name)) or (
        path.suffix.lower() == ".png" and not m.camera)
    return m
