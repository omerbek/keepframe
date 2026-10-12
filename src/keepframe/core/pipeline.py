"""Orchestrates the similar-photo scan. Pure Python (no Qt): the GUI and CLI share it.

Memory-light: workers decode one image at a time, write a 512 px thumbnail to disk and
return only small numbers. Embeddings and ORB read the thumbnails back. Results are
cached in SQLite by (path, size, mtime), so a re-scan only touches new/changed files.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from . import assets as assets_mod
from . import candidates, discovery, thumbs
from .cache import FeatureCache, Row
from .decode import decode
from .features import embedder, hashes, quality
from .grouping import build_groups, split_large
from .metadata import HIGH_CONFIDENCE
from .ranking import is_edited, rank_copies, rank_similar
from .types import Asset, Features, Group, GroupKind
from .verify import OrbCache, Thresholds, decide, orb_match

Progress = Callable[[str, int, int], None]   # (stage_key, done, total)


@dataclass
class ScanOptions:
    roots: list[Path]
    excluded: list[str] = field(default_factory=list)
    strictness: float = 0.5                  # 0 = loose, 1 = strict
    max_dt: float = candidates.MAX_DT        # seconds between similar shots
    cross_device: bool = True
    near_copies: bool = True                 # resized / re-encoded copies, any date
    include_screenshots: bool = False
    use_file_dates: bool = False             # low-confidence times for similar matching
    use_ai: bool = True
    device: str = "auto"                     # auto | cpu
    workers: int = 0                         # 0 = auto
    skip_hidden: bool = True
    include_cloud_only: bool = False
    min_size: int = 8 * 1024
    max_group: int = 40
    use_cache: bool = True


@dataclass
class ScanStats:
    files: int = 0
    photos: int = 0
    from_cache: int = 0
    skipped_cloud: int = 0
    skipped_dupe_path: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    seconds: float = 0.0
    ai: bool = False


@dataclass
class ScanResult:
    assets: dict[int, Asset]
    features: dict[int, Features]
    groups: list[Group]
    device: str
    stats: ScanStats = field(default_factory=ScanStats)


class Cancelled(Exception):
    pass


def pair_key(a: Path, b: Path) -> tuple[str, str]:
    x, y = os.path.normcase(str(a)), os.path.normcase(str(b))
    return (x, y) if x <= y else (y, x)


def _workers(n: int) -> int:
    return n or max(2, min(16, (os.cpu_count() or 4)))


def _chunked(ex: ThreadPoolExecutor, fn, items, cancel: threading.Event, size: int):
    """Like ex.map, but submits in chunks so cancellation is quick."""
    for s in range(0, len(items), size):
        if cancel.is_set():
            raise Cancelled
        futs = [ex.submit(fn, it) for it in items[s : s + size]]
        for f in futs:
            yield f.result()


def run(opts: ScanOptions, progress: Progress | None = None,
        cancel: threading.Event | None = None,
        ignored: set[tuple[str, str]] = frozenset(),
        cache: FeatureCache | None = None) -> ScanResult:
    t0 = time.monotonic()
    progress = progress or (lambda *_: None)
    cancel = cancel or threading.Event()
    stats = ScanStats()
    nw = _workers(opts.workers)
    own_cache = cache is None and opts.use_cache
    if own_cache:
        cache = FeatureCache()

    def check():
        if cancel.is_set():
            raise Cancelled

    try:
        # 1. discovery ------------------------------------------------------------
        scope = discovery.ScanScope(roots=opts.roots, excluded=opts.excluded,
                                    extensions=discovery.PHOTO_EXT, min_size=0,
                                    skip_hidden=opts.skip_hidden,
                                    include_cloud_only=opts.include_cloud_only)
        wst = discovery.WalkStats()
        files = []
        for fe in discovery.walk(scope, stats=wst, cancel=cancel):
            files.append(fe)
            if len(files) % 200 == 0:
                progress("discover", len(files), 0)
        progress("discover", len(files), 0)
        check()
        stats.files, stats.skipped_cloud = wst.files, wst.skipped_cloud
        stats.skipped_dupe_path = wst.skipped_dupe_path
        file_sets = [(p, c) for p, c in assets_mod.group_files(files)
                     if p.size >= opts.min_size]

        assets: dict[int, Asset] = {}
        for i, (p, comps) in enumerate(file_sets):
            assets[i] = Asset(id=i, primary=p.path, companions=[c.path for c in comps],
                              size=p.size, mtime=p.mtime,
                              thumb=thumbs.thumb_path(p.path, p.size, p.mtime))
        stats.photos = len(assets)

        # 2-4. metadata + proxy + cheap features (cached) ---------------------------
        feats: dict[int, Features] = {}
        ok_ids: set[int] = set()
        hits = cache.get_many([(str(a.primary), a.size, a.mtime) for a in assets.values()]) \
            if cache else {}

        def apply_row(a: Asset, r: Row):
            a.taken_at, a.camera, a.burst_id = r.taken_at, r.camera, r.burst_id
            a.time_source = r.time_source
            a.width, a.height, a.rating = r.width, r.height, r.rating
            f = Features(dhash=r.dhash, sharpness=r.sharp, exposure_clip=r.exposure)
            if r.emb is not None and r.model_ver == embedder.MODEL_VERSION:
                f.embedding = r.emb
            feats[a.id] = f
            if r.ok:
                ok_ids.add(a.id)

        todo: list[Asset] = []
        for a in assets.values():
            r = hits.get(str(a.primary))
            if r is not None and (not r.ok or (a.thumb and a.thumb.exists())):
                apply_row(a, r)
                stats.from_cache += 1
            else:
                todo.append(a)

        def work(a: Asset):
            if cancel.is_set():
                return a, None, "cancelled"
            try:
                d = decode(a.primary, a.mtime)
                g = np.asarray(d.image.convert("L"))
                thumbs.save(d.image, a.thumb)
                m = d.meta
                row = Row(m.taken_at, m.time_source, m.camera, m.burst_id, m.width, m.height,
                          m.rating, quality.dhash(g), quality.sharpness(g),
                          quality.exposure_clip(g), True)
                return a, (row, m), None
            except Exception as e:  # recorded and shown to the user
                return a, None, f"{type(e).__name__}: {e}"

        total = len(todo)
        progress("features", 0, total)
        with ThreadPoolExecutor(nw) as ex:
            for n, (a, res, err) in enumerate(_chunked(ex, work, todo, cancel, nw * 8), 1):
                if err:
                    if err != "cancelled":
                        stats.errors.append((str(a.primary), err))
                    if cache and err != "cancelled":
                        cache.put(str(a.primary), a.size, a.mtime,
                                  Row(None, "", "", "", 0, 0, 0, 0, 0.0, 0.0, False))
                    continue
                row, m = res
                apply_row(a, row)
                a.is_screenshot = m.is_screenshot
                if cache:
                    cache.put(str(a.primary), a.size, a.mtime, row)
                    if n % 500 == 0:
                        cache.commit()
                if n % 25 == 0 or n == total:
                    progress("features", n, total)
        if cache:
            cache.commit()
        check()
        from .metadata import _SCREENSHOT
        for a in assets.values():
            a.is_edited = is_edited(a)
            if not a.is_screenshot:
                a.is_screenshot = bool(_SCREENSHOT.search(a.primary.name)) or (
                    a.primary.suffix.lower() == ".png" and not a.camera)

        # 5a. exact copies: size -> 64 KB pre-hash -> full hash ----------------------
        by_size: dict[int, list[int]] = defaultdict(list)
        for aid in ok_ids:
            by_size[assets[aid].size].append(aid)
        same = [aid for v in by_size.values() if len(v) > 1 for aid in v]
        progress("hash", 0, len(same))
        pre: dict[int, str] = {}
        with ThreadPoolExecutor(nw) as ex:
            for aid, h in _chunked(ex, lambda i: (i, _try(hashes.file_hash, assets[i].primary,
                                                         limit=hashes.PARTIAL)),
                                   same, cancel, nw * 8):
                if h:
                    pre[aid] = h
        buckets: dict[tuple[int, str], list[int]] = defaultdict(list)
        for aid, h in pre.items():
            buckets[(assets[aid].size, h)].append(aid)
        need_full = [aid for v in buckets.values() if len(v) > 1 for aid in v]
        by_hash: dict[str, list[int]] = defaultdict(list)
        with ThreadPoolExecutor(nw) as ex:
            for n, (aid, h) in enumerate(_chunked(
                    ex, lambda i: (i, _try(hashes.file_hash, assets[i].primary)),
                    need_full, cancel, nw * 4), 1):
                if h:
                    feats[aid].sha256 = h
                    by_hash[h].append(aid)
                progress("hash", n, len(need_full))
        exact_sets = [sorted(v) for v in by_hash.values() if len(v) > 1]

        # representative per exact set stays in the similarity pool
        hidden: set[int] = set()
        for v in exact_sets:
            rep = max(v, key=lambda i: (assets[i].time_source == "exif", -len(str(assets[i].primary))))
            hidden.update(set(v) - {rep})

        # 5b. re-encoded / resized copies across the library -------------------------
        reenc_sets: list[list[int]] = []
        if opts.near_copies:
            hs = {aid: feats[aid].dhash for aid in ok_ids if aid not in hidden}
            near = candidates.near_copy_pairs(hs)
            uf: dict[int, int] = {}

            def find(x):
                while uf.setdefault(x, x) != x:
                    uf[x] = uf[uf[x]]
                    x = uf[x]
                return x
            best_for_untimed: dict[int, tuple[int, int]] = {}
            keep_edges: list[tuple[int, int]] = []
            for a, b in sorted(near):
                A, B = assets[a], assets[b]
                if pair_key(A.primary, B.primary) in ignored or not _same_aspect(A, B):
                    continue
                ta = A.time_source in HIGH_CONFIDENCE
                tb = B.time_source in HIGH_CONFIDENCE
                fam = _ext_family(A.primary) != _ext_family(B.primary)
                if ta and tb:
                    # two real captures: a copy only if same moment AND re-encoded/resized
                    if abs(A.taken_at - B.taken_at) > 1.0 or not (fam or A.pixels != B.pixels):
                        continue
                    keep_edges.append((a, b))
                    continue
                d = (feats[a].dhash ^ feats[b].dhash).bit_count()
                for x, y in ((a, b), (b, a)):      # untimed copy -> its single closest match
                    if assets[x].time_source not in HIGH_CONFIDENCE:
                        if x not in best_for_untimed or d < best_for_untimed[x][1]:
                            best_for_untimed[x] = (y, d)
            keep_edges += [(x, y) for x, (y, _) in best_for_untimed.items()]
            for a, b in keep_edges:
                uf[find(a)] = find(b)
            comp: dict[int, list[int]] = defaultdict(list)
            for x in list(uf):
                comp[find(x)].append(x)
            reenc_sets = [sorted(v) for v in comp.values() if len(v) > 1]
            for v in reenc_sets:
                rep = max(v, key=lambda i: (assets[i].pixels, assets[i].size))
                hidden.update(set(v) - {rep})

        # 5c. candidate pairs for similar shots -------------------------------------
        pool = [assets[i] for i in ok_ids if i not in hidden]
        pairs = candidates.candidate_pairs(pool, opts.max_dt, opts.cross_device,
                                           opts.use_file_dates, opts.include_screenshots)
        cand_ids = sorted({x for p in pairs for x in p})

        # 6. embeddings (only for candidates, from thumbnails) ----------------------
        device = "dHash"
        if opts.use_ai and embedder.available() and cand_ids:
            model = embedder.Embedder(device=opts.device)
            device = model.device_label
            stats.ai = True
            missing = [i for i in cand_ids if feats[i].embedding is None]
            progress("embed", 0, len(missing))
            B = 64
            with ThreadPoolExecutor(nw) as ex:
                for s in range(0, len(missing), B):
                    check()
                    chunk = missing[s : s + B]
                    ims = list(ex.map(lambda i: _open_thumb(assets[i].thumb), chunk))
                    keep = [(i, im) for i, im in zip(chunk, ims, strict=False) if im is not None]
                    if keep:
                        vecs = model.embed([im for _, im in keep])
                        for (i, _), v in zip(keep, vecs, strict=False):
                            feats[i].embedding = v
                            if cache:
                                cache.set_emb(str(assets[i].primary), v, embedder.MODEL_VERSION)
                    progress("embed", min(s + B, len(missing)), len(missing))
            if cache:
                cache.commit()
            have = [i for i in cand_ids if feats[i].embedding is not None]
            if len(have) < len(cand_ids):    # keep one scale: drop pairs without embeddings
                hv = set(have)
                pairs = {p for p in pairs if p[0] in hv and p[1] in hv}
        use_emb = stats.ai
        th = Thresholds.ai(opts.strictness) if use_emb else Thresholds.dhash(opts.strictness)

        def sim(a: int, b: int) -> float:
            if use_emb:
                ea, eb = feats[a].embedding, feats[b].embedding
                return float(np.dot(ea.astype(np.float32), eb.astype(np.float32)))
            return 1.0 - (feats[a].dhash ^ feats[b].dhash).bit_count() / 64.0

        # 7. verify pairs -------------------------------------------------------------
        orb = OrbCache()
        plist = sorted(pairs)
        edges: list[tuple[int, int, float]] = []
        verified: set[tuple[int, int]] = set()

        def ver(p):
            a, b = p
            A, B = assets[a], assets[b]
            if pair_key(A.primary, B.primary) in ignored or not _same_aspect(A, B, 0.08):
                return p, None, False
            s = sim(a, b)
            dt = abs((A.taken_at or 0) - (B.taken_at or 0))
            linked, geo = decide(s, dt, th, lambda: orb_match(orb, A.thumb, B.thumb))
            return p, (s if linked else None), geo

        progress("verify", 0, len(plist))
        with ThreadPoolExecutor(nw) as ex:
            for n, (p, s, geo) in enumerate(_chunked(ex, ver, plist, cancel, nw * 64), 1):
                if s is not None:
                    edges.append((p[0], p[1], s))
                    if geo:
                        verified.add(p)
                if n % 500 == 0 or n == len(plist):
                    progress("verify", n, len(plist))

        # 8. grouping + ranking ----------------------------------------------------------
        groups: list[Group] = []
        for v in exact_sets:
            groups.append(rank_copies([assets[i] for i in v], GroupKind.EXACT))
        for v in reenc_sets:
            groups.append(rank_copies([assets[i] for i in v], GroupKind.REENCODED))
        times = {i: assets[i].taken_at for i in assets}
        for g in build_groups(edges, sim, th.group_mean, th.low * 0.97, verified):
            for part in split_large(g, times, opts.max_group):
                grp = rank_similar([assets[i] for i in part], [feats[i] for i in part])
                best = grp.best.asset_id
                for m in grp.members:
                    m.similarity = 1.0 if m.asset_id == best else sim(best, m.asset_id)
                groups.append(grp)

        order = {GroupKind.SIMILAR: 0, GroupKind.REENCODED: 1, GroupKind.EXACT: 2}
        groups.sort(key=lambda g: (order[g.kind],
                                   min((assets[m.asset_id].taken_at or 0) for m in g.members)))
        stats.seconds = time.monotonic() - t0
        progress("done", len(groups), len(groups))
        return ScanResult(assets, feats, groups, device, stats)
    finally:
        if own_cache and cache:
            cache.close()


def _try(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception:
        return None


def _open_thumb(p: Path | None):
    if p is None:
        return None
    try:
        with Image.open(p) as im:
            return im.convert("RGB")
    except Exception:
        return None


def _ext_family(p: Path) -> str:
    e = p.suffix.lower()
    return {".jpeg": ".jpg", ".jpe": ".jpg", ".heif": ".heic", ".tiff": ".tif"}.get(e, e)


def _same_aspect(a: Asset, b: Asset, tol: float = 0.02) -> bool:
    if not (a.width and a.height and b.width and b.height):
        return True
    ra, rb = a.width / a.height, b.width / b.height
    return abs(ra - rb) / max(ra, rb) <= tol
