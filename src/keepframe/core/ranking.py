"""Stage 8: score photos within a group and suggest one — never decide for the user.

The output is a *soft* "Suggested" badge plus human-readable reasons. Which photos get
removed is chosen by the user through selection rules (see ``selection.py``).
"""

from __future__ import annotations

import math
import re

from .types import Asset, Features, Group, GroupKind, Member

W_SHARP, W_EYES, W_SMILE, W_EXPO, W_RES, W_META = 0.35, 0.30, 0.10, 0.10, 0.10, 0.05
BLINK_PENALTY = 1.5
_EDITED = re.compile(r"(^IMG_E\d|_edited|-edited|\(edited\)|_bearbeitet|_düzenlendi)", re.I)


def is_edited(a: Asset, software: str = "") -> bool:
    return bool(_EDITED.search(a.primary.stem))


def _z(values: list[float]) -> list[float]:
    n = len(values)
    mean = sum(values) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / n)
    return [0.0 if sd < 1e-9 else (v - mean) / sd for v in values]


def rank_similar(assets: list[Asset], feats: list[Features]) -> Group:
    sharp = [math.log1p(f.sharpness) for f in feats]
    spread = (max(sharp) - min(sharp)) / (abs(max(sharp)) + 1e-9)
    sharp_z = _z(sharp)
    if spread < 0.03:            # near-identical: don't pretend one is "sharpest"
        sharp_z = [0.0] * len(sharp_z)
    res_z = _z([math.log(max(a.pixels, 1)) for a in assets])
    expo_z = _z([-f.exposure_clip for f in feats])
    has_faces = any(f.eyes_open is not None for f in feats)

    members: list[Member] = []
    for i, (a, f) in enumerate(zip(assets, feats, strict=False)):
        s = W_SHARP * sharp_z[i] + W_EXPO * expo_z[i] + W_RES * res_z[i]
        s += W_META * (a.rating / 5 + (1 if a.is_favorite else 0) + (1 if a.is_edited else 0))
        if has_faces:
            eyes = f.eyes_open if f.eyes_open is not None else 0.5
            s += W_EYES * eyes + W_SMILE * (f.smile or 0.0)
            if f.eyes_open is not None and f.eyes_open < 0.5:
                s -= BLINK_PENALTY
        else:
            s += (W_EYES + W_SMILE) * sharp_z[i]
        members.append(Member(asset_id=a.id, score=s))

    best = max(range(len(members)), key=lambda i: members[i].score)
    members[best].suggested = True
    for i, m in enumerate(members):
        m.reasons = _reasons(i, best, assets, feats, spread < 0.03)
    return Group(GroupKind.SIMILAR, members)


def _reasons(i: int, best: int, assets: list[Asset], feats: list[Features],
             near_identical: bool) -> list[str]:
    """Machine-readable reason keys; the UI translates them (ui/i18n.py)."""
    a, f = assets[i], feats[i]
    r: list[str] = []
    if a.is_favorite or a.rating > 0:
        r.append("protected")
    if a.is_edited:
        r.append("edited")
    if i == best:
        others = [j for j in range(len(feats)) if j != i]
        if near_identical:
            r.append("near_identical")
        elif others and all(f.sharpness >= feats[j].sharpness for j in others):
            r.append("sharpest")
        if f.eyes_open is not None and f.eyes_open >= 0.5:
            r.append("eyes_open")
        if others and all(a.pixels >= assets[j].pixels for j in others) and \
                any(a.pixels > assets[j].pixels for j in others):
            r.append("highest_resolution")
        return r or ["best_overall"]
    if not near_identical and f.sharpness < feats[best].sharpness * 0.8:
        r.append("blurrier")
    if f.eyes_open is not None and f.eyes_open < 0.5:
        r.append("eyes_closed")
    if a.pixels < assets[best].pixels:
        r.append("lower_resolution")
    if f.exposure_clip > feats[best].exposure_clip + 0.05:
        r.append("worse_exposure")
    return r or ["similar_to_best"]


def rank_copies(assets: list[Asset], kind: GroupKind = GroupKind.EXACT) -> Group:
    """Exact / re-encoded copies: suggest the most complete original."""
    def key(a: Asset):
        has_exif = a.time_source == "exif"
        return (a.pixels, has_exif, a.size, -len(str(a.primary)), -a.mtime)

    best = max(assets, key=key)
    members = []
    for a in assets:
        r = []
        if a is best:
            r.append("original")
            if kind == GroupKind.REENCODED and any(a.pixels > o.pixels for o in assets):
                r.append("highest_resolution")
        else:
            r.append("copy")
            if a.pixels < best.pixels:
                r.append("lower_resolution")
        members.append(Member(asset_id=a.id, score=1.0 if a is best else 0.0,
                              reasons=r, suggested=a is best))
    return Group(kind, members)


rank_exact = rank_copies   # backwards compatible name
