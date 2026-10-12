"""Generic results page for the file tools (duplicates, big files, empty folders, ...)."""

from __future__ import annotations

import csv
import os
import re
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QMenu,
    QSplitter,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from ..core.tools import ToolResult
from .i18n import t
from .icons import icon
from .imageloader import ImageLoader
from .theme import T, human_size
from .viewers import ZoomView
from .widgets import btn, label, open_file, open_in_explorer

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".heic", ".heif", ".tif", ".tiff",
             ".avif"}
ROLE_ITEM = Qt.UserRole + 1


class ToolPage(QWidget):
    remove_requested = Signal(list)        # list[Item]
    move_requested = Signal(list)
    toast = Signal(str, str)

    def __init__(self, loader: ImageLoader):
        super().__init__()
        self.loader = loader
        self.result: ToolResult | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar = QWidget()
        bar.setObjectName("Toolbar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(18, 10, 14, 10)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.title = label("", "title")
        self.sub = label("", "caption")
        col.addWidget(self.title)
        col.addWidget(self.sub)
        bl.addLayout(col, 1)
        self.expand_b = btn(t("tool.expand"), "ghost")
        self.expand_b.clicked.connect(lambda: self.tree.expandAll())
        self.select_b = QToolButton()
        self.select_b.setText("  " + t("select.menu"))
        self.select_b.setIcon(icon("list-checks", "#FFFFFF", 18, active="#FFFFFF"))
        self.select_b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.select_b.setPopupMode(QToolButton.InstantPopup)
        self.select_b.setStyleSheet(
            f"QToolButton {{ background: {T['accent_fill']}; color: white; border: 1px solid {T['accent_fill']}; }}"
            f"QToolButton:hover {{ background: {T['accent_fill_hover']}; }}")
        bl.addWidget(self.expand_b)
        bl.addWidget(self.select_b)
        root.addWidget(bar)

        split = QSplitter(Qt.Horizontal)
        self.tree = QTreeView()
        self.tree.setAlternatingRowColors(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setIconSize(QSize(16, 16))
        self.tree.setSortingEnabled(True)
        self.tree.doubleClicked.connect(self._open)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._ctx)
        split.addWidget(self.tree)
        right = QWidget()
        right.setObjectName("Inspector")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(16, 16, 16, 16)
        rv.addWidget(label(t("inspector.title"), "overline"))
        self.view = ZoomView()
        rv.addWidget(self.view, 1)
        self.info = label("", "caption", wrap=True)
        rv.addWidget(self.info)
        right.setMinimumWidth(280)
        split.addWidget(right)
        split.setSizes([900, 360])
        root.addWidget(split, 1)

        ab = QWidget()
        ab.setObjectName("ActionBar")
        al = QHBoxLayout(ab)
        al.setContentsMargins(18, 10, 16, 10)
        self.summary = label("", "section")
        al.addWidget(self.summary, 1)
        self.csv_b = btn(t("review.export_csv"), "ghost", "download")
        self.move_b = btn(t("review.move_to_folder"), "", "move")
        self.remove_b = btn(t("review.remove"), "danger", "trash")
        for b in (self.csv_b, self.move_b, self.remove_b):
            al.addWidget(b)
        root.addWidget(ab)
        self.csv_b.clicked.connect(self.export_csv)
        self.move_b.clicked.connect(lambda: self.move_requested.emit(self.checked_items()))
        self.remove_b.clicked.connect(lambda: self.remove_requested.emit(self.checked_items()))
        loader.loaded.connect(lambda k: self._current_preview())
        self.model = QStandardItemModel()
        self.tree.setModel(self.model)
        self.tree.selectionModel().currentChanged.connect(lambda *_: self._current_preview())
        self.model.itemChanged.connect(self._item_changed)
        self._guard = False

    # ------------------------------------------------------------------ load
    def load(self, tool: str, res: ToolResult) -> None:
        self.result = res
        self.tool = tool
        self.title.setText(t("nav." + tool))
        self.model.clear()
        self.model.setHorizontalHeaderLabels([t("col.name"), t("col.folder"), t("col.size"),
                                              t("col.modified"), t("col.info")])
        grouped = res.keep_one
        total = 0
        for gi, g in enumerate(res.groups, 1):
            if grouped:
                parent = QStandardItem(t("tool.group", n=gi, count=len(g),
                                         size=human_size(g[0].size)))
                parent.setEditable(False)
                f = parent.font()
                f.setBold(True)
                parent.setFont(f)
                row = [parent] + [self._ro("") for _ in range(4)]
                self.model.appendRow(row)
                for it in g:
                    parent.appendRow(self._row(it))
            else:
                self.model.appendRow(self._row(g[0]))
            total += sum(i.size for i in g)
        self.tree.expandAll()
        hh = self.tree.header()
        hh.setSectionResizeMode(0, QHeaderView.Interactive)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        self.tree.setColumnWidth(0, 300)
        self.tree.setColumnWidth(2, 90)
        self.tree.setColumnWidth(3, 130)
        self.expand_b.setVisible(grouped)
        n = len(res.items)
        self.sub.setText(t("tool.found", n=n, size=human_size(total)) +
                         (f"  ·  {t('tool.errors', n=res.errors)}" if res.errors else ""))
        self.select_b.setMenu(self._menu(grouped))
        self.update_summary()
        first = self.model.index(0, 0)
        if first.isValid():
            if self.model.hasChildren(first):
                first = self.model.index(0, 0, first)
            self.tree.setCurrentIndex(first)

    def _ro(self, text: str) -> QStandardItem:
        it = QStandardItem(text)
        it.setEditable(False)
        return it

    def _row(self, it) -> list[QStandardItem]:
        name = QStandardItem(it.path.name)
        name.setEditable(False)
        name.setCheckable(True)
        name.setData(it, ROLE_ITEM)
        name.setIcon(icon("folder" if it.is_dir else "files", T["text_secondary"], 16))
        size = self._ro(human_size(it.size) if not it.is_dir else "")
        size.setData(it.size, Qt.UserRole)
        try:
            mod = datetime.fromtimestamp(it.mtime).strftime("%d.%m.%Y %H:%M") if it.mtime else ""
        except (OverflowError, OSError, ValueError):
            mod = ""
        info = self._ro(it.info)
        if it.info:
            info.setToolTip(it.info)
        return [name, self._ro(str(it.path.parent)), size, self._ro(mod), info]

    # ------------------------------------------------------------------ selection
    def _leaf_items(self):
        for r in range(self.model.rowCount()):
            top = self.model.item(r, 0)
            if top.hasChildren():
                yield top, [top.child(i, 0) for i in range(top.rowCount())]
            else:
                yield None, [top]

    def checked_items(self) -> list:
        out = []
        for _, leaves in self._leaf_items():
            out += [x.data(ROLE_ITEM) for x in leaves if x.checkState() == Qt.Checked]
        return out

    def _item_changed(self, item: QStandardItem) -> None:
        if self._guard or not item.isCheckable():
            return
        parent = item.parent()
        if parent is not None and self.result and self.result.keep_one:
            kids = [parent.child(i, 0) for i in range(parent.rowCount())]
            if all(k.checkState() == Qt.Checked for k in kids):
                self._guard = True
                item.setCheckState(Qt.Unchecked)
                self._guard = False
                self.toast.emit(t("review.guard"), "info")
        self.update_summary()

    def _set_checks(self, fn) -> None:
        """fn(leaves) -> set of leaf indices to check (per group)."""
        self._guard = True
        for parent, leaves in self._leaf_items():
            want = fn(leaves)
            if parent is not None and len(want) >= len(leaves):
                want = set(list(want)[1:]) if leaves else want
            for i, leaf in enumerate(leaves):
                leaf.setCheckState(Qt.Checked if i in want else Qt.Unchecked)
        self._guard = False
        self.update_summary()

    def _menu(self, grouped: bool) -> QMenu:
        m = QMenu(self)
        if grouped:
            def except_by(key, largest=True):
                def fn(leaves):
                    items = [x.data(ROLE_ITEM) for x in leaves]
                    keep = (max if largest else min)(range(len(items)), key=lambda i: key(items[i]))
                    return set(range(len(items))) - {keep}
                return fn
            m.addAction(t("rule.except_oldest"), lambda: self._set_checks(except_by(lambda i: i.mtime, False)))
            m.addAction(t("rule.except_newest"), lambda: self._set_checks(except_by(lambda i: i.mtime)))
            m.addAction(t("rule.except_shortest_path"),
                        lambda: self._set_checks(except_by(lambda i: len(str(i.path)), False)))
            m.addAction(t("rule.except_longest_path"),
                        lambda: self._set_checks(except_by(lambda i: len(str(i.path)))))
            m.addAction(t("rule.folder_priority"), self._folder_rule)
        else:
            m.addAction(t("select.all"), lambda: self._set_checks(lambda lv: set(range(len(lv)))))
        m.addAction(t("rule.regex"), self._regex_rule)
        m.addSeparator()
        m.addAction(t("select.invert"), lambda: self._set_checks(
            lambda lv: {i for i, x in enumerate(lv) if x.checkState() != Qt.Checked}))
        m.addAction(t("select.clear"), lambda: self._set_checks(lambda lv: set()))
        return m

    def _folder_rule(self):
        d = QFileDialog.getExistingDirectory(self, t("rule.folder_priority_q"))
        if not d:
            return
        dn = os.path.normcase(d).rstrip("\\/") + os.sep

        def fn(leaves):
            items = [x.data(ROLE_ITEM) for x in leaves]
            inside = [i for i, it in enumerate(items) if os.path.normcase(str(it.path)).startswith(dn)]
            keep = inside[0] if inside else 0
            return set(range(len(items))) - {keep}
        self._set_checks(fn)

    def _regex_rule(self):
        v, ok = QInputDialog.getText(self, t("rule.regex"), t("rule.regex_q"))
        if not ok or not v.strip():
            return
        try:
            rx = re.compile(v.strip(), re.I)
        except re.error as e:
            self.toast.emit(str(e), "error")
            return
        self._set_checks(lambda lv: {i for i, x in enumerate(lv)
                                     if rx.search(str(x.data(ROLE_ITEM).path))})

    def update_summary(self) -> None:
        items = self.checked_items()
        self.summary.setText(t("review.summary_files", n=len(items),
                               size=human_size(sum(i.size for i in items))))
        self.remove_b.setEnabled(bool(items))
        self.move_b.setEnabled(bool(items) and not any(i.is_dir for i in items))

    # ------------------------------------------------------------------ preview / ctx
    def _current_item(self):
        idx = self.tree.currentIndex()
        if not idx.isValid():
            return None
        it0 = self.model.itemFromIndex(idx.siblingAtColumn(0))
        return it0.data(ROLE_ITEM) if it0 else None

    def _current_preview(self):
        it = self._current_item()
        if it is None:
            return
        self.info.setText(f"{it.path}\n{human_size(it.size)}" + (f"\n{it.info}" if it.info else ""))
        if it.path.suffix.lower() in IMAGE_EXT and it.size:
            pm = self.loader.get(None, it.path, 1600, full=True)
            self.view.set_pixmap(pm)
        else:
            self.view.set_pixmap(None)

    def _open(self, idx):
        it = self._current_item()
        if it:
            open_file(it.path)

    def _ctx(self, pos):
        it = self._current_item()
        if it is None:
            return
        m = QMenu(self)
        m.addAction(t("info.open"), lambda: open_file(it.path))
        m.addAction(t("info.show"), lambda: open_in_explorer(it.path))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def export_csv(self) -> None:
        if not self.result:
            return
        path, _ = QFileDialog.getSaveFileName(self, t("review.export_csv"), f"keepframe_{self.tool}.csv",
                                              "CSV (*.csv)")
        if not path:
            return
        checked = {str(i.path) for i in self.checked_items()}
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["group", "path", "size", "modified", "info", "checked"])
            for gi, g in enumerate(self.result.groups, 1):
                for it in g:
                    w.writerow([gi, str(it.path), it.size, it.mtime, it.info,
                                int(str(it.path) in checked)])
        self.toast.emit(t("review.exported", path=Path(path).name), "success")

    def drop_paths(self, paths: set[str]) -> None:
        if not self.result:
            return
        groups = []
        for g in self.result.groups:
            g2 = [i for i in g if str(i.path) not in paths]
            if (self.result.keep_one and len(g2) > 1) or (not self.result.keep_one and g2):
                groups.append(g2)
        self.result.groups = groups
        self.load(self.tool, self.result)
