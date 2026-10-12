"""KeepFrame main window: sidebar of tools, folder bar, pages."""

from __future__ import annotations

import itertools
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import APP_NAME, __version__
from ..app.controller import TaskRunner
from ..core import pipeline, tools
from ..core.actions import ActionExecutor
from ..core.cache import FeatureCache
from ..core.catalog import Catalog
from ..core.discovery import ScanScope
from ..core.features import embedder
from ..core.types import Asset
from . import theme
from .i18n import t
from .icons import icon
from .imageloader import ImageLoader
from .pages import HistoryPage, ScanPage, SettingsPage
from .review import ReviewPage
from .settings import Settings
from .theme import human_size
from .toolpage import ToolPage
from .widgets import EmptyState, FolderBar, Toast, btn, label

PHOTO_TOOLS = ["similar"]
FILE_TOOLS = ["duplicates", "big", "empty_files", "empty_folders", "temp", "broken", "bad_ext"]
NAV_ICONS = {"similar": "images", "duplicates": "copy", "big": "hard-drive",
             "empty_files": "file-x", "empty_folders": "folder-x", "temp": "clock",
             "broken": "image-off", "bad_ext": "file-question", "history": "history",
             "settings": "settings"}


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings | None = None):
        super().__init__()
        self.settings = settings or Settings.load()
        self.setWindowTitle(APP_NAME)
        self.resize(1440, 900)
        self.setMinimumSize(1100, 680)
        self.catalog = Catalog()
        self.loader = ImageLoader(parent=self)
        self.runner = TaskRunner(self)
        self.job = ""
        self.current = "similar"

        central = QWidget()
        self.setCentralWidget(central)
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._sidebar())
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        self.folders = FolderBar(self.settings)
        self.folders.scan_clicked.connect(self.start_scan)
        rv.addWidget(self.folders)
        self.stack = QStackedWidget()
        rv.addWidget(self.stack, 1)
        h.addWidget(right, 1)

        # pages
        self.scan_page = ScanPage()
        self.scan_page.cancel.connect(self.runner.cancel)
        self.review = ReviewPage(self.loader, self.settings)
        self.review.remove_requested.connect(lambda ids: self.remove_photos(ids, "remove"))
        self.review.move_requested.connect(lambda ids: self.remove_photos(ids, "move"))
        self.review.ignore_group.connect(self.ignore_group)
        self.review.toast.connect(lambda m, k: self.toast.show_message(m, k))
        self.settings_page = SettingsPage(self.settings)
        self.settings_page.theme_changed.connect(self._theme)
        self.settings_page.clear_cache.connect(self._clear_cache)
        self.settings_page.clear_ignored.connect(self._clear_ignored)
        self.history = HistoryPage(self.catalog)
        self.history.undo.connect(self.undo_session)
        self.tool_pages: dict[str, ToolPage] = {}
        self.empty_pages: dict[str, QWidget] = {}
        for w in (self.scan_page, self.review, self.settings_page, self.history):
            self.stack.addWidget(w)

        self.status = label("", "caption")
        self.statusBar().addWidget(self.status, 1)
        dev = label(self._device_text(), "caption")
        self.statusBar().addPermanentWidget(dev)
        self.toast = Toast(central)

        self.runner.progress.connect(self.scan_page.update)
        self.runner.finished.connect(self._finished)
        self.runner.failed.connect(self._failed)
        self.runner.cancelled.connect(self._cancelled)
        self.folders.changed.connect(lambda: self.review.set_protected(self.settings.protected))
        QShortcut(QKeySequence("F5"), self, self.start_scan)
        QShortcut(QKeySequence("Ctrl+O"), self, self.folders.add_dialog)
        self.results_ready: set[str] = set()
        self.navigate("similar")

    # ------------------------------------------------------------------ chrome
    def _sidebar(self) -> QWidget:
        sb = QWidget()
        sb.setObjectName("Sidebar")
        sb.setFixedWidth(232)
        v = QVBoxLayout(sb)
        v.setContentsMargins(12, 16, 12, 12)
        v.setSpacing(2)
        logo = QHBoxLayout()
        logo.setContentsMargins(6, 0, 0, 12)
        ic = label()
        logo_pm = QPixmap(str(Path(__file__).parent / "app_icon.png"))
        logo_pm.setDevicePixelRatio(logo_pm.width() / 34)
        ic.setPixmap(logo_pm)
        logo.addWidget(ic)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(label(APP_NAME, "logo"))
        col.addWidget(label(t("app.tagline_short"), "muted"))
        logo.addLayout(col, 1)
        v.addLayout(logo)
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        self.nav_buttons: dict[str, object] = {}

        def section(title: str):
            lab = label(title.upper(), "overline")
            lab.setContentsMargins(10, 14, 0, 4)
            v.addWidget(lab)

        def item(key: str):
            b = btn("  " + t("nav." + key), "nav", NAV_ICONS[key], checkable=True)
            b.setIconSize(QSize(18, 18))
            b.clicked.connect(lambda _=False, k=key: self.navigate(k))
            self.nav.addButton(b)
            self.nav_buttons[key] = b
            v.addWidget(b)

        section(t("nav.section.photos"))
        for k in PHOTO_TOOLS:
            item(k)
        section(t("nav.section.files"))
        for k in FILE_TOOLS:
            item(k)
        v.addStretch(1)
        item("history")
        item("settings")
        ver = label(f"v{__version__} · GPL-3.0", "muted")
        ver.setContentsMargins(10, 8, 0, 0)
        v.addWidget(ver)
        return sb

    def _device_text(self) -> str:
        if not self.settings.use_ai:
            return t("status.ai_off")
        return t("status.ai_ready") if embedder.available() else t("status.ai_missing")

    def _busy(self) -> bool:
        # The worker thread may still be winding down after it reported a result,
        # so "busy" is tracked by the job flag, not by QThread.isRunning().
        return bool(self.job)

    def _run(self, job: str, fn) -> None:
        self.job = job
        if not self.runner.start(fn):
            self.job = ""
            self.toast.show_message(t("toast.cancelled"), "info")

    def navigate(self, key: str) -> None:
        if key in self.nav_buttons:
            self.nav_buttons[key].setChecked(True)
        if self._busy() and key not in ("history", "settings"):
            self.stack.setCurrentWidget(self.scan_page)
        if key in ("history", "settings"):
            if key == "history":
                self.history.refresh()
            self.stack.setCurrentWidget(self.history if key == "history" else self.settings_page)
            self.folders.title.setText(t("nav." + key))
            self.folders.scan.setVisible(False)
            return
        self.current = key
        self.folders.title.setText(t("nav." + key))
        self.folders.scan.setVisible(True)
        self.folders.scan.setText(t("scan.start") if key not in self.results_ready
                                  else t("scan.rescan"))
        if self._busy():
            return
        if key == "similar" and key in self.results_ready:
            self.stack.setCurrentWidget(self.review)
        elif key in self.tool_pages and key in self.results_ready:
            self.stack.setCurrentWidget(self.tool_pages[key])
        else:
            self.stack.setCurrentWidget(self._empty(key))

    def _empty(self, key: str) -> QWidget:
        if key not in self.empty_pages:
            b = btn(t("scan.start") if self.settings.roots else t("folder.add"), "primary",
                    "scan" if self.settings.roots else "folder-plus")
            b.clicked.connect(lambda: self.start_scan() if self.settings.roots
                              else self.folders.add_dialog())
            self.folders.changed.connect(lambda b=b: (
                b.setText(t("scan.start") if self.settings.roots else t("folder.add"))))
            w = EmptyState(NAV_ICONS[key], t("empty." + key + ".title"),
                           t("empty." + key + ".text") + "\n\n" + t("empty.drop"), b,
                           dropzone=True)
            w.setAcceptDrops(True)
            w.dragEnterEvent = lambda e: e.acceptProposedAction() if e.mimeData().hasUrls() else None
            w.dropEvent = lambda e: self.folders.add(
                [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])
            self.empty_pages[key] = w
            self.stack.addWidget(w)
        return self.empty_pages[key]

    # ------------------------------------------------------------------ scanning
    def start_scan(self) -> None:
        if self._busy() or self.current not in PHOTO_TOOLS + FILE_TOOLS:
            return
        roots = self.folders.roots()
        if not roots:
            self.folders.add_dialog()
            roots = self.folders.roots()
            if not roots:
                return
        s = self.settings
        key = self.current
        if key == "similar":
            opts = pipeline.ScanOptions(
                roots=roots, excluded=s.excluded_list, strictness=s.strictness,
                max_dt=s.max_dt, cross_device=s.cross_device, near_copies=s.near_copies,
                include_screenshots=s.include_screenshots, use_file_dates=s.use_file_dates,
                use_ai=s.use_ai, device=s.device, workers=s.workers, skip_hidden=s.skip_hidden,
                include_cloud_only=s.include_cloud_only, min_size=s.min_size_kb * 1024)
            ignored = self.catalog.ignored_path_pairs()
            fn = lambda progress, cancel: pipeline.run(opts, progress, cancel, ignored)  # noqa: E731
        else:
            scope = ScanScope(roots=roots, excluded=s.excluded_list, extensions=None,
                              min_size=1 if key == "duplicates" else 0,
                              skip_hidden=s.skip_hidden, include_cloud_only=s.include_cloud_only)
            fn_tool = tools.TOOLS[key]
            kw = {"count": s.big_count} if key == "big" else {}
            fn = lambda progress, cancel: fn_tool(scope, cancel, progress, **kw)  # noqa: E731
        _job = "scan:" + key
        self.scan_page.start(t("scan.title_for", tool=t("nav." + key)))
        self.stack.setCurrentWidget(self.scan_page)
        self.folders.scan.setEnabled(False)
        self._run(_job, fn)

    def _finished(self, res) -> None:
        job, self.job = self.job, ""
        self.folders.scan.setEnabled(bool(self.settings.roots))
        if job == "scan:similar":
            self.results_ready.add("similar")
            self.loader.clear()
            self.review.load(res, self.settings.protected)
            st = res.stats
            self.status.setText(t("status.similar", photos=f"{st.photos:,}", groups=len(res.groups),
                                  secs=f"{st.seconds:.1f}", cached=f"{st.from_cache:,}",
                                  device=res.device))
            if self.current == "similar":
                self.stack.setCurrentWidget(self.review)
            if not res.groups:
                self.toast.show_message(t("toast.no_groups"), "success")
            if st.errors:
                self.toast.show_message(t("toast.errors", n=len(st.errors)), "error",
                                        t("toast.show"), lambda: self._show_errors(st.errors))
            elif st.skipped_cloud:
                self.toast.show_message(t("toast.cloud", n=st.skipped_cloud), "info")
        elif job.startswith("scan:"):
            key = job[5:]
            self.results_ready.add(key)
            if key not in self.tool_pages:
                p = ToolPage(self.loader)
                p.toast.connect(lambda m, k: self.toast.show_message(m, k))
                p.remove_requested.connect(lambda items, key=key: self.remove_items(key, items, "remove"))
                p.move_requested.connect(lambda items, key=key: self.remove_items(key, items, "move"))
                self.tool_pages[key] = p
                self.stack.addWidget(p)
            self.tool_pages[key].load(key, res)
            self.status.setText(t("tool.found", n=len(res.items),
                                  size=human_size(sum(i.size for i in res.items))))
            if self.current == key:
                self.stack.setCurrentWidget(self.tool_pages[key])
        elif job.startswith("remove"):
            self._removed(job, res)
        elif job == "undo":
            self.toast.show_message(t("toast.restored", n=res.moved), "success")
            if res.failed:
                self._show_errors([(str(p), e) for p, e in res.failed])
            self.history.refresh()
        self.navigate(self.current) if not job.startswith("remove") else None

    def _failed(self, tb: str) -> None:
        self.job = ""
        self.folders.scan.setEnabled(bool(self.settings.roots))
        QMessageBox.critical(self, APP_NAME, tb[-3000:])
        self.navigate(self.current)

    def _cancelled(self) -> None:
        self.job = ""
        self.folders.scan.setEnabled(bool(self.settings.roots))
        self.toast.show_message(t("toast.cancelled"), "info")
        self.navigate(self.current)

    def _show_errors(self, errors) -> None:
        txt = "\n".join(f"{p}\n    {e}" for p, e in errors[:60])
        if len(errors) > 60:
            txt += f"\n… +{len(errors) - 60}"
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setText(t("toast.errors", n=len(errors)))
        box.setDetailedText(txt)
        box.exec()

    # ------------------------------------------------------------------ removal
    def _confirm(self, n: int, size: int, move_to: Path | None) -> bool:
        if move_to:
            text = t("confirm.move", n=n, size=human_size(size), folder=str(move_to))
        elif self.settings.removal == "recycle":
            text = t("confirm.recycle", n=n, size=human_size(size))
        else:
            text = t("confirm.quarantine", n=n, size=human_size(size))
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setIcon(QMessageBox.Question)
        box.setText(f"<b>{t('confirm.title', n=n)}</b>")
        box.setInformativeText(text)
        ok = box.addButton(t("confirm.ok"), QMessageBox.AcceptRole)
        box.addButton(t("confirm.cancel"), QMessageBox.RejectRole)
        box.setDefaultButton(ok)
        box.exec()
        return box.clickedButton() is ok

    def _executor(self, mode: str) -> ActionExecutor | None:
        target = None
        if mode == "move":
            d = QFileDialog.getExistingDirectory(self, t("review.move_to_folder"))
            if not d:
                return None
            target = Path(d)
        ex = ActionExecutor(self.catalog, "move" if target else self.settings.removal,
                            target_dir=target)
        return ex

    def remove_photos(self, ids: list[int], mode: str) -> None:
        st = self.review.state
        if not ids or st is None or self._busy():
            return
        for g in st.groups:   # final guard
            if g.ids and all(i in st.checked for i in g.ids):
                QMessageBox.warning(self, APP_NAME, t("review.guard"))
                return
        ex = self._executor(mode)
        if ex is None:
            return
        assets = [st.assets[i] for i in ids]
        if not self._confirm(len(assets), sum(a.size for a in assets), ex.target_dir):
            return
        roots = self.folders.roots()
        _job = "remove:similar"
        self._last_exec = ex
        self._run(_job, lambda progress, cancel: ex.remove_assets(assets, roots))

    def remove_items(self, key: str, items, mode: str) -> None:
        if not items or self._busy():
            return
        ex = self._executor(mode)
        if ex is None:
            return
        if not self._confirm(len(items), sum(i.size for i in items), ex.target_dir):
            return
        assets = [Asset(id=k, primary=i.path, size=i.size, mtime=i.mtime)
                  for k, i in enumerate(items)]
        roots = self.folders.roots()
        _job = "remove:" + key
        self._last_exec = ex
        self._last_items = {k: str(i.path) for k, i in enumerate(items)}
        self._run(_job, lambda progress, cancel: ex.remove_assets(assets, roots))

    def _removed(self, job: str, res) -> None:
        key = job.split(":", 1)[1]
        if key == "similar":
            self.review.drop_assets(res.done_assets)
        elif key in self.tool_pages:
            self.tool_pages[key].drop_paths({self._last_items[k] for k in res.done_assets})
        n = len(res.done_assets)
        msg = t("toast.removed", n=n, size=human_size(res.bytes))
        if res.failed:
            self._show_errors([(str(p), e) for p, e in res.failed])
        sid = res.session_id
        self.toast.show_message(msg, "success", t("toast.undo"), lambda: self.undo_session(sid),
                                ms=12000)

    def undo_session(self, sid: str) -> None:
        if self._busy():
            return
        ex = ActionExecutor(self.catalog)
        _job = "undo"
        self._run(_job, lambda progress, cancel: ex.undo_session(sid))

    def ignore_group(self, gi: int) -> None:
        st = self.review.state
        g = st.groups[gi]
        for a, b in itertools.combinations(g.ids, 2):
            self.catalog.ignore_paths(str(st.assets[a].primary), str(st.assets[b].primary))
        self.review.remove_group(gi)
        self.toast.show_message(t("toast.ignored"), "info")

    # ------------------------------------------------------------------ settings
    def _theme(self, mode: str) -> None:
        from PySide6.QtWidgets import QApplication
        theme.apply(QApplication.instance(), mode)
        self.toast.show_message(t("settings.restart_note"), "info")

    def _clear_cache(self) -> None:
        import shutil

        from ..core.paths import thumbs_dir
        c = FeatureCache()
        c.clear()
        c.close()
        shutil.rmtree(thumbs_dir(), ignore_errors=True)
        self.loader.clear()
        self.toast.show_message(t("toast.cache_cleared"), "success")

    def _clear_ignored(self) -> None:
        self.catalog.clear_ignored()
        self.toast.show_message(t("toast.ignored_cleared"), "success")

    def closeEvent(self, e) -> None:
        self.runner.shutdown()
        self.settings.save()
        super().closeEvent(e)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if self.toast.isVisible():
            p = self.toast.parentWidget()
            self.toast.move((p.width() - self.toast.width()) // 2, p.height() - 92)


_ = (icon, Qt)
