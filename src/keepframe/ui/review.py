"""Review screen for similar / duplicate photo groups.

Nothing is decided for the user: the AI only adds a soft "Suggested" badge. Photos are
checked for removal by hand (X / click) or with rules from the Select menu, and the
guard always keeps at least one photo per group.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import (
    QAbstractListModel,
    QEvent,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QKeySequence, QPainter, QPainterPath, QPen, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QListView,
    QMenu,
    QSlider,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..core import selection as sel
from ..core.pipeline import ScanResult
from ..core.types import Group, GroupKind
from .i18n import reason_text, t
from .icons import icon, pixmap
from .imageloader import ImageLoader
from .theme import T, c, human_size
from .viewers import CompareOverlay, InfoRow, PreviewOverlay, ZoomView
from .widgets import btn, label, open_file, open_in_explorer

GROUP_THUMB = 160
CARD_THUMB = 512


def fmt_time(ts: float | None) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(ts, timezone.utc).strftime("%d.%m.%Y %H:%M")
    except (OverflowError, OSError, ValueError):
        return ""


def rounded(p: QPainter, r: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(r, radius, radius)
    return path


def draw_pixmap_fit(p: QPainter, pm, r: QRect, radius: float = 8, cover: bool = False) -> None:
    if pm is None or pm.isNull():
        return
    s = pm.size().scaled(r.size(), Qt.KeepAspectRatioByExpanding if cover else Qt.KeepAspectRatio)
    dst = QRect(0, 0, s.width(), s.height())
    dst.moveCenter(r.center())
    p.save()
    p.setClipPath(rounded(p, QRectF(r), radius))
    p.drawPixmap(dst, pm)
    p.restore()


# ===================================================================== group list
class GroupListModel(QAbstractListModel):
    def __init__(self, state: sel.SelectionState):
        super().__init__()
        self.state = state
        self.rows: list[int] = list(range(len(state.groups)))
        self.kind_filter = "all"
        self.status_filter = "all"
        self.sort = "default"

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.rows)

    def data(self, idx, role=Qt.DisplayRole):
        if not idx.isValid():
            return None
        if role == Qt.UserRole:
            return self.rows[idx.row()]
        if role == Qt.ToolTipRole:
            g = self.state.groups[self.rows[idx.row()]]
            return f"{len(g.members)} · {t('kind.' + g.kind.value)}"
        return None

    def reclaim(self, gi: int) -> int:
        g = self.state.groups[gi]
        return sum(self.state.assets[i].size for i in g.ids) - max(
            self.state.assets[i].size for i in g.ids)

    def rebuild(self) -> None:
        self.beginResetModel()
        st = self.state
        rows = []
        for gi, g in enumerate(st.groups):
            if self.kind_filter != "all" and g.kind.value != self.kind_filter:
                continue
            n = st.group_checked(gi)
            if self.status_filter == "unreviewed" and gi in st.reviewed:
                continue
            if self.status_filter == "checked" and n == 0:
                continue
            if self.status_filter == "unchecked" and n > 0:
                continue
            rows.append(gi)
        if self.sort == "reclaim":
            rows.sort(key=lambda gi: -self.reclaim(gi))
        elif self.sort == "size":
            rows.sort(key=lambda gi: -len(st.groups[gi].members))
        elif self.sort == "date_new":
            rows.sort(key=lambda gi: -max(st.assets[i].taken_at or 0 for i in st.groups[gi].ids))
        elif self.sort == "date_old":
            rows.sort(key=lambda gi: min(st.assets[i].taken_at or 0 for i in st.groups[gi].ids))
        self.rows = rows
        self.endResetModel()

    def refresh_row(self, gi: int) -> None:
        if gi in self.rows:
            i = self.index(self.rows.index(gi))
            self.dataChanged.emit(i, i)


class GroupDelegate(QStyledItemDelegate):
    H = 86

    def __init__(self, state: sel.SelectionState, loader: ImageLoader, parent=None):
        super().__init__(parent)
        self.state, self.loader = state, loader

    def sizeHint(self, opt, idx):
        return QSize(opt.rect.width(), self.H)

    def paint(self, p: QPainter, opt, idx):
        gi = idx.data(Qt.UserRole)
        g = self.state.groups[gi]
        r = opt.rect.adjusted(8, 3, -8, -3)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        selected = opt.state & QStyle.State_Selected
        hover = opt.state & QStyle.State_MouseOver
        if selected or hover:
            p.setPen(Qt.NoPen)
            p.setBrush(c("selection_bg") if selected else c("bg_hover"))
            p.drawRoundedRect(QRectF(r), 8, 8)
        if selected:
            p.setBrush(c("accent"))
            p.drawRoundedRect(QRectF(r.left(), r.top() + 14, 3, r.height() - 28), 1.5, 1.5)
        n_checked = self.state.group_checked(gi)
        reviewed = gi in self.state.reviewed
        if reviewed and not selected:
            p.setOpacity(0.72)
        # thumbnails strip
        ids = sorted(g.ids, key=lambda i: self.state.assets[i].taken_at or 0)
        tw = 48
        x = r.left() + 12
        y = r.top() + (r.height() - tw) // 2
        shown = ids[:3]
        for k, aid in enumerate(shown):
            a = self.state.assets[aid]
            tr = QRect(x + k * (tw + 4), y, tw, tw)
            p.setPen(Qt.NoPen)
            p.setBrush(c("photo_matte"))
            p.drawRoundedRect(QRectF(tr), 6, 6)
            pm = self.loader.get(a.thumb, a.primary, GROUP_THUMB)
            draw_pixmap_fit(p, pm, tr, 6, cover=True)
            if aid in self.state.checked:
                p.setBrush(QColor(200, 40, 40, 110))
                p.drawRoundedRect(QRectF(tr), 6, 6)
        if len(ids) > 3:
            tr = QRect(x + 2 * (tw + 4), y, tw, tw)
            p.setBrush(QColor(10, 11, 13, 170))
            p.drawRoundedRect(QRectF(tr), 6, 6)
            p.setPen(c("text"))
            f = QFont(opt.font)
            f.setPixelSize(13)
            f.setBold(True)
            p.setFont(f)
            p.drawText(tr, Qt.AlignCenter, f"+{len(ids) - 2}")
        # text
        tx = x + 3 * (tw + 4) + 8
        trect = QRect(tx, r.top() + 12, r.right() - tx - 8, 20)
        f = QFont(opt.font)
        f.setPixelSize(13)
        f.setBold(True)
        p.setFont(f)
        p.setPen(c("text"))
        p.drawText(trect, Qt.AlignLeft | Qt.AlignVCenter,
                   t("review.n_photos", n=len(g.members)))
        # kind chip
        kind_col = {GroupKind.SIMILAR: "info", GroupKind.REENCODED: "warning",
                    GroupKind.EXACT: "accent"}[g.kind]
        f.setPixelSize(10)
        p.setFont(f)
        ktxt = t("kind_short." + g.kind.value).upper()
        kw = p.fontMetrics().horizontalAdvance(ktxt) + 14
        chip = QRectF(tx, r.top() + 36, kw, 18)
        col = c(kind_col)
        bg = QColor(col)
        bg.setAlpha(40)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(chip, 9, 9)
        p.setPen(col)
        p.drawText(chip, Qt.AlignCenter, ktxt)
        # date / status
        f.setBold(False)
        f.setPixelSize(12)
        p.setFont(f)
        p.setPen(c("text_secondary"))
        first = min((self.state.assets[i].taken_at or 0) for i in g.ids)
        p.drawText(QRect(tx, r.top() + 58, r.right() - tx - 8, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   fmt_time(first).split(" ")[0] if first else "")
        if n_checked:
            txt = t("review.n_checked", n=n_checked)
            f.setBold(True)
            p.setFont(f)
            w = p.fontMetrics().horizontalAdvance(txt) + 14
            pill = QRectF(r.right() - w - 8, r.top() + 35, w, 20)
            p.setPen(Qt.NoPen)
            p.setBrush(c("danger_fill"))
            p.drawRoundedRect(pill, 10, 10)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(pill, Qt.AlignCenter, txt)
        elif reviewed:
            p.drawPixmap(r.right() - 26, r.top() + 12, pixmap("check", T["success"], 16))
        p.restore()


# ===================================================================== photo grid
class PhotoModel(QAbstractListModel):
    def __init__(self, state: sel.SelectionState):
        super().__init__()
        self.state = state
        self.gi = -1
        self.ids: list[int] = []

    def set_group(self, gi: int) -> None:
        self.beginResetModel()
        self.gi = gi
        if 0 <= gi < len(self.state.groups):
            g = self.state.groups[gi]
            self.ids = sorted(g.ids, key=lambda i: (self.state.assets[i].taken_at or 0,
                                                    str(self.state.assets[i].primary)))
        else:
            self.ids = []
        self.endResetModel()

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.ids)

    def data(self, idx, role=Qt.DisplayRole):
        if not idx.isValid():
            return None
        if role == Qt.UserRole:
            return self.ids[idx.row()]
        if role == Qt.ToolTipRole:
            return str(self.state.assets[self.ids[idx.row()]].primary)
        return None

    def member(self, aid: int):
        g = self.state.groups[self.gi]
        return next(m for m in g.members if m.asset_id == aid)

    def refresh(self) -> None:
        if self.ids:
            self.dataChanged.emit(self.index(0), self.index(len(self.ids) - 1))


class PhotoDelegate(QStyledItemDelegate):
    FOOT = 74
    toggle = Signal(int)
    open_preview = Signal(int)

    def __init__(self, model: PhotoModel, loader: ImageLoader, parent=None):
        super().__init__(parent)
        self.model, self.loader = model, loader
        self.card_w = 230

    def sizeHint(self, opt, idx):
        return QSize(self.card_w + 12, int(self.card_w * 0.75) + self.FOOT + 12)

    def _rects(self, r: QRect):
        card = r.adjusted(6, 6, -6, -6)
        img = QRect(card.left(), card.top(), card.width(), int(card.width() * 0.75))
        box = QRect(img.right() - 34, img.top() + 8, 26, 26)
        return card, img, box

    def paint(self, p: QPainter, opt, idx):
        st = self.model.state
        aid = idx.data(Qt.UserRole)
        a = st.assets[aid]
        m = self.model.member(aid)
        checked = aid in st.checked
        protected = st.is_protected(aid)
        card, img, box = self._rects(opt.rect)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        selected = opt.state & QStyle.State_Selected
        hover = opt.state & QStyle.State_MouseOver
        # card
        p.setPen(QPen(c("danger") if checked else (c("accent") if selected else
                                                   (c("border_strong") if hover else c("border"))),
                      2 if (checked or selected) else 1))
        p.setBrush(c("bg_card"))
        p.drawRoundedRect(QRectF(card).adjusted(.5, .5, -.5, -.5), 10, 10)
        # image
        p.setPen(Qt.NoPen)
        p.setBrush(c("photo_matte"))
        path = QPainterPath()
        path.addRoundedRect(QRectF(img).adjusted(1, 1, -1, 0), 9, 9)
        p.drawPath(path)
        pm = self.loader.get(a.thumb, a.primary, CARD_THUMB)
        if pm is not None:
            draw_pixmap_fit(p, pm, img.adjusted(1, 1, -1, 0), 9)
        else:
            p.setPen(c("text_muted"))
            p.drawText(img, Qt.AlignCenter, "…")
        if checked:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(12, 12, 14, 140))
            p.drawPath(path)
            p.setBrush(QColor(201, 58, 54, 70))
            p.drawPath(path)
            f = QFont(opt.font)
            f.setPixelSize(11)
            f.setBold(True)
            p.setFont(f)
            txt = t("review.will_remove").upper()
            w = p.fontMetrics().horizontalAdvance(txt) + 16
            pill = QRectF(img.center().x() - w / 2, img.bottom() - 30, w, 22)
            p.setBrush(c("danger_fill"))
            p.drawRoundedRect(pill, 11, 11)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(pill, Qt.AlignCenter, txt)
        # suggested badge
        if m.suggested:
            f = QFont(opt.font)
            f.setPixelSize(11)
            f.setBold(True)
            p.setFont(f)
            txt = t("review.suggested").upper()
            w = p.fontMetrics().horizontalAdvance(txt) + 30
            b = QRectF(img.left() + 8, img.top() + 8, w, 22)
            p.setPen(Qt.NoPen)
            p.setBrush(c("warning"))
            p.drawRoundedRect(b, 11, 11)
            p.drawPixmap(int(b.left()) + 7, int(b.top()) + 4, pixmap("star", "#141414", 14,
                                                                    fill="#141414"))
            p.setPen(QColor("#141414"))
            p.drawText(b.adjusted(18, 0, 0, 0), Qt.AlignCenter, txt)
        # checkbox / lock
        p.setPen(Qt.NoPen)
        if protected:
            p.setBrush(QColor(10, 11, 13, 190))
            p.drawEllipse(box)
            p.drawPixmap(box.adjusted(5, 5, -5, -5), pixmap("lock", T["warning"], 16))
        else:
            if checked:
                p.setBrush(c("danger_fill"))
                p.drawEllipse(box)
                p.drawPixmap(box.adjusted(5, 5, -5, -5), pixmap("check", "#FFFFFF", 16, stroke=2.6))
            elif hover or selected:
                p.setBrush(QColor(10, 11, 13, 160))
                p.setPen(QPen(QColor(236, 237, 239, 220), 1.6))
                p.drawEllipse(box.adjusted(1, 1, -1, -1))
        # footer
        fx = card.left() + 12
        fw = card.width() - 24
        f = QFont(opt.font)
        f.setPixelSize(13)
        f.setBold(True)
        p.setFont(f)
        p.setPen(c("text_muted") if checked else c("text"))
        name = p.fontMetrics().elidedText(a.primary.name, Qt.ElideMiddle, fw)
        p.drawText(QRect(fx, img.bottom() + 8, fw, 18), Qt.AlignLeft | Qt.AlignVCenter, name)
        f.setBold(False)
        f.setPixelSize(12)
        p.setFont(f)
        p.setPen(c("text_secondary"))
        cap = f"{a.width}×{a.height} · {human_size(a.size)}" if a.width else human_size(a.size)
        ts = fmt_time(a.taken_at)
        p.drawText(QRect(fx, img.bottom() + 27, fw, 16), Qt.AlignLeft | Qt.AlignVCenter, cap)
        if ts:
            p.drawText(QRect(fx, img.bottom() + 27, fw, 16), Qt.AlignRight | Qt.AlignVCenter,
                       ts.split(" ")[-1] if " " in ts else ts)
        reasons = " · ".join(reason_text(r) for r in m.reasons[:2])
        if not m.suggested and m.similarity < 0.999:
            reasons = f"{round(m.similarity * 100)}%  ·  " + reasons
        col = c("warning") if m.suggested else (c("danger") if "blurrier" in m.reasons
                                                or "eyes_closed" in m.reasons else c("text_muted"))
        p.setPen(col)
        p.drawText(QRect(fx, img.bottom() + 45, fw, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(reasons, Qt.ElideRight, fw))
        p.restore()

    def editorEvent(self, ev, model, opt, idx):
        if ev.type() == QEvent.MouseButtonRelease and ev.button() == Qt.LeftButton:
            _, _, box = self._rects(opt.rect)
            if box.adjusted(-6, -6, 6, 6).contains(ev.position().toPoint()):
                self.toggle.emit(idx.data(Qt.UserRole))
                return True
        if ev.type() == QEvent.MouseButtonDblClick:
            self.open_preview.emit(idx.data(Qt.UserRole))
            return True
        return False


class PhotoGrid(QListView):
    key_action = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName("PhotoGrid")
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setMouseTracking(True)
        self.setSpacing(0)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.viewport().setAttribute(Qt.WA_Hover, True)
        self.setContentsMargins(12, 12, 12, 12)

    def keyPressEvent(self, e):
        k = e.key()
        mapping = {Qt.Key_X: "toggle", Qt.Key_Delete: "remove", Qt.Key_Space: "preview",
                   Qt.Key_Return: "preview", Qt.Key_Enter: "preview", Qt.Key_C: "compare",
                   Qt.Key_J: "next", Qt.Key_PageDown: "next", Qt.Key_K: "prev",
                   Qt.Key_PageUp: "prev", Qt.Key_N: "next_unreviewed", Qt.Key_R: "rule_next",
                   Qt.Key_U: "keep_all", Qt.Key_I: "invert"}
        if e.modifiers() == Qt.NoModifier and k in mapping:
            self.key_action.emit(mapping[k])
            return
        if e.modifiers() == Qt.NoModifier and Qt.Key_1 <= k <= Qt.Key_9:
            self.key_action.emit(f"num{k - Qt.Key_0}")
            return
        super().keyPressEvent(e)


# ===================================================================== inspector
class Inspector(QWidget):
    def __init__(self, loader: ImageLoader):
        super().__init__()
        self.setObjectName("Inspector")
        self.loader = loader
        self.setMinimumWidth(270)
        self.setMaximumWidth(380)
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(8)
        v.addWidget(label(t("inspector.title"), "overline"))
        self.view = ZoomView()
        self.view.setMinimumHeight(200)
        self.view.setStyleSheet(f"border-radius: 8px; background: {T['photo_matte']};")
        v.addWidget(self.view, 3)
        self.name = label("", "section", wrap=True)
        v.addWidget(self.name)
        self.rows: dict[str, InfoRow] = {}
        for k in ("folder", "resolution", "size", "taken", "camera", "source", "sharpness",
                  "similarity", "reasons"):
            r = InfoRow(t("info." + k))
            self.rows[k] = r
            v.addWidget(r)
        h = QHBoxLayout()
        self.open_b = btn(t("info.open"), "ghost", "external")
        self.show_b = btn(t("info.show"), "ghost", "folder")
        h.addWidget(self.open_b)
        h.addWidget(self.show_b)
        v.addLayout(h)
        v.addStretch(1)
        self.aid = None

    def show_asset(self, state: sel.SelectionState, member, aid: int) -> None:
        self.aid = aid
        a = state.assets[aid]
        f = state.feats.get(aid)
        self.name.setText(a.primary.name)
        vals = {
            "folder": str(a.primary.parent),
            "resolution": f"{a.width} × {a.height}  ({a.pixels / 1e6:.1f} MP)" if a.width else "–",
            "size": human_size(a.size) + (f"  (+{len(a.companions)} " + t("info.companions") + ")"
                                          if a.companions else ""),
            "taken": fmt_time(a.taken_at) or "–",
            "camera": a.camera or "–",
            "source": t("time_source." + (a.time_source or "none")),
            "sharpness": f"{f.sharpness:.0f}" if f else "–",
            "similarity": f"{member.similarity * 100:.1f} %" if member else "–",
            "reasons": " · ".join(reason_text(r) for r in (member.reasons if member else [])),
        }
        for k, r in self.rows.items():
            r.v.setText(vals[k])
        self.open_b.setProperty("path", str(a.primary))
        self.refresh_image(state)

    def refresh_image(self, state) -> None:
        if self.aid is None:
            return
        a = state.assets[self.aid]
        pm = self.loader.get(a.thumb, a.primary, CARD_THUMB)
        self.view.set_pixmap(pm, a.width, a.height)


# ===================================================================== page
class ReviewPage(QWidget):
    remove_requested = Signal(list)         # asset ids
    move_requested = Signal(list)
    ignore_group = Signal(int)              # group index -> "not duplicates"
    status = Signal(str)
    toast = Signal(str, str)

    SCOPES = ("group", "visible", "all")

    def __init__(self, loader: ImageLoader, settings):
        super().__init__()
        self.loader = loader
        self.settings = settings
        self.state: sel.SelectionState | None = None
        self.result: ScanResult | None = None
        self.scope = "group"
        self.focus_id: int | None = None
        self._last_rule = settings.last_rule

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.split = QSplitter(Qt.Horizontal)
        self.split.setChildrenCollapsible(False)
        root.addWidget(self.split, 1)

        # left: groups
        left = QWidget()
        left.setObjectName("Inspector")
        left.setStyleSheet(f"QWidget#Inspector {{ border-left: none; border-right: 1px solid {T['border']}; }}")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 12, 0, 0)
        lv.setSpacing(8)
        head = QHBoxLayout()
        head.setContentsMargins(16, 0, 12, 0)
        self.count_label = label("", "overline")
        head.addWidget(self.count_label)
        head.addStretch()
        lv.addLayout(head)
        fl = QHBoxLayout()
        fl.setContentsMargins(12, 0, 12, 0)
        fl.setSpacing(6)
        self.kind_box = QComboBox()
        for k in ("all", "similar", "reencoded", "exact"):
            self.kind_box.addItem(t("filter.kind." + k), k)
        self.status_box = QComboBox()
        for k in ("all", "unreviewed", "checked", "unchecked"):
            self.status_box.addItem(t("filter.status." + k), k)
        self.sort_box = QComboBox()
        for k in ("default", "reclaim", "size", "date_new", "date_old"):
            self.sort_box.addItem(t("sort." + k), k)
        fl.addWidget(self.kind_box, 1)
        fl.addWidget(self.status_box, 1)
        lv.addLayout(fl)
        sl = QHBoxLayout()
        sl.setContentsMargins(12, 0, 12, 0)
        sl.addWidget(label(t("sort.label"), "muted"))
        sl.addWidget(self.sort_box, 1)
        lv.addLayout(sl)
        self.group_list = QListView()
        self.group_list.setObjectName("GroupList")
        self.group_list.setMouseTracking(True)
        self.group_list.setUniformItemSizes(True)
        self.group_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.group_list.viewport().setAttribute(Qt.WA_Hover, True)
        lv.addWidget(self.group_list, 1)
        left.setMinimumWidth(300)
        left.setMaximumWidth(420)
        self.split.addWidget(left)

        # centre
        center = QWidget()
        cv = QVBoxLayout(center)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        bar = QWidget()
        bar.setObjectName("Toolbar")
        bv = QVBoxLayout(bar)
        bv.setContentsMargins(18, 10, 14, 10)
        bv.setSpacing(8)
        row1 = QHBoxLayout()
        tcol = QVBoxLayout()
        tcol.setSpacing(0)
        self.g_title = label("", "title")
        self.g_sub = label("", "caption")
        self.g_sub.setMinimumWidth(10)
        tcol.addWidget(self.g_title)
        tcol.addWidget(self.g_sub)
        row1.addLayout(tcol, 1)
        zl = QToolButton()
        zl.setIcon(icon("zoom-in"))
        zl.setProperty("variant", "icon")
        zl.setEnabled(False)
        self.size_slider = QSlider(Qt.Horizontal)
        self.size_slider.setRange(150, 420)
        self.size_slider.setValue(settings.card_size)
        self.size_slider.setFixedWidth(110)
        self.size_slider.setToolTip(t("review.card_size"))
        row1.addWidget(zl)
        row1.addWidget(self.size_slider)
        bv.addLayout(row1)
        bl = QHBoxLayout()
        bl.setSpacing(8)
        self.select_b = QToolButton()
        self.select_b.setText("  " + t("select.menu") + "  ▾")
        self.select_b.setIcon(icon("list-checks", T["text_on_accent"], 18, active=T["text_on_accent"]))
        self.select_b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.select_b.setPopupMode(QToolButton.InstantPopup)
        self.select_b.setStyleSheet(
            f"QToolButton {{ background: {T['accent_fill']}; color: white; border: 1px solid {T['accent_fill']}; "
            "padding: 0 12px; }"
            f"QToolButton:hover {{ background: {T['accent_fill_hover']}; }}")
        self.select_menu = self._build_select_menu()
        self.select_b.setMenu(self.select_menu)
        self.notdup_b = btn(t("review.not_duplicates"), "ghost", "check",
                            t("review.not_duplicates_tip"))
        self.compare_b = btn(t("review.compare"), "", "columns", "C")
        self.preview_b = btn(t("review.preview"), "", "maximize", t("key.space"))
        bl.addWidget(self.select_b)
        bl.addWidget(self.preview_b)
        bl.addWidget(self.compare_b)
        bl.addStretch()
        bl.addWidget(self.notdup_b)
        bv.addLayout(bl)
        cv.addWidget(bar)
        self.grid = PhotoGrid()
        cv.addWidget(self.grid, 1)
        self.split.addWidget(center)

        # right
        self.inspector = Inspector(loader)
        self.split.addWidget(self.inspector)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setStretchFactor(2, 0)
        self.split.setSizes([330, 900, 320])

        # bottom action bar
        ab = QWidget()
        ab.setObjectName("ActionBar")
        al = QHBoxLayout(ab)
        al.setContentsMargins(18, 10, 16, 10)
        al.setSpacing(8)
        self.summary = label("", "section")
        self.summary_sub = label(t("review.guard"), "muted")
        sc = QVBoxLayout()
        sc.setSpacing(0)
        sc.addWidget(self.summary)
        sc.addWidget(self.summary_sub)
        al.addLayout(sc, 1)
        self.undo_sel_b = btn(t("review.undo_selection"), "ghost", "undo", "Ctrl+Z")
        self.csv_b = btn(t("review.export_csv"), "ghost", "download")
        self.move_b = btn(t("review.move_to_folder"), "", "move")
        self.remove_b = btn(t("review.remove"), "danger", "trash")
        for b in (self.undo_sel_b, self.csv_b, self.move_b, self.remove_b):
            al.addWidget(b)
        root.addWidget(ab)

        # overlays
        self.preview = PreviewOverlay(self)
        self.compare = CompareOverlay(self)

        # wiring
        self.kind_box.currentIndexChanged.connect(self._filters_changed)
        self.status_box.currentIndexChanged.connect(self._filters_changed)
        self.sort_box.currentIndexChanged.connect(self._filters_changed)
        self.size_slider.valueChanged.connect(self._card_size)
        self.grid.key_action.connect(self._key)
        self.preview_b.clicked.connect(lambda: self.open_preview(self.current_focus()))
        self.compare_b.clicked.connect(self.open_compare)
        self.notdup_b.clicked.connect(self._not_duplicates)
        self.remove_b.clicked.connect(lambda: self.remove_requested.emit(sorted(self.state.checked)))
        self.move_b.clicked.connect(lambda: self.move_requested.emit(sorted(self.state.checked)))
        self.csv_b.clicked.connect(self.export_csv)
        self.undo_sel_b.clicked.connect(self.undo_selection)
        self.preview.closed.connect(self.close_preview)
        self.preview.navigate.connect(self._preview_nav)
        self.preview.toggle_check.connect(lambda: self.toggle(self.preview_id))
        self.preview.compare.connect(self.open_compare)
        self.compare.closed.connect(self.close_compare)
        self.compare.toggle_check.connect(lambda i: self.toggle(self.compare_ids[i]))
        self.compare.cycle.connect(self._compare_cycle)
        self.inspector.open_b.clicked.connect(
            lambda: self.inspector.aid is not None and open_file(self.state.assets[self.inspector.aid].primary))
        self.inspector.show_b.clicked.connect(
            lambda: self.inspector.aid is not None and open_in_explorer(self.state.assets[self.inspector.aid].primary))
        loader.loaded.connect(self._image_loaded)
        QShortcut(QKeySequence.Undo, self, self.undo_selection)
        self.preview_id = None
        self.compare_ids = [None, None]
        self._repaint = QTimer(self)
        self._repaint.setSingleShot(True)
        self._repaint.setInterval(30)
        self._repaint.timeout.connect(self._do_repaint)

    # ------------------------------------------------------------------ setup
    def _build_select_menu(self) -> QMenu:
        m = QMenu(self)
        m.addSection(t("select.scope"))
        grp = QActionGroup(m)
        for s in self.SCOPES:
            a = QAction(t("select.scope." + s), m, checkable=True)
            a.setChecked(s == self.scope)
            a.triggered.connect(lambda _=False, s=s: setattr(self, "scope", s))
            grp.addAction(a)
            m.addAction(a)
        m.addSection(t("select.rules"))
        for key in ("except_suggested", "except_highest_res", "except_largest_file",
                    "except_sharpest", "except_oldest", "except_newest", "except_shortest_path"):
            m.addAction(t("rule." + key), lambda k=key: self.apply_rule(k))
        m.addAction(t("rule.blurrier"), self._rule_blurrier)
        m.addAction(t("rule.prefer_format"), self._rule_format)
        m.addAction(t("rule.folder_priority"), self._rule_folder)
        m.addAction(t("rule.regex"), self._rule_regex)
        m.addSeparator()
        m.addAction(t("select.invert"), lambda: self._apply(lambda: self.state.invert(self._scope_ids())))
        m.addAction(t("select.clear"), lambda: self._apply(lambda: self.state.clear(self._scope_ids())))
        return m

    def load(self, result: ScanResult, protected: list[str]) -> None:
        self.result = result
        self.state = sel.SelectionState(result.groups, result.assets, result.features,
                                        protected_dirs=protected)
        self.gmodel = GroupListModel(self.state)
        self.group_list.setModel(self.gmodel)
        self.group_list.setItemDelegate(GroupDelegate(self.state, self.loader, self.group_list))
        self.group_list.selectionModel().currentChanged.connect(self._group_changed)
        self.pmodel = PhotoModel(self.state)
        self.grid.setModel(self.pmodel)
        self.pdel = PhotoDelegate(self.pmodel, self.loader, self.grid)
        self.pdel.card_w = self.size_slider.value()
        self.pdel.toggle.connect(self.toggle)
        self.pdel.open_preview.connect(self.open_preview)
        self.grid.setItemDelegate(self.pdel)
        self.grid.selectionModel().currentChanged.connect(self._photo_changed)
        self.gmodel.rebuild()
        self.update_summary()
        if self.gmodel.rows:
            self.group_list.setCurrentIndex(self.gmodel.index(0))

    def set_protected(self, dirs: list[str]) -> None:
        if self.state:
            self.state.protected_dirs = list(dirs)
            self.grid.viewport().update()

    # ------------------------------------------------------------------ helpers
    def current_gi(self) -> int:
        return self.pmodel.gi if self.state else -1

    def current_focus(self) -> int | None:
        idx = self.grid.currentIndex()
        if idx.isValid():
            return idx.data(Qt.UserRole)
        return self.pmodel.ids[0] if self.state and self.pmodel.ids else None

    def _scope_ids(self) -> list[int]:
        if self.scope == "group":
            return [self.current_gi()] if self.current_gi() >= 0 else []
        if self.scope == "visible":
            return list(self.gmodel.rows)
        return list(range(len(self.state.groups)))

    def _apply(self, fn) -> None:
        if not self.state:
            return
        res = fn()
        if isinstance(res, sel.ApplyReport) and res.spared_groups:
            self.toast.emit(t("review.spared", g=res.spared_groups), "info")
        self.after_change(all_rows=self.scope != "group")

    def apply_rule(self, key, advance: bool = False) -> None:
        self._last_rule = key if isinstance(key, str) else self._last_rule
        if isinstance(key, str):
            self.settings.last_rule = key
        self._apply(lambda: self.state.apply(key, self._scope_ids()))
        if advance:
            self.step_group(1)

    def _rule_blurrier(self):
        v, ok = QInputDialog.getInt(self, t("rule.blurrier"), t("rule.blurrier_q"), 60, 5, 99)
        if ok:
            self._apply(lambda: self.state.apply(sel.rule_blurrier_than(v), self._scope_ids()))

    def _rule_format(self):
        items = ["HEIC > JPG > PNG", "JPG > HEIC > PNG", "RAW (DNG/CR3/NEF/ARW) > JPG > HEIC"]
        v, ok = QInputDialog.getItem(self, t("rule.prefer_format"), t("rule.prefer_format_q"),
                                     items, 0, False)
        if ok:
            order = {0: [".heic", ".jpg", ".png"], 1: [".jpg", ".heic", ".png"],
                     2: [".dng", ".cr3", ".cr2", ".nef", ".arw", ".raf", ".jpg", ".heic"]}[
                items.index(v)]
            self._apply(lambda: self.state.apply(sel.rule_prefer_format(order), self._scope_ids()))

    def _rule_folder(self):
        d = QFileDialog.getExistingDirectory(self, t("rule.folder_priority_q"))
        if d:
            self._apply(lambda: self.state.apply(sel.rule_folder_priority([d]), self._scope_ids()))

    def _rule_regex(self):
        v, ok = QInputDialog.getText(self, t("rule.regex"), t("rule.regex_q"))
        if ok and v.strip():
            try:
                rule = sel.rule_regex(v.strip())
            except Exception as e:
                self.toast.emit(str(e), "error")
                return
            self._apply(lambda: self.state.apply(rule, self._scope_ids()))

    def toggle(self, aid: int | None) -> None:
        if aid is None or not self.state:
            return
        gi = self.current_gi()
        if not self.state.toggle(gi, aid):
            msg = t("review.protected_tip") if self.state.is_protected(aid) else t("review.guard")
            self.toast.emit(msg, "info")
        self.after_change()

    def undo_selection(self) -> None:
        if self.state and self.state.undo():
            self.after_change(all_rows=True)

    def after_change(self, all_rows: bool = False) -> None:
        self.pmodel.refresh()
        self.grid.viewport().update()
        self.group_list.viewport().update()
        self.update_summary()
        if self.preview.isVisible():
            self._show_preview(self.preview_id)
        if self.compare.isVisible():
            self._show_compare()

    def update_summary(self) -> None:
        if not self.state:
            return
        n, size = self.state.summary()
        self.summary.setText(t("review.summary", n=n, size=human_size(size)))
        groups = len(self.state.groups)
        self.count_label.setText(t("review.groups_count", shown=len(self.gmodel.rows), total=groups))
        for b in (self.remove_b, self.move_b):
            b.setEnabled(n > 0)
        self.remove_b.setText(t("review.remove_n", n=n) if n else t("review.remove"))

    # ------------------------------------------------------------------ navigation
    def _filters_changed(self, *_):
        if not self.state:
            return
        self.gmodel.kind_filter = self.kind_box.currentData()
        self.gmodel.status_filter = self.status_box.currentData()
        self.gmodel.sort = self.sort_box.currentData()
        gi = self.current_gi()
        self.gmodel.rebuild()
        self.update_summary()
        if gi in self.gmodel.rows:
            self.group_list.setCurrentIndex(self.gmodel.index(self.gmodel.rows.index(gi)))
        elif self.gmodel.rows:
            self.group_list.setCurrentIndex(self.gmodel.index(0))
        else:
            self.pmodel.set_group(-1)
            self._update_title()

    def _group_changed(self, cur, _prev):
        if not cur.isValid():
            return
        gi = cur.data(Qt.UserRole)
        self.loader.bump()
        self.pmodel.set_group(gi)
        self._update_title()
        if self.pmodel.ids:
            g = self.state.groups[gi]
            best = g.best.asset_id
            row = self.pmodel.ids.index(best) if best in self.pmodel.ids else 0
            self.grid.setCurrentIndex(self.pmodel.index(row))
        self._prefetch(gi)
        self.grid.setFocus()

    def _update_title(self):
        gi = self.current_gi()
        if gi < 0:
            self.g_title.setText(t("review.no_group"))
            self.g_sub.setText("")
            return
        g = self.state.groups[gi]
        pos = self.gmodel.rows.index(gi) + 1 if gi in self.gmodel.rows else 0
        self.g_title.setText(t("review.group_title", n=pos, total=len(self.gmodel.rows)))
        span = [self.state.assets[i].taken_at or 0 for i in g.ids]
        dur = max(span) - min(span)
        self.g_sub.setText(t("kind." + g.kind.value) + "  ·  " +
                           t("review.n_photos", n=len(g.members)) + "  ·  " +
                           fmt_time(min(span)) + (f"  ·  {dur:.0f} s" if dur > 0 else "") +
                           "  ·  " + t("review.reclaim", size=human_size(self.gmodel.reclaim(gi))))

    def _prefetch(self, gi: int) -> None:
        """Warm the cache: full previews for this group, thumbnails for the next ones."""
        g = self.state.groups[gi]
        for aid in g.ids:
            a = self.state.assets[aid]
            self.loader.get(a.thumb, a.primary, CARD_THUMB, priority=5)
        if gi in self.gmodel.rows:
            k = self.gmodel.rows.index(gi)
            for nxt in self.gmodel.rows[k + 1 : k + 3]:
                for aid in self.state.groups[nxt].ids:
                    a = self.state.assets[aid]
                    self.loader.get(a.thumb, a.primary, CARD_THUMB, priority=1)

    def step_group(self, d: int, unreviewed: bool = False) -> None:
        rows = self.gmodel.rows
        if not rows:
            return
        gi = self.current_gi()
        k = rows.index(gi) if gi in rows else -1
        while True:
            k += d
            if not 0 <= k < len(rows):
                return
            if not unreviewed or rows[k] not in self.state.reviewed:
                break
        self.group_list.setCurrentIndex(self.gmodel.index(k))
        self.group_list.scrollTo(self.gmodel.index(k))

    def _photo_changed(self, cur, _prev):
        if not cur.isValid():
            return
        aid = cur.data(Qt.UserRole)
        self.focus_id = aid
        self.inspector.show_asset(self.state, self.pmodel.member(aid), aid)
        a = self.state.assets[aid]
        self.loader.get(a.thumb, a.primary, 2048, full=True, priority=3)

    def _key(self, action: str) -> None:
        if not self.state:
            return
        if action == "toggle":
            for i in self.grid.selectionModel().selectedIndexes() or [self.grid.currentIndex()]:
                self.toggle(i.data(Qt.UserRole))
        elif action == "preview":
            self.open_preview(self.current_focus())
        elif action == "compare":
            self.open_compare()
        elif action == "next":
            self.step_group(1)
        elif action == "prev":
            self.step_group(-1)
        elif action == "next_unreviewed":
            self.step_group(1, unreviewed=True)
        elif action == "rule_next":
            scope, self.scope = self.scope, "group"
            self.apply_rule(self._last_rule, advance=True)
            self.scope = scope
        elif action == "keep_all":
            self.state.clear([self.current_gi()])
            self.state.reviewed.add(self.current_gi())
            self.after_change()
            self.step_group(1)
        elif action == "invert":
            scope, self.scope = self.scope, "group"
            self._apply(lambda: self.state.invert([self.current_gi()]))
            self.scope = scope
        elif action == "remove":
            if self.state.checked:
                self.remove_requested.emit(sorted(self.state.checked))
        elif action.startswith("num"):
            n = int(action[3:]) - 1
            if n < len(self.pmodel.ids):
                self.toggle(self.pmodel.ids[n])

    def _not_duplicates(self) -> None:
        gi = self.current_gi()
        if gi >= 0:
            self.ignore_group.emit(gi)

    def _card_size(self, v: int) -> None:
        self.settings.card_size = v
        if self.state:
            self.pdel.card_w = v
            self.grid.doItemsLayout()

    # ------------------------------------------------------------------ preview / compare
    def open_preview(self, aid: int | None) -> None:
        if aid is None or not self.state:
            return
        self.preview_id = aid
        self.preview.setGeometry(self.rect())
        self.preview.view.fitted = True
        self._show_preview(aid)
        self.preview.show()
        self.preview.raise_()
        self.preview.setFocus()

    def _show_preview(self, aid: int) -> None:
        a = self.state.assets[aid]
        m = self.pmodel.member(aid)
        self.preview.header.set(a, aid in self.state.checked, m.suggested, m.reasons,
                                f"{round(m.similarity * 100)}%" if not m.suggested else "")
        full = self.loader.get(a.thumb, a.primary, 2048, full=True, priority=9)
        pm = full or self.loader.get(a.thumb, a.primary, CARD_THUMB)
        self.preview.view.set_pixmap(pm, a.width, a.height)
        ids = self.pmodel.ids
        self.preview.pos_label.setText(f"{ids.index(aid) + 1} / {len(ids)}")
        for d in (-1, 1):            # prefetch neighbours
            j = ids.index(aid) + d
            if 0 <= j < len(ids):
                b = self.state.assets[ids[j]]
                self.loader.get(b.thumb, b.primary, 2048, full=True, priority=4)

    def _preview_nav(self, d: int) -> None:
        ids = self.pmodel.ids
        j = ids.index(self.preview_id) + d
        if 0 <= j < len(ids):
            self.preview_id = ids[j]
            self.grid.setCurrentIndex(self.pmodel.index(j))
            self._show_preview(self.preview_id)

    def close_preview(self) -> None:
        self.preview.hide()
        if self.preview_id in self.pmodel.ids:
            self.grid.setCurrentIndex(self.pmodel.index(self.pmodel.ids.index(self.preview_id)))
        self.grid.setFocus()

    def open_compare(self) -> None:
        if not self.state or len(self.pmodel.ids) < 2:
            return
        selected = [i.data(Qt.UserRole) for i in self.grid.selectionModel().selectedIndexes()]
        g = self.state.groups[self.current_gi()]
        best = g.best.asset_id
        focus = self.current_focus()
        if len(selected) >= 2:
            a, b = selected[:2]
        else:
            a = best
            b = focus if focus != best else next(i for i in self.pmodel.ids if i != best)
        self.compare_ids = [a, b]
        self.preview.hide()
        self.compare.setGeometry(self.rect())
        for p in self.compare.panes:
            p.view.fitted = True
        self._show_compare()
        self.compare.show()
        self.compare.raise_()
        self.compare.setFocus()

    def _show_compare(self) -> None:
        for pane, aid in zip(self.compare.panes, self.compare_ids, strict=False):
            a = self.state.assets[aid]
            m = self.pmodel.member(aid)
            pane.header.set(a, aid in self.state.checked, m.suggested, m.reasons)
            full = self.loader.get(a.thumb, a.primary, 2048, full=True, priority=9)
            pane.view.set_pixmap(full or self.loader.get(a.thumb, a.primary, CARD_THUMB),
                                 a.width, a.height)

    def _compare_cycle(self, pane: int, d: int) -> None:
        ids = [i for i in self.pmodel.ids if i != self.compare_ids[1 - pane]]
        cur = self.compare_ids[pane]
        k = (ids.index(cur) + d) % len(ids) if cur in ids else 0
        self.compare_ids[pane] = ids[k]
        self._show_compare()

    def close_compare(self) -> None:
        self.compare.hide()
        self.grid.setFocus()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.preview.isVisible():
            self.preview.setGeometry(self.rect())
        if self.compare.isVisible():
            self.compare.setGeometry(self.rect())

    # ------------------------------------------------------------------ images
    def _image_loaded(self, key: str) -> None:
        self._repaint.start()
        if key.startswith("F") and self.state:
            if self.preview.isVisible() and self.preview_id is not None:
                a = self.state.assets[self.preview_id]
                if key == self.loader.key(a.primary, 2048, True):
                    self.preview.view.set_pixmap(self.loader.cache.get(key), a.width, a.height)
            if self.compare.isVisible():
                for pane, aid in zip(self.compare.panes, self.compare_ids, strict=False):
                    a = self.state.assets[aid]
                    if key == self.loader.key(a.primary, 2048, True):
                        pane.view.set_pixmap(self.loader.cache.get(key), a.width, a.height)
            if self.inspector.aid is not None:
                a = self.state.assets[self.inspector.aid]
                if key == self.loader.key(a.primary, 2048, True):
                    self.inspector.view.set_pixmap(self.loader.cache.get(key), a.width, a.height)

    def _do_repaint(self) -> None:
        self.grid.viewport().update()
        self.group_list.viewport().update()
        if self.inspector.aid is not None and self.state:
            if self.inspector.view.item.pixmap().isNull():
                self.inspector.refresh_image(self.state)

    # ------------------------------------------------------------------ export
    def export_csv(self) -> None:
        if not self.state:
            return
        path, _ = QFileDialog.getSaveFileName(self, t("review.export_csv"), "keepframe.csv",
                                              "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["group", "kind", "path", "checked", "suggested", "score", "similarity",
                        "width", "height", "size", "taken", "reasons"])
            for gi, g in enumerate(self.state.groups, 1):
                for m in g.members:
                    a = self.state.assets[m.asset_id]
                    w.writerow([gi, g.kind.value, str(a.primary), int(m.asset_id in self.state.checked),
                                int(m.suggested), f"{m.score:.3f}", f"{m.similarity:.3f}",
                                a.width, a.height, a.size, fmt_time(a.taken_at),
                                ",".join(m.reasons)])
        self.toast.emit(t("review.exported", path=Path(path).name), "success")

    def drop_assets(self, ids: set[int]) -> None:
        """Files were moved away: remove them from the view."""
        gi = self.current_gi()
        pos = self.gmodel.rows.index(gi) if gi in self.gmodel.rows else 0
        self.state.remove_assets(ids)
        self.gmodel.rebuild()
        self.update_summary()
        if self.gmodel.rows:
            k = min(pos, len(self.gmodel.rows) - 1)
            self.group_list.setCurrentIndex(self.gmodel.index(k))
        else:
            self.pmodel.set_group(-1)
            self._update_title()

    def remove_group(self, gi: int) -> None:
        g = self.state.groups[gi]
        self.state.clear([gi])
        pos = self.gmodel.rows.index(gi) if gi in self.gmodel.rows else 0
        self.state.groups.pop(gi)
        self.state.reviewed = {x - (x > gi) for x in self.state.reviewed if x != gi}
        self.gmodel.rebuild()
        self.update_summary()
        if self.gmodel.rows:
            self.group_list.setCurrentIndex(self.gmodel.index(min(pos, len(self.gmodel.rows) - 1)))
        else:
            self.pmodel.set_group(-1)
            self._update_title()
        return g


__all__ = ["ReviewPage", "Group"]
