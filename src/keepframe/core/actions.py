"""Safe file operations: Recycle Bin / quarantine / move-to-folder, logged and undoable.

Invariants:
  * Never delete permanently.
  * A file is only touched if it still has the size/mtime seen during the scan.
  * All files of an asset (RAW+JPG, HEIC+MOV, XMP) move together.
  * Where the Recycle Bin would delete permanently (network, removable drives), files
    go to the quarantine folder instead.
"""

from __future__ import annotations

import os
import shutil
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .catalog import Catalog
from .types import Asset, Group

QUARANTINE_DIR = "_keepframe_quarantine"


class SafetyError(RuntimeError):
    pass


@dataclass
class Result:
    moved: int = 0
    bytes: int = 0
    failed: list[tuple[Path, str]] = field(default_factory=list)
    done_assets: set[int] = field(default_factory=set)
    session_id: str = ""


def drive_type(p: Path) -> int:
    """Windows GetDriveTypeW: 2 removable, 3 fixed, 4 remote. 0 elsewhere."""
    s = str(p)
    if s.startswith("\\\\"):
        return 4
    try:
        import ctypes

        return int(ctypes.windll.kernel32.GetDriveTypeW(Path(s).drive + "\\"))
    except Exception:
        return 0


def recycle_unsafe(p: Path) -> bool:
    return drive_type(p) in (2, 4)


def check_group(group: Group, checked: set[int]) -> None:
    if all(m.asset_id in checked for m in group.members):
        raise SafetyError("At least one photo in a group must be kept.")


def _unique(p: Path) -> Path:
    if not p.exists():
        return p
    i = 1
    while (c := p.with_name(f"{p.stem}_{i}{p.suffix}")).exists():
        i += 1
    return c


def _retry(fn, tries: int = 3):
    for k in range(tries):
        try:
            return fn()
        except PermissionError:
            if k == tries - 1:
                raise
            time.sleep(0.15 * (k + 1))


class ActionExecutor:
    def __init__(self, catalog: Catalog, mode: str = "recycle",
                 quarantine_root: Path | None = None, target_dir: Path | None = None):
        """mode: 'recycle' | 'quarantine' | 'move' (to ``target_dir``)."""
        self.cat = catalog
        self.mode = mode
        self.quarantine_root = quarantine_root
        self.target_dir = target_dir
        self.session_id = time.strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:6]

    def _dest(self, src: Path, root: Path, base: Path) -> Path:
        try:
            rel = src.relative_to(root)
        except ValueError:
            rel = Path(src.drive.replace(":", "") or "x") / src.relative_to(src.anchor)
        return _unique(base / rel)

    def remove_assets(self, assets: Iterable[Asset], roots: list[Path],
                      progress: Callable[[int, int], None] | None = None) -> Result:
        res = Result(session_id=self.session_id)
        items = list(assets)
        recycle_batch: list[tuple[Asset, Path]] = []
        for n, a in enumerate(items, 1):
            root = next((r for r in roots if _under(a.primary, r)), a.primary.parent)
            try:
                st = a.primary.stat()
                if not a.primary.is_dir() and (st.st_size != a.size
                                               or abs(st.st_mtime - a.mtime) > 2):
                    raise SafetyError("file changed since the scan")
            except FileNotFoundError:
                res.failed.append((a.primary, "file not found"))
                continue
            except SafetyError as e:
                res.failed.append((a.primary, str(e)))
                continue
            mode = self.mode
            if mode == "recycle" and recycle_unsafe(a.primary):
                mode = "quarantine"
            files = [f for f in a.all_files if f.exists()]
            if mode == "recycle":
                recycle_batch.extend((a, f) for f in files)
                continue
            base = (self.target_dir if mode == "move" else
                    (self.quarantine_root or root) / QUARANTINE_DIR / self.session_id)
            ok = True
            for f in files:
                dst = self._dest(f, root, base)
                lid = self._log(a.id, mode, f, dst, done=False)
                try:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    _retry(lambda f=f, dst=dst: shutil.move(str(f), str(dst)))
                    self._mark_done(lid)
                    res.moved += 1
                except Exception as e:
                    ok = False
                    res.failed.append((f, str(e)))
            if ok:
                res.done_assets.add(a.id)
                res.bytes += a.size
            if progress:
                progress(n, len(items))
        if recycle_batch:
            self._recycle(recycle_batch, res)
        self.cat.db.commit()
        return res

    def _recycle(self, batch: list[tuple[Asset, Path]], res: Result) -> None:
        from send2trash import send2trash

        by_asset: dict[int, list[Path]] = {}
        amap: dict[int, Asset] = {}
        for a, f in batch:
            by_asset.setdefault(a.id, []).append(f)
            amap[a.id] = a
        paths = [str(f) for _, f in batch]
        try:
            _retry(lambda: send2trash(paths))          # one shell operation
            for a, f in batch:
                self._log(a.id, "recycle", f, None, done=True)
            res.moved += len(paths)
            for aid in by_asset:
                res.done_assets.add(aid)
                res.bytes += amap[aid].size
        except Exception:
            for aid, files in by_asset.items():        # fall back one by one
                ok = True
                for f in files:
                    try:
                        _retry(lambda f=f: send2trash(str(f)))
                        self._log(aid, "recycle", f, None, done=True)
                        res.moved += 1
                    except Exception as e:
                        ok = False
                        res.failed.append((f, str(e)))
                if ok:
                    res.done_assets.add(aid)
                    res.bytes += amap[aid].size

    def _log(self, asset_id: int, op: str, src: Path, dst: Path | None, done: bool) -> int:
        cur = self.cat.db.execute(
            "INSERT INTO action_log(session_id, asset_id, op, src_path, dst_path, ts, undone)"
            " VALUES(?,?,?,?,?,?,?)",
            (self.session_id, asset_id, op, str(src), str(dst) if dst else None, time.time(),
             0 if done else -1))
        return cur.lastrowid

    def _mark_done(self, lid: int) -> None:
        self.cat.db.execute("UPDATE action_log SET undone=0 WHERE id=?", (lid,))

    def undo_session(self, session_id: str | None = None) -> Result:
        """Move files back. Recycle Bin items are restored via the Windows shell."""
        sid = session_id or self.session_id
        res = Result(session_id=sid)
        rows = self.cat.db.execute(
            "SELECT id, op, src_path, dst_path FROM action_log"
            " WHERE session_id=? AND undone=0 ORDER BY id DESC", (sid,)).fetchall()
        recycled = []
        for r in rows:
            if r["op"] == "recycle":
                recycled.append(r)
                continue
            src, dst = Path(r["src_path"]), Path(r["dst_path"])
            try:
                src.parent.mkdir(parents=True, exist_ok=True)
                _retry(lambda dst=dst, src=src: shutil.move(str(dst), str(_unique(src))))
                self.cat.db.execute("UPDATE action_log SET undone=1 WHERE id=?", (r["id"],))
                res.moved += 1
            except Exception as e:
                res.failed.append((dst, str(e)))
        if recycled:
            restored = restore_from_recycle_bin([Path(r["src_path"]) for r in recycled])
            for r in recycled:
                if os.path.normcase(r["src_path"]) in restored:
                    self.cat.db.execute("UPDATE action_log SET undone=1 WHERE id=?", (r["id"],))
                    res.moved += 1
                else:
                    res.failed.append((Path(r["src_path"]), "restore from Recycle Bin manually"))
        self.cat.db.commit()
        return res


def restore_from_recycle_bin(paths: list[Path]) -> set[str]:
    """Restore items by original path using Shell.Application (Windows only)."""
    want = {os.path.normcase(str(p)) for p in paths}
    done: set[str] = set()
    try:
        import win32com.client  # type: ignore  # pywin32, optional

        shell = win32com.client.Dispatch("Shell.Application")
        bin_ = shell.Namespace(10)
        for item in list(bin_.Items()):
            orig = os.path.join(bin_.GetDetailsOf(item, 1), item.Name)
            key = os.path.normcase(orig)
            cands = [k for k in want if k == key or os.path.splitext(k)[0] == key]
            if cands:
                for verb in item.Verbs():
                    if verb.Name.replace("&", "").lower() in ("restore", "geri yükle"):
                        verb.DoIt()
                        done.add(cands[0])
                        break
    except Exception:
        pass
    return done


def _under(p: Path, root: Path) -> bool:
    a, b = os.path.normcase(str(p)), os.path.normcase(str(root)).rstrip("\\/")
    return a.startswith(b + os.sep)
