"""Selection rules: the user decides what to remove; rules only help check boxes.

Every rule returns, for one group, the set of asset ids to CHECK (= mark for removal).
``SelectionState`` applies rules over a scope and always enforces two guards:
  * protected photos (favorites, rated, protected folders) are never checked;
  * at least one photo per group stays unchecked.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .types import Asset, Features, Group

Ctx = tuple[dict[int, Asset], dict[int, Features]]
Rule = Callable[[Group, Ctx], set[int]]


def _all_except(key: Callable[[Asset, Features | None], object], largest: bool = True) -> Rule:
    def rule(g: Group, ctx: Ctx) -> set[int]:
        assets, feats = ctx
        ids = g.ids
        keep = (max if largest else min)(ids, key=lambda i: (key(assets[i], feats.get(i)),
                                                          -ids.index(i)))
        return set(ids) - {keep}
    return rule


def except_suggested(g: Group, ctx: Ctx) -> set[int]:
    return {m.asset_id for m in g.members if not m.suggested}


RULES: dict[str, Rule] = {
    "except_suggested": except_suggested,
    "except_highest_res": _all_except(lambda a, f: (a.pixels, a.size)),
    "except_largest_file": _all_except(lambda a, f: a.size),
    "except_smallest_file": _all_except(lambda a, f: a.size, largest=False),
    "except_oldest": _all_except(lambda a, f: (a.taken_at or a.mtime), largest=False),
    "except_newest": _all_except(lambda a, f: (a.taken_at or a.mtime)),
    "except_shortest_path": _all_except(lambda a, f: len(str(a.primary)), largest=False),
    "except_sharpest": _all_except(lambda a, f: f.sharpness if f else 0.0),
}


def rule_blurrier_than(pct: float) -> Rule:
    """Check photos whose sharpness is below ``pct`` % of the sharpest in the group."""
    def rule(g: Group, ctx: Ctx) -> set[int]:
        _, feats = ctx
        s = {i: (feats[i].sharpness if i in feats else 0.0) for i in g.ids}
        top = max(s.values()) or 1.0
        return {i for i, v in s.items() if v < top * pct / 100.0}
    return rule


def rule_regex(pattern: str, invert: bool = False) -> Rule:
    rx = re.compile(pattern, re.I)

    def rule(g: Group, ctx: Ctx) -> set[int]:
        assets, _ = ctx
        hit = {i for i in g.ids if rx.search(str(assets[i].primary))}
        return set(g.ids) - hit if invert else hit
    return rule


def rule_folder_priority(folders: list[str | Path]) -> Rule:
    """Keep the photo from the highest-priority folder, check the rest."""
    norm = [os.path.normcase(os.path.abspath(str(f))).rstrip("\\/") for f in folders]

    def rank(a: Asset) -> int:
        p = os.path.normcase(str(a.primary))
        for i, f in enumerate(norm):
            if p.startswith(f + os.sep):
                return i
        return len(norm)

    def rule(g: Group, ctx: Ctx) -> set[int]:
        assets, _ = ctx
        keep = min(g.ids, key=lambda i: (rank(assets[i]), -assets[i].pixels))
        return set(g.ids) - {keep}
    return rule


def rule_prefer_format(order: list[str]) -> Rule:
    """Keep the photo whose extension comes first in ``order`` (e.g. [".heic", ".jpg"])."""
    order = [o.lower() if o.startswith(".") else "." + o.lower() for o in order]

    def rank(a: Asset) -> int:
        ext = a.primary.suffix.lower()
        ext = ".jpg" if ext == ".jpeg" else ext
        return order.index(ext) if ext in order else len(order)

    def rule(g: Group, ctx: Ctx) -> set[int]:
        assets, _ = ctx
        keep = min(g.ids, key=lambda i: (rank(assets[i]), -assets[i].pixels))
        return set(g.ids) - {keep}
    return rule


@dataclass
class ApplyReport:
    checked: int = 0
    spared_groups: int = 0       # groups where the guard kept one photo


@dataclass
class SelectionState:
    groups: list[Group]
    assets: dict[int, Asset]
    feats: dict[int, Features]
    protected_dirs: list[str] = field(default_factory=list)
    checked: set[int] = field(default_factory=set)
    reviewed: set[int] = field(default_factory=set)       # group indices
    _history: list[set[int]] = field(default_factory=list)

    # --- queries ---------------------------------------------------------
    def is_protected(self, aid: int) -> bool:
        a = self.assets[aid]
        if a.is_favorite or a.rating > 0:
            return True
        p = os.path.normcase(str(a.primary))
        return any(p.startswith(os.path.normcase(d).rstrip("\\/") + os.sep)
                   for d in self.protected_dirs)

    def group_checked(self, gi: int) -> int:
        return sum(1 for i in self.groups[gi].ids if i in self.checked)

    def summary(self) -> tuple[int, int]:
        return len(self.checked), sum(self.assets[i].size for i in self.checked)

    # --- mutations -------------------------------------------------------
    def _snapshot(self):
        self._history.append(set(self.checked))
        if len(self._history) > 50:
            self._history.pop(0)

    def undo(self) -> bool:
        if not self._history:
            return False
        self.checked = self._history.pop()
        return True

    def toggle(self, gi: int, aid: int) -> bool:
        """Toggle one photo. Returns False when refused (guard or protected)."""
        if aid in self.checked:
            self._snapshot()
            self.checked.discard(aid)
            return True
        if self.is_protected(aid):
            return False
        ids = self.groups[gi].ids
        if sum(1 for i in ids if i not in self.checked) <= 1:
            return False
        self._snapshot()
        self.checked.add(aid)
        self.reviewed.add(gi)
        return True

    def apply(self, rule: Rule | str, scope: Iterable[int], additive: bool = False) -> ApplyReport:
        rule = RULES[rule] if isinstance(rule, str) else rule
        self._snapshot()
        rep = ApplyReport()
        ctx = (self.assets, self.feats)
        for gi in scope:
            g = self.groups[gi]
            ids = g.ids
            want = {i for i in rule(g, ctx) if i in ids and not self.is_protected(i)}
            if not additive:
                self.checked.difference_update(ids)
            want |= {i for i in ids if i in self.checked}
            if len(want) >= len(ids):          # guard: keep the suggested / best one
                keep = max(g.members, key=lambda m: (m.suggested, m.score)).asset_id
                want.discard(keep)
                rep.spared_groups += 1
            self.checked.update(want)
            rep.checked += len(want)
            self.reviewed.add(gi)
        return rep

    def invert(self, scope: Iterable[int]) -> ApplyReport:
        def rule(g: Group, ctx: Ctx) -> set[int]:
            return {i for i in g.ids if i not in self.checked}
        return self.apply(rule, scope)

    def clear(self, scope: Iterable[int]) -> None:
        self._snapshot()
        for gi in scope:
            self.checked.difference_update(self.groups[gi].ids)

    def remove_assets(self, ids: set[int]) -> None:
        """After files were moved away: drop them and groups that became trivial."""
        self.checked -= ids
        new_groups = []
        for g in self.groups:
            g.members = [m for m in g.members if m.asset_id not in ids]
            if len(g.members) > 1:
                new_groups.append(g)
        self.groups = new_groups
        self.reviewed = set()
        self._history.clear()
