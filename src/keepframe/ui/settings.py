"""User settings persisted with QSettings."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields

from PySide6.QtCore import QSettings


@dataclass
class Settings:
    language: str = ""                 # "" = follow system
    theme: str = "dark"                # dark | light | system
    roots: list[str] = field(default_factory=list)
    protected: list[str] = field(default_factory=list)
    excluded: str = "node_modules, .git, *cache*"
    strictness: float = 0.5
    max_dt: float = 20.0
    cross_device: bool = True
    near_copies: bool = True
    include_screenshots: bool = False
    use_file_dates: bool = False
    use_ai: bool = True
    device: str = "auto"
    removal: str = "recycle"           # recycle | quarantine
    min_size_kb: int = 8
    skip_hidden: bool = True
    include_cloud_only: bool = False
    workers: int = 0
    big_count: int = 200
    card_size: int = 230
    last_rule: str = "except_suggested"

    @property
    def excluded_list(self) -> list[str]:
        return [x.strip() for x in self.excluded.split(",") if x.strip()]

    @classmethod
    def load(cls) -> Settings:
        s = QSettings()
        raw = s.value("settings/json", "")
        out = cls()
        if raw:
            try:
                data = json.loads(raw)
                for f in fields(cls):
                    if f.name in data:
                        setattr(out, f.name, data[f.name])
            except (ValueError, TypeError):
                pass
        return out

    def save(self) -> None:
        QSettings().setValue("settings/json", json.dumps(asdict(self)))
