"""Zoomable photo views: full-window preview and synced side-by-side compare."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QKeyEvent, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ..core.types import Asset
from .i18n import reason_text, t
from .icons import icon
from .theme import T, human_size
from .widgets import btn, label


class ZoomView(QGraphicsView):
    """Wheel = zoom at cursor, drag = pan, double-click = fit / 100%."""

    view_changed = Signal(object, float, float)      # transform, h-fraction, v-fraction

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Matte")
        self.setScene(QGraphicsScene(self))
        self.item = QGraphicsPixmapItem()
        self.item.setTransformationMode(Qt.SmoothTransformation)
        self.scene().addItem(self.item)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.fitted = True
        self.natural = QRectF()     # size of the ORIGINAL photo, to compute true 100%
        self._sync_block = False
        self.horizontalScrollBar().valueChanged.connect(self._emit)
        self.verticalScrollBar().valueChanged.connect(self._emit)

    def set_pixmap(self, pm: QPixmap | None, natural_w: int = 0, natural_h: int = 0) -> None:
        old = self.item.pixmap()
        rel = None
        if not self.fitted and not old.isNull() and pm is not None:
            rel = self._fractions()
        if pm is None:
            pm = QPixmap()
        # keep scene coordinates in "original pixels" so swapping thumb -> full is seamless
        w = natural_w or pm.width()
        h = natural_h or pm.height()
        self.item.setPixmap(pm)
        if pm.width():
            self.item.setScale(w / pm.width())
        self.natural = QRectF(0, 0, w, h)
        self.scene().setSceneRect(self.natural)
        if self.fitted or rel is None:
            self.fit()
        else:
            self._restore(rel)

    def fit(self) -> None:
        if self.natural.isEmpty():
            return
        self.fitInView(self.natural, Qt.KeepAspectRatio)
        self.fitted = True
        self._emit()

    def actual(self) -> None:
        self.setTransform(QTransform())     # 1 scene unit = 1 original pixel = 1 screen px
        self.fitted = False
        self._emit()

    def toggle_zoom(self) -> None:
        self.actual() if self.fitted else self.fit()

    def zoom_percent(self) -> int:
        return round(self.transform().m11() * 100)

    def wheelEvent(self, e):
        f = 1.25 if e.angleDelta().y() > 0 else 0.8
        s = self.transform().m11() * f
        if s < 0.02 or s > 16:
            return
        self.scale(f, f)
        self.fitted = False
        self._emit()

    def mouseDoubleClickEvent(self, e):
        self.toggle_zoom()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.fitted:
            self.fit()

    def _fractions(self) -> tuple[float, float]:
        c = self.mapToScene(self.viewport().rect().center())
        r = self.natural
        return (c.x() / max(r.width(), 1), c.y() / max(r.height(), 1))

    def _restore(self, rel) -> None:
        self.centerOn(QPointF(rel[0] * self.natural.width(), rel[1] * self.natural.height()))

    def _emit(self, *_):
        if not self._sync_block:
            fx, fy = self._fractions()
            self.view_changed.emit(self.transform(), fx, fy)

    def follow(self, tr: QTransform, fx: float, fy: float, fitted: bool) -> None:
        self._sync_block = True
        if fitted:
            self.fit()
        else:
            self.setTransform(tr)
            self.fitted = False
            self.centerOn(QPointF(fx * self.natural.width(), fy * self.natural.height()))
        self._sync_block = False


def caption_for(a: Asset) -> str:
    from datetime import datetime, timezone

    parts = []
    if a.width:
        parts.append(f"{a.width}×{a.height}")
    parts.append(human_size(a.size))
    if a.taken_at:
        try:
            parts.append(datetime.fromtimestamp(a.taken_at, timezone.utc)
                         .strftime("%d.%m.%Y %H:%M:%S"))
        except (OverflowError, OSError, ValueError):
            pass
    return "  ·  ".join(parts)


class PhotoHeader(QWidget):
    toggled = Signal()

    def __init__(self, closable: bool = False):
        super().__init__()
        self.setObjectName("Matte")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 10, 8)
        lay.setSpacing(10)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.name = label("", "section")
        self.meta = label("", "caption")
        col.addWidget(self.name)
        col.addWidget(self.meta)
        lay.addLayout(col, 1)
        self.badge = label("", "")
        self.badge.setFixedHeight(22)
        lay.addWidget(self.badge, 0, Qt.AlignVCenter)
        self.check = btn(t("review.mark"), "", "trash", checkable=True)
        self.check.clicked.connect(self.toggled)
        lay.addWidget(self.check)
        self.close_b = None
        if closable:
            self.close_b = btn("", "icon", "x", t("common.close_esc"))
            lay.addWidget(self.close_b)

    def set(self, a: Asset, checked: bool, suggested: bool, reasons: list[str], extra: str = ""):
        self.name.setText(a.primary.name)
        txt = caption_for(a)
        if extra:
            txt += "  ·  " + extra
        self.meta.setText(txt + ("\n" + " · ".join(reason_text(r) for r in reasons) if reasons else ""))
        self.badge.setText(("★ " + t("review.suggested")) if suggested else "")
        self.badge.setStyleSheet(
            f"color:#141414;background:{T['warning']};border-radius:9px;padding:2px 8px;"
            "font-size:11px;font-weight:700;" if suggested else "")
        self.check.setChecked(checked)
        self.check.setText(t("review.marked") if checked else t("review.mark"))
        self.check.setProperty("variant", "danger" if checked else "")
        self.check.setIcon(icon("trash", "#FFFFFF" if checked else T["text_secondary"], 16))
        self.check.style().unpolish(self.check)
        self.check.style().polish(self.check)


class PreviewOverlay(QWidget):
    """Full-window viewer for one photo of the current group."""

    closed = Signal()
    navigate = Signal(int)          # +1 / -1
    toggle_check = Signal()
    compare = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("Matte")
        self.setAttribute(Qt.WA_StyledBackground, True)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.header = PhotoHeader(closable=True)
        self.header.close_b.clicked.connect(self.closed)
        self.header.toggled.connect(self.toggle_check)
        v.addWidget(self.header)
        mid = QHBoxLayout()
        mid.setContentsMargins(0, 0, 0, 0)
        self.prev_b = btn("", "icon", "chevron-left", "←")
        self.next_b = btn("", "icon", "chevron-right", "→")
        self.prev_b.clicked.connect(lambda: self.navigate.emit(-1))
        self.next_b.clicked.connect(lambda: self.navigate.emit(1))
        self.view = ZoomView()
        mid.addWidget(self.prev_b)
        mid.addWidget(self.view, 1)
        mid.addWidget(self.next_b)
        v.addLayout(mid, 1)
        foot = QHBoxLayout()
        foot.setContentsMargins(14, 6, 14, 8)
        self.pos_label = label("", "caption")
        self.zoom_label = label("", "caption")
        hint = label(t("preview.hint"), "muted")
        foot.addWidget(self.pos_label)
        foot.addStretch()
        foot.addWidget(hint)
        foot.addStretch()
        foot.addWidget(self.zoom_label)
        v.addLayout(foot)
        self.view.view_changed.connect(lambda *_: self.zoom_label.setText(
            f"{self.view.zoom_percent()} %"))
        self.hide()

    def keyPressEvent(self, e: QKeyEvent):
        k = e.key()
        if k == Qt.Key_Escape or k == Qt.Key_Space:
            self.closed.emit()
        elif k in (Qt.Key_Right, Qt.Key_D):
            self.navigate.emit(1)
        elif k in (Qt.Key_Left, Qt.Key_A):
            self.navigate.emit(-1)
        elif k in (Qt.Key_X, Qt.Key_Delete):
            self.toggle_check.emit()
        elif k == Qt.Key_1:
            self.view.toggle_zoom()
        elif k == Qt.Key_C:
            self.compare.emit()
        else:
            super().keyPressEvent(e)


class ComparePane(QWidget):
    toggled = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("Matte")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.header = PhotoHeader()
        self.header.toggled.connect(self.toggled)
        self.view = ZoomView()
        v.addWidget(self.header)
        v.addWidget(self.view, 1)


class CompareOverlay(QWidget):
    """Two photos side by side; zoom and pan are synchronised (Shift = unsync)."""

    closed = Signal()
    toggle_check = Signal(int)          # pane index
    cycle = Signal(int, int)            # pane index, direction

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("Matte")
        self.setAttribute(Qt.WA_StyledBackground, True)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        top = QHBoxLayout()
        top.setContentsMargins(14, 8, 10, 0)
        top.addWidget(label(t("compare.title"), "section"))
        top.addStretch()
        top.addWidget(label(t("compare.hint"), "muted"))
        self.sync = btn(t("compare.sync"), "ghost", "columns", checkable=True)
        self.sync.setChecked(True)
        top.addWidget(self.sync)
        close = btn("", "icon", "x", t("common.close_esc"))
        close.clicked.connect(self.closed)
        top.addWidget(close)
        v.addLayout(top)
        row = QHBoxLayout()
        row.setSpacing(1)
        self.panes = [ComparePane(), ComparePane()]
        for i, p in enumerate(self.panes):
            p.toggled.connect(lambda i=i: self.toggle_check.emit(i))
            p.view.view_changed.connect(lambda tr, fx, fy, i=i: self._sync(i, tr, fx, fy))
            row.addWidget(p, 1)
        v.addLayout(row, 1)
        self.hide()

    def _sync(self, src: int, tr, fx, fy):
        from PySide6.QtWidgets import QApplication

        if not self.sync.isChecked() or QApplication.keyboardModifiers() & Qt.ShiftModifier:
            return
        other = self.panes[1 - src].view
        other.follow(tr, fx, fy, self.panes[src].view.fitted)

    def keyPressEvent(self, e: QKeyEvent):
        k = e.key()
        if k in (Qt.Key_Escape, Qt.Key_C):
            self.closed.emit()
        elif k == Qt.Key_1:
            for p in self.panes:
                p.view.toggle_zoom()
        elif k == Qt.Key_Right:
            self.cycle.emit(1, 1)
        elif k == Qt.Key_Left:
            self.cycle.emit(1, -1)
        else:
            super().keyPressEvent(e)


class InfoRow(QWidget):
    def __init__(self, key: str):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        k = label(key, "muted")
        k.setFixedWidth(96)
        self.v = QLabel()
        self.v.setWordWrap(True)
        self.v.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(k)
        lay.addWidget(self.v, 1)
