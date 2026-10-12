"""Shared data types for the core pipeline (no Qt dependency)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class GroupKind(str, Enum):
    EXACT = "exact"          # byte-identical files
    REENCODED = "reencoded"  # same picture, different encoding / size / format
    SIMILAR = "similar"      # burst / same scene, same angle


@dataclass
class FileEntry:
    path: Path
    size: int
    mtime: float


@dataclass
class Asset:
    """One logical photo. May consist of several files (RAW+JPG, HEIC+MOV, XMP)."""

    id: int
    primary: Path
    companions: list[Path] = field(default_factory=list)
    taken_at: float | None = None      # wall-clock seconds, incl. sub-seconds
    time_source: str = ""              # exif | name | name_day | mtime
    camera: str = ""
    burst_id: str = ""
    width: int = 0
    height: int = 0
    size: int = 0
    mtime: float = 0.0
    is_favorite: bool = False
    rating: int = 0
    is_screenshot: bool = False
    is_edited: bool = False
    thumb: Path | None = None          # cached 512 px JPEG (fast preview)

    @property
    def pixels(self) -> int:
        return self.width * self.height

    @property
    def all_files(self) -> list[Path]:
        return [self.primary, *self.companions]

    @property
    def total_size(self) -> int:
        return self.size


@dataclass
class Features:
    sha256: str = ""
    dhash: int = 0
    embedding: object = None           # np.ndarray (float16, L2-normalized) or None
    sharpness: float = 0.0
    exposure_clip: float = 0.0         # fraction of clipped pixels (0..1)
    eyes_open: float | None = None     # 0..1, None = no faces
    smile: float | None = None


@dataclass
class Member:
    asset_id: int
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    suggested: bool = False            # soft "Suggested best" badge — never a decision
    similarity: float = 1.0            # similarity to the suggested photo


@dataclass
class Group:
    kind: GroupKind
    members: list[Member]

    @property
    def best(self) -> Member:
        return max(self.members, key=lambda m: m.score)

    @property
    def ids(self) -> list[int]:
        return [m.asset_id for m in self.members]
