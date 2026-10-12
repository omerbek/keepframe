"""Reusable widgets: buttons, folder bar with chips, toast, stat cards, empty states."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QListView,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from .i18n import t
from .icons import icon, pixmap
from .theme import T


def btn(text: str = "", variant: str = "", icon_name: str | None = None, tip: str = "",
        checkable: bool = False, icon_color: str | None = None) -> QPushButton:
    b = QPushButton(text)
    if variant:
        b.setProperty("variant", variant)
    if icon_name:
        col = icon_color or (T["text_on_accent"] if variant in ("primary", "danger")
                             else T["text_secondary"])
        b.setIcon(icon(icon_name, col, 18, active=col if variant in ("primary", "danger") else None))
        b.setIconSize(QSize(16, 16))
    if tip:
        b.setToolTip(tip)
    b.setCheckable(checkable)
    b.setCursor(Qt.PointingHandCursor)
    return b


def label(text: str = "", role: str = "", wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    if role:
        lab.setProperty("role", role)
    lab.setWordWrap(wrap)
    return lab


def repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def pick_folders(parent: QWidget, title: str) -> list[str]:
    """Folder dialog that allows selecting MANY folders at once (Ctrl/Shift+click)."""
    dlg = QFileDialog(parent, title)
    dlg.setFileMode(QFileDialog.Directory)
    dlg.setOption(QFileDialog.ShowDirsOnly, True)
    dlg.setOption(QFileDialog.DontUseNativeDialog, True)
    for view in dlg.findChildren(QListView) + dlg.findChildren(QTreeView):
        view.setSelectionMode(QAbstractItemView.ExtendedSelection)
    if dlg.exec():
        return [f for f in dlg.selectedFiles() if os.path.isdir(f)]
    return []


class FolderChip(QFrame):
    removed = Signal(str)
    toggled_protected = Signal(str)

    def __init__(self, path: str, protected: bool = False):
        super().__init__()
        self.path = path
        self.setProperty("role", "chip")
        self.setFixedHeight(28)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 4, 0)
        lay.setSpacing(6)
        ic = QLabel()
        ic.setPixmap(pixmap("lock" if protected else "folder",
                            T["warning"] if protected else T["text_secondary"], 14))
        name = QLabel()
        fm = QFontMetrics(name.font())
        name.setText(fm.elidedText(path, Qt.ElideMiddle, 230))
        name.setToolTip(path + ("\n" + t("folder.protected_tip") if protected else ""))
        x = btn("", "chip-close", "x", t("folder.remove"))
        x.clicked.connect(lambda: self.removed.emit(self.path))
        lay.addWidget(ic)
        lay.addWidget(name)
        lay.addWidget(x)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.protected = protected

    def _menu(self, pos):
        m = QMenu(self)
        m.addAction(t("folder.unprotect") if self.protected else t("folder.protect"),
                    lambda: self.toggled_protected.emit(self.path))
        m.addAction(t("folder.open"), lambda: open_in_explorer(Path(self.path), select=False))
        m.addSeparator()
        m.addAction(t("folder.remove"), lambda: self.removed.emit(self.path))
        m.exec(self.mapToGlobal(pos))


class FolderBar(QWidget):
    """Top bar: page title, folder chips (drag & drop, multi-add), Scan button."""

    changed = Signal()
    scan_clicked = Signal()

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.setObjectName("TopBar")
        self.setAcceptDrops(True)
        self.setFixedHeight(60)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 0, 16, 0)
        lay.setSpacing(10)
        self.title = label("", "section")
        self.title.setMinimumWidth(150)
        lay.addWidget(self.title)
        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QFrame.NoFrame)
        self.area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.area.setFixedHeight(44)
        inner = QWidget()
        inner.setObjectName("Transparent")
        self.chips = QHBoxLayout(inner)
        self.chips.setContentsMargins(0, 8, 0, 8)
        self.chips.setSpacing(6)
        self.chips.addStretch()
        self.area.setWidget(inner)
        self.area.setStyleSheet("background: transparent;")
        lay.addWidget(self.area, 1)
        self.hint = label(t("folder.drop_hint"), "muted")
        lay.addWidget(self.hint)
        add = btn(t("folder.add"), "", "folder-plus")
        menu = QMenu(add)
        menu.addAction(t("folder.add_many"), self.add_dialog)
        menu.addAction(t("folder.paste"), self.add_from_clipboard)
        menu.addSeparator()
        menu.addAction(t("folder.clear"), self.clear)
        add.clicked.connect(self.add_dialog)
        add.setContextMenuPolicy(Qt.CustomContextMenu)
        self.add_menu = menu
        more = QPushButton()
        more.setProperty("variant", "icon")
        more.setIcon(icon("chevron-down"))
        more.setMenu(menu)
        lay.addWidget(add)
        lay.addWidget(more)
        self.scan = btn(t("scan.start"), "primary", "scan")
        self.scan.clicked.connect(self.scan_clicked)
        lay.addWidget(self.scan)
        self.refresh()

    # --- data -------------------------------------------------------------------
    def roots(self) -> list[Path]:
        return [Path(p) for p in self.settings.roots]

    def add(self, paths: list[str]) -> None:
        cur = {os.path.normcase(p) for p in self.settings.roots}
        for p in paths:
            p = os.path.normpath(p)
            if os.path.isdir(p) and os.path.normcase(p) not in cur:
                self.settings.roots.append(p)
                cur.add(os.path.normcase(p))
        self.settings.save()
        self.refresh()
        self.changed.emit()

    def remove(self, path: str) -> None:
        self.settings.roots = [p for p in self.settings.roots if p != path]
        self.settings.protected = [p for p in self.settings.protected if p != path]
        self.settings.save()
        self.refresh()
        self.changed.emit()

    def toggle_protected(self, path: str) -> None:
        if path in self.settings.protected:
            self.settings.protected.remove(path)
        else:
            self.settings.protected.append(path)
        self.settings.save()
        self.refresh()

    def clear(self) -> None:
        self.settings.roots, self.settings.protected = [], []
        self.settings.save()
        self.refresh()
        self.changed.emit()

    def add_dialog(self) -> None:
        self.add(pick_folders(self, t("folder.add_many")))

    def add_from_clipboard(self) -> None:
        text = QGuiApplication.clipboard().text()
        self.add([ln.strip().strip('"') for ln in text.splitlines() if ln.strip()])

    def refresh(self) -> None:
        while self.chips.count() > 1:
            w = self.chips.takeAt(0).widget()
            if w:
                w.deleteLater()
        for p in self.settings.roots:
            chip = FolderChip(p, p in self.settings.protected)
            chip.removed.connect(self.remove)
            chip.toggled_protected.connect(self.toggle_protected)
            self.chips.insertWidget(self.chips.count() - 1, chip)
        self.hint.setVisible(not self.settings.roots)
        self.scan.setEnabled(bool(self.settings.roots))

    # --- drag & drop --------------------------------------------------------------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])


class StatCard(QFrame):
    def __init__(self, caption: str, value: str = "–", role: str = ""):
        super().__init__()
        self.setProperty("role", "card")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(2)
        self.value = label(value, "stat")
        if role:
            self.value.setStyleSheet(f"color: {T[role]};")
        lay.addWidget(self.value)
        lay.addWidget(label(caption, "caption"))

    def set(self, v: str) -> None:
        self.value.setText(v)


class EmptyState(QWidget):
    def __init__(self, icon_name: str, title: str, text: str, button: QPushButton | None = None,
                 dropzone: bool = False):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignCenter)
        box = QFrame()
        if dropzone:
            box.setProperty("role", "dropzone")
        box.setMaximumWidth(520)
        box.setMinimumWidth(420)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(40, 40, 40, 40)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignCenter)
        circle = QLabel()
        circle.setFixedSize(88, 88)
        circle.setAlignment(Qt.AlignCenter)
        circle.setStyleSheet(f"background: {T['bg_card']}; border-radius: 44px;")
        circle.setPixmap(pixmap(icon_name, T["text_muted"], 40))
        lay.addWidget(circle, alignment=Qt.AlignCenter)
        lay.addSpacing(6)
        tl = label(title, "title")
        tl.setAlignment(Qt.AlignCenter)
        lay.addWidget(tl)
        tx = label(text, "secondary", wrap=True)
        tx.setAlignment(Qt.AlignCenter)
        lay.addWidget(tx)
        if button:
            lay.addSpacing(8)
            lay.addWidget(button, alignment=Qt.AlignCenter)
        outer.addWidget(box, alignment=Qt.AlignCenter)


class Toast(QFrame):
    """Bottom-centre snackbar with an optional action (e.g. Undo)."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setProperty("role", "toast")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 6, 8, 6)
        lay.setSpacing(12)
        self.ic = QLabel()
        self.text = QLabel()
        self.action = btn("", "link")
        self.close_b = btn("", "chip-close", "x")
        self.close_b.clicked.connect(self.hide)
        lay.addWidget(self.ic)
        lay.addWidget(self.text, 1)
        lay.addWidget(self.action)
        lay.addWidget(self.close_b)
        self.setMinimumWidth(380)
        self.setFixedHeight(48)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)
        self.fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.fx)
        self.anim = QPropertyAnimation(self.fx, b"opacity", self)
        self.anim.setDuration(160)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self._cb = None
        self.action.clicked.connect(self._do)
        self.hide()

    def _do(self):
        self.hide()
        if self._cb:
            self._cb()

    def show_message(self, text: str, kind: str = "success", action: str = "",
                     callback=None, ms: int = 8000) -> None:
        name, col = {"success": ("check", T["success"]), "error": ("alert", T["danger"]),
                     "info": ("info", T["info"])}.get(kind, ("info", T["info"]))
        self.ic.setPixmap(pixmap(name, col, 18))
        self.text.setText(text)
        self.action.setText(action)
        self.action.setVisible(bool(action))
        self._cb = callback
        self.adjustSize()
        p = self.parentWidget()
        w = min(max(self.sizeHint().width(), 380), p.width() - 40)
        self.resize(w, 48)
        self.move((p.width() - w) // 2, p.height() - 48 - 44)
        self.raise_()
        self.show()
        self.anim.stop()
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.start()
        self.timer.start(ms)


def open_in_explorer(path: Path, select: bool = True) -> None:
    import subprocess
    import sys

    try:
        if sys.platform == "win32":
            if select and path.exists():
                subprocess.Popen(["explorer", "/select,", str(path)])
            else:
                os.startfile(str(path if path.is_dir() else path.parent))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R" if select else "", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path if path.is_dir() else path.parent)])
    except Exception:
        pass


def open_file(path: Path) -> None:
    import subprocess
    import sys

    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open" if sys.platform != "darwin" else "open", str(path)])
    except Exception:
        pass


def hspacer() -> QWidget:
    w = QWidget()
    w.setObjectName("Transparent")
    w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    return w
