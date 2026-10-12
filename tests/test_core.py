from __future__ import annotations

import os
import shutil
from pathlib import Path

import numpy as np
import piexif
import pytest

from keepframe.core import actions, assets, candidates, discovery, grouping, ranking, selection, tools
from keepframe.core.catalog import Catalog
from keepframe.core.discovery import ScanScope
from keepframe.core.features import quality
from keepframe.core.metadata import time_from_name
from keepframe.core.types import Asset, Features, Group, GroupKind, Member
from keepframe.core.verify import Thresholds, decide


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("KEEPFRAME_DATA", str(tmp_path / "_data"))


def _save(im, path: Path, when: str | None = None, q: int = 92):
    path.parent.mkdir(parents=True, exist_ok=True)
    kw = {}
    if when:
        kw["exif"] = piexif.dump({"0th": {piexif.ImageIFD.Make: b"OPPO"},
                                  "Exif": {piexif.ExifIFD.DateTimeOriginal: when.encode()}})
    im.save(path, quality=q, **kw)


# --- discovery & assets ------------------------------------------------------------
def test_walk_skips_quarantine_and_unknown(tmp_path, scene):
    _save(scene(1), tmp_path / "a" / "x.jpg")
    _save(scene(2), tmp_path / "_keepframe_quarantine" / "y.jpg")
    (tmp_path / "notes.txt").write_text("hi")
    found = {e.path.name for e in discovery.walk([tmp_path])}
    assert found == {"x.jpg"}


def test_overlapping_roots_yield_each_file_once(tmp_path, scene):
    _save(scene(1), tmp_path / "a" / "b" / "x.jpg")
    files = list(discovery.walk([tmp_path, tmp_path / "a", tmp_path / "a" / "b"]))
    assert len(files) == 1


def test_raw_jpg_and_live_photo_merge(tmp_path):
    for n in ("IMG_1.JPG", "IMG_1.CR2", "IMG_2.HEIC", "IMG_2.MOV", "IMG_3.MOV"):
        (tmp_path / n).write_bytes(b"x")
    sets = assets.group_files(discovery.walk([tmp_path]))
    by_primary = {p.path.name: sorted(c.path.name for c in comps) for p, comps in sets}
    assert by_primary == {"IMG_1.JPG": ["IMG_1.CR2"], "IMG_2.HEIC": ["IMG_2.MOV"]}


def test_time_from_filename():
    assert time_from_name("IMG20251129104752_01.heic")[1] == "name"
    assert time_from_name("PXL_20251129_104752123.jpg")[1] == "name"
    assert time_from_name("IMG-20251201-WA0003.jpg")[1] == "name_day"
    assert time_from_name("1000141854.jpg") == (None, "")


# --- features ----------------------------------------------------------------------
def test_dhash_close_for_shift_far_for_other(scene):
    g = lambda im: np.asarray(im.convert("L"))  # noqa: E731
    a, b, c = (quality.dhash(g(x)) for x in (scene(1), scene(1, shift=2), scene(99)))
    assert (a ^ b).bit_count() < (a ^ c).bit_count()


def test_sharpness_detects_blur(scene):
    g = lambda im: np.asarray(im.convert("L"))  # noqa: E731
    assert quality.sharpness(g(scene(1))) > quality.sharpness(g(scene(1, blur=True))) * 2


def test_near_copy_pairs_multi_index():
    hashes = {1: 0b1011, 2: 0b1011 ^ (1 << 40), 3: (1 << 64) - 1}
    assert candidates.near_copy_pairs(hashes, bits=4) == {(1, 2)}


# --- candidates & grouping -----------------------------------------------------------
def test_time_window_respects_max_dt_and_camera():
    a = [Asset(i, Path(f"{i}.jpg"), taken_at=t, time_source="exif", camera=c)
         for i, (t, c) in enumerate([(0, "A"), (5, "A"), (500, "A"), (502, "A"), (3, "B")])]
    pairs = candidates.candidate_pairs(a, max_dt=20, cross_device=False)
    assert pairs == {(0, 1), (2, 3)}
    pairs = candidates.candidate_pairs(a, max_dt=20, cross_device=True)
    assert (0, 4) in pairs and (1, 4) in pairs


def test_low_confidence_times_excluded_by_default():
    a = [Asset(0, Path("a.jpg"), taken_at=0, time_source="mtime"),
         Asset(1, Path("b.jpg"), taken_at=1, time_source="mtime")]
    assert candidates.candidate_pairs(a) == set()
    assert candidates.candidate_pairs(a, use_low_confidence=True) == {(0, 1)}


def test_anti_chaining_stops_slow_pan():
    sims = {(0, 1): .95, (1, 2): .95, (2, 3): .95, (0, 2): .80, (1, 3): .80, (0, 3): .50}

    def sim(a, b):
        return 1.0 if a == b else sims.get((min(a, b), max(a, b)), 0.0)

    groups = grouping.build_groups([(0, 1, .95), (1, 2, .95), (2, 3, .95)], sim, min_mean=0.85)
    assert all(len(g) <= 3 for g in groups)


def test_split_large_groups():
    times = {i: float(i if i < 30 else i + 100) for i in range(60)}
    parts = grouping.split_large(list(range(60)), times, max_size=40, gap=5)
    assert len(parts) >= 2 and all(len(p) <= 40 for p in parts)


# --- ranking & selection -------------------------------------------------------------
def _group():
    a = [Asset(i, Path(f"/p/{'x' * i}{i}.jpg"), width=4000 - i * 100, height=3000, size=1000 + i,
               taken_at=float(i)) for i in range(3)]
    f = [Features(sharpness=s) for s in (100.0, 900.0, 50.0)]
    g = ranking.rank_similar(a, f)
    return g, {x.id: x for x in a}, {x.id: y for x, y in zip(a, f, strict=True)}


def test_ranking_only_suggests():
    g, _, _ = _group()
    assert sum(m.suggested for m in g.members) == 1
    assert g.best.asset_id == 1 and "sharpest" in g.best.reasons


def test_nothing_checked_by_default_and_rules():
    g, A, F = _group()
    st = selection.SelectionState([g], A, F)
    assert st.checked == set()
    st.apply("except_suggested", [0])
    assert st.checked == {0, 2}
    st.apply("except_highest_res", [0])
    assert st.checked == {1, 2}
    st.apply("except_oldest", [0])
    assert st.checked == {1, 2}
    st.invert([0])
    assert st.checked == {0}
    assert st.undo() and st.checked == {1, 2}


def test_guard_never_checks_whole_group():
    g, A, F = _group()
    st = selection.SelectionState([g], A, F)
    rep = st.apply(selection.rule_regex(r"\.jpg$"), [0])
    assert len(st.checked) == 2 and rep.spared_groups == 1
    assert not st.toggle(0, next(i for i in g.ids if i not in st.checked))


def test_protected_never_checked(tmp_path):
    g, A, F = _group()
    A[0].is_favorite = True
    st = selection.SelectionState([g], A, F)
    st.apply("except_suggested", [0])
    assert 0 not in st.checked
    assert not st.toggle(0, 0)


def test_prefer_format_and_folder_priority():
    a = [Asset(0, Path("/a/x.jpg"), width=10, height=10), Asset(1, Path("/b/x.heic"), width=10, height=10)]
    g = Group(GroupKind.REENCODED, [Member(0), Member(1)])
    ctx = ({x.id: x for x in a}, {})
    assert selection.rule_prefer_format([".heic", ".jpg"])(g, ctx) == {0}
    assert selection.rule_folder_priority([os.path.abspath("/a")])(g, ctx) == {1}


def test_verify_thresholds():
    th = Thresholds.ai(0.5)
    assert decide(0.95, 1.0, th)[0]
    assert not decide(0.70, 1.0, th, lambda: (999, 1.0))[0]
    assert decide(0.85, 1.0, th, lambda: (80, 0.5)) == (True, True)
    assert not decide(0.85, 1.0, th, lambda: (10, 0.1))[0]
    assert Thresholds.ai(1.0).high > Thresholds.ai(0.0).high
    dh = Thresholds.dhash(0.5)
    assert not decide(0.99, 60.0, dh)[0]          # dHash auto-link needs a short time gap


# --- safety --------------------------------------------------------------------------
def test_cannot_trash_whole_group():
    g = Group(GroupKind.SIMILAR, [Member(1), Member(2)])
    with pytest.raises(actions.SafetyError):
        actions.check_group(g, {1, 2})
    actions.check_group(g, {2})


def test_quarantine_moves_companions_and_undo(tmp_path, scene):
    root = tmp_path / "lib"
    jpg, raw = root / "d" / "IMG_1.JPG", root / "d" / "IMG_1.CR2"
    _save(scene(1), jpg)
    raw.write_bytes(b"raw")
    st = jpg.stat()
    cat = Catalog(tmp_path / "c.db")
    ex = actions.ActionExecutor(cat, mode="quarantine")
    res = ex.remove_assets([Asset(1, jpg, companions=[raw], size=st.st_size, mtime=st.st_mtime)],
                           [root])
    assert res.moved == 2 and res.done_assets == {1}
    assert not jpg.exists() and not raw.exists()
    assert (root / actions.QUARANTINE_DIR / ex.session_id / "d" / "IMG_1.JPG").exists()
    assert ex.undo_session().moved == 2 and jpg.exists() and raw.exists()
    cat.close()


def test_changed_file_is_not_touched(tmp_path, scene):
    p = tmp_path / "a.jpg"
    _save(scene(1), p)
    cat = Catalog(tmp_path / "c.db")
    ex = actions.ActionExecutor(cat, mode="quarantine")
    res = ex.remove_assets([Asset(1, p, size=1, mtime=0)], [tmp_path])
    assert p.exists() and res.failed and not res.done_assets
    cat.close()


# --- file tools ----------------------------------------------------------------------
def test_file_tools(tmp_path, scene):
    _save(scene(1), tmp_path / "a" / "x.jpg")
    shutil.copy(tmp_path / "a" / "x.jpg", tmp_path / "b.jpg")
    (tmp_path / "zero.txt").write_bytes(b"")
    (tmp_path / "e" / "f").mkdir(parents=True)
    (tmp_path / "~x.tmp").write_bytes(b"1")
    scene(2).save(tmp_path / "png.jpg", "PNG")
    (tmp_path / "bad.jpg").write_bytes((tmp_path / "b.jpg").read_bytes()[:500])
    sc = ScanScope(roots=[tmp_path], extensions=None)
    assert len(tools.duplicate_files(sc).groups) == 1
    assert {i.path.name for i in tools.empty_files(sc).items} == {"zero.txt"}
    assert {i.path.name for i in tools.empty_folders(sc).items} == {"e", "f"}
    assert {i.path.name for i in tools.temporary_files(sc).items} == {"~x.tmp"}
    assert {i.path.name for i in tools.wrong_extensions(sc).items} == {"png.jpg"}
    assert "bad.jpg" in {i.path.name for i in tools.broken_images(sc).items}
    assert tools.big_files(sc, count=1).items[0].size > 0


# --- end to end (dHash fallback, no model needed) ----------------------------------------
def test_pipeline_bursts_copies_and_cache(tmp_path, scene):
    from keepframe.core import pipeline

    lib = tmp_path / "lib"
    for i in range(4):
        _save(scene(1, shift=i * 2, blur=(i == 2)), lib / f"IMG2025112910475{i}.jpg",
              f"2025:11:29 10:47:5{i}")
    _save(scene(50), lib / "IMG20251129104759.jpg", "2025:11:29 10:47:59")
    _save(scene(7), lib / "a" / "IMG20230101090000.jpg", "2023:01:01 09:00:00")
    shutil.copy(lib / "a" / "IMG20230101090000.jpg", lib / "IMG20230101090000.jpg")
    _save(scene(1).resize((160, 120)), lib / "wa" / "IMG-20251201-WA0003.jpg", q=70)

    opts = pipeline.ScanOptions(roots=[lib, lib / "a"], use_ai=False, min_size=0)
    res = pipeline.run(opts)
    kinds = sorted(g.kind.value for g in res.groups)
    assert kinds == ["exact", "reencoded", "similar"], kinds
    sim = next(g for g in res.groups if g.kind == GroupKind.SIMILAR)
    names = {res.assets[m.asset_id].primary.name for m in sim.members}
    assert "IMG20251129104759.jpg" not in names
    assert res.assets[sim.best.asset_id].primary.name != "IMG20251129104752.jpg"   # blurred
    assert all(a.thumb.exists() for a in res.assets.values())
    res2 = pipeline.run(opts)
    assert res2.stats.from_cache == res2.stats.photos
    assert sorted(g.kind.value for g in res2.groups) == kinds
