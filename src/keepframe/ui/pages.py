"""Scan progress, settings and history pages."""

from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core.features import embedder
from .i18n import LANGUAGES, t
from .theme import T
from .widgets import StatCard, btn, label, open_in_explorer

STAGES = ["discover", "features", "hash", "embed", "verify"]


class ScanPage(QWidget):
    cancel = Signal()

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignCenter)
        box = QWidget()
        box.setFixedWidth(620)
        v = QVBoxLayout(box)
        v.setSpacing(14)
        self.title = label(t("scan.title"), "display")
        v.addWidget(self.title)
        self.stage = label("", "secondary")
        v.addWidget(self.stage)
        steps = QHBoxLayout()
        steps.setSpacing(6)
        self.dots: dict[str, QLabel] = {}
        for s in STAGES:
            d = label(t("stage." + s).rstrip("…"), "muted")
            d.setAlignment(Qt.AlignCenter)
            self.dots[s] = d
            steps.addWidget(d, 1)
        v.addLayout(steps)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        v.addWidget(self.bar)
        self.eta = label("", "caption")
        v.addWidget(self.eta)
        grid = QGridLayout()
        grid.setSpacing(12)
        self.c_files = StatCard(t("scan.stat.files"))
        self.c_done = StatCard(t("scan.stat.processed"))
        self.c_speed = StatCard(t("scan.stat.speed"))
        self.c_elapsed = StatCard(t("scan.stat.elapsed"))
        for i, w in enumerate((self.c_files, self.c_done, self.c_speed, self.c_elapsed)):
            grid.addWidget(w, i // 2, i % 2)
        v.addLayout(grid)
        h = QHBoxLayout()
        h.addWidget(label(t("scan.hint"), "muted", wrap=True), 1)
        self.cancel_b = btn(t("scan.cancel"), "", "square")
        self.cancel_b.clicked.connect(self._cancel)
        h.addWidget(self.cancel_b)
        v.addLayout(h)
        outer.addWidget(box, alignment=Qt.AlignCenter)
        self.t0 = 0.0
        self.stage_t0 = 0.0
        self.cur = ""

    def start(self, title: str) -> None:
        self.title.setText(title)
        self.t0 = self.stage_t0 = time.monotonic()
        self.cur = ""
        self.bar.setRange(0, 0)
        self.cancel_b.setEnabled(True)
        self.cancel_b.setText(t("scan.cancel"))
        for c in (self.c_files, self.c_done, self.c_speed, self.c_elapsed):
            c.set("–")
        for d in self.dots.values():
            d.setStyleSheet("")

    def _cancel(self):
        self.cancel_b.setEnabled(False)
        self.cancel_b.setText(t("scan.cancelling"))
        self.cancel.emit()

    def update(self, stage: str, done: int, total: int) -> None:
        now = time.monotonic()
        if stage != self.cur:
            self.cur, self.stage_t0 = stage, now
        self.stage.setText(t("stage." + stage) if t("stage." + stage) != "stage." + stage else stage)
        hit = False
        for s in reversed(STAGES):
            d = self.dots[s]
            if s == stage:
                d.setStyleSheet(f"color: {T['accent']}; font-weight: 600;")
                hit = True
            elif hit:
                d.setStyleSheet(f"color: {T['success']};")
            else:
                d.setStyleSheet("")
        if stage == "discover":
            self.c_files.set(f"{done:,}")
        if total:
            self.bar.setRange(0, total)
            self.bar.setValue(done)
            el = now - self.stage_t0
            rate = done / el if el > 0.3 else 0
            self.c_done.set(f"{done:,} / {total:,}")
            if rate:
                self.c_speed.set(f"{rate:,.0f}/s")
                rem = (total - done) / rate
                self.eta.setText(t("scan.eta", pct=round(100 * done / total),
                                   time=_dur(rem)))
        else:
            self.bar.setRange(0, 0)
            self.eta.setText("")
        self.c_elapsed.set(_dur(now - self.t0))


def _dur(s: float) -> str:
    s = int(s)
    return f"{s // 60}:{s % 60:02d}" if s >= 60 else f"{s} s"


class SettingsPage(QWidget):
    changed = Signal()
    theme_changed = Signal(str)
    clear_cache = Signal()
    clear_ignored = Signal()

    def __init__(self, settings):
        super().__init__()
        self.s = settings
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        v = QVBoxLayout(body)
        v.setContentsMargins(32, 24, 32, 32)
        v.setSpacing(18)
        v.addWidget(label(t("settings.title"), "title"))

        def section(title: str) -> QFormLayout:
            card = QFrame()
            card.setProperty("role", "card")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(20, 16, 20, 16)
            cl.addWidget(label(title, "section"))
            f = QFormLayout()
            f.setLabelAlignment(Qt.AlignLeft)
            f.setHorizontalSpacing(24)
            f.setVerticalSpacing(10)
            cl.addLayout(f)
            card.setMaximumWidth(860)
            v.addWidget(card)
            return f

        f = section(t("settings.similar"))
        self.strict = QSlider(Qt.Horizontal)
        self.strict.setRange(0, 100)
        self.strict.setValue(int(settings.strictness * 100))
        sl = QHBoxLayout()
        sl.addWidget(label(t("settings.loose"), "muted"))
        sl.addWidget(self.strict, 1)
        sl.addWidget(label(t("settings.strict"), "muted"))
        f.addRow(t("settings.strictness"), sl)
        self.max_dt = QDoubleSpinBox()
        self.max_dt.setRange(1, 600)
        self.max_dt.setSuffix(" s")
        self.max_dt.setDecimals(0)
        self.max_dt.setValue(settings.max_dt)
        f.addRow(t("settings.max_dt"), self.max_dt)
        self.cross = QCheckBox(t("settings.cross_device"))
        self.cross.setChecked(settings.cross_device)
        self.near = QCheckBox(t("settings.near_copies"))
        self.near.setChecked(settings.near_copies)
        self.shots = QCheckBox(t("settings.screenshots"))
        self.shots.setChecked(settings.include_screenshots)
        self.fdates = QCheckBox(t("settings.file_dates"))
        self.fdates.setChecked(settings.use_file_dates)
        for w in (self.cross, self.near, self.shots, self.fdates):
            f.addRow("", w)

        f = section(t("settings.ai"))
        self.ai = QCheckBox(t("settings.use_ai"))
        self.ai.setChecked(settings.use_ai)
        f.addRow("", self.ai)
        self.device = QComboBox()
        self.device.addItem(t("settings.device.auto"), "auto")
        self.device.addItem("CPU", "cpu")
        self.device.setCurrentIndex(0 if settings.device == "auto" else 1)
        f.addRow(t("settings.device"), self.device)
        mf = embedder.model_file()
        self.model_status = label(t("settings.model_ok", path=str(mf)) if mf
                                  else t("settings.model_missing"), "caption", wrap=True)
        f.addRow(t("settings.model"), self.model_status)
        mb = btn(t("settings.model_choose"), "", "download")
        mb.clicked.connect(self._choose_model)
        f.addRow("", mb)

        f = section(t("settings.files"))
        self.excluded = QLineEdit(settings.excluded)
        self.excluded.setPlaceholderText("node_modules, *.tmp, D:/Photos/Archive/*")
        f.addRow(t("settings.excluded"), self.excluded)
        self.min_kb = QSpinBox()
        self.min_kb.setRange(0, 10_000_000)
        self.min_kb.setSuffix(" KB")
        self.min_kb.setValue(settings.min_size_kb)
        f.addRow(t("settings.min_size"), self.min_kb)
        self.hidden = QCheckBox(t("settings.skip_hidden"))
        self.hidden.setChecked(settings.skip_hidden)
        self.cloud = QCheckBox(t("settings.cloud"))
        self.cloud.setChecked(settings.include_cloud_only)
        f.addRow("", self.hidden)
        f.addRow("", self.cloud)
        self.big = QSpinBox()
        self.big.setRange(10, 100000)
        self.big.setValue(settings.big_count)
        f.addRow(t("settings.big_count"), self.big)
        self.workers = QSpinBox()
        self.workers.setRange(0, 64)
        self.workers.setSpecialValueText(t("settings.auto"))
        self.workers.setValue(settings.workers)
        f.addRow(t("settings.threads"), self.workers)

        f = section(t("settings.removal"))
        self.removal = QComboBox()
        self.removal.addItem(t("settings.removal.recycle"), "recycle")
        self.removal.addItem(t("settings.removal.quarantine"), "quarantine")
        self.removal.setCurrentIndex(0 if settings.removal == "recycle" else 1)
        f.addRow(t("settings.removal_method"), self.removal)
        f.addRow("", label(t("settings.removal_note"), "muted", wrap=True))

        f = section(t("settings.appearance"))
        self.lang = QComboBox()
        self.lang.addItem(t("settings.lang.system"), "")
        for k, name in LANGUAGES.items():
            self.lang.addItem(name, k)
        self.lang.setCurrentIndex(max(0, self.lang.findData(settings.language)))
        f.addRow(t("settings.language"), self.lang)
        self.theme = QComboBox()
        for k in ("dark", "light", "system"):
            self.theme.addItem(t("settings.theme." + k), k)
        self.theme.setCurrentIndex(max(0, self.theme.findData(settings.theme)))
        f.addRow(t("settings.theme"), self.theme)
        f.addRow("", label(t("settings.restart_note"), "muted"))

        f = section(t("settings.data"))
        h = QHBoxLayout()
        cc = btn(t("settings.clear_cache"), "", "trash")
        ci = btn(t("settings.clear_ignored"), "", "undo")
        od = btn(t("settings.open_data"), "ghost", "folder")
        cc.clicked.connect(self.clear_cache)
        ci.clicked.connect(self.clear_ignored)
        from ..core.paths import data_dir
        od.clicked.connect(lambda: open_in_explorer(data_dir(), select=False))
        h.addWidget(cc)
        h.addWidget(ci)
        h.addWidget(od)
        h.addStretch()
        f.addRow("", h)
        v.addStretch()

        for w in (self.strict, ):
            w.valueChanged.connect(self._save)
        for w in (self.max_dt, self.min_kb, self.big, self.workers):
            w.valueChanged.connect(self._save)
        for w in (self.cross, self.near, self.shots, self.fdates, self.ai, self.hidden, self.cloud):
            w.toggled.connect(self._save)
        for w in (self.device, self.removal, self.lang):
            w.currentIndexChanged.connect(self._save)
        self.theme.currentIndexChanged.connect(self._theme)
        self.excluded.editingFinished.connect(self._save)

    def _theme(self):
        self._save()
        self.theme_changed.emit(self.s.theme)

    def _save(self, *_):
        s = self.s
        s.strictness = self.strict.value() / 100
        s.max_dt = self.max_dt.value()
        s.cross_device = self.cross.isChecked()
        s.near_copies = self.near.isChecked()
        s.include_screenshots = self.shots.isChecked()
        s.use_file_dates = self.fdates.isChecked()
        s.use_ai = self.ai.isChecked()
        s.device = self.device.currentData()
        s.excluded = self.excluded.text()
        s.min_size_kb = self.min_kb.value()
        s.skip_hidden = self.hidden.isChecked()
        s.include_cloud_only = self.cloud.isChecked()
        s.big_count = self.big.value()
        s.workers = self.workers.value()
        s.removal = self.removal.currentData()
        s.language = self.lang.currentData()
        s.theme = self.theme.currentData()
        from .i18n import set_language
        if s.language:
            set_language(s.language)
        s.save()
        self.changed.emit()

    def _choose_model(self):
        f, _ = QFileDialog.getOpenFileName(self, t("settings.model_choose"), "", "ONNX (*.onnx)")
        if not f:
            return
        import shutil

        from ..core.paths import data_dir
        dst = data_dir() / "models" / embedder.MODEL_NAME
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(f, dst)
        self.model_status.setText(t("settings.model_ok", path=str(dst)))


class HistoryPage(QWidget):
    undo = Signal(str)

    def __init__(self, catalog):
        super().__init__()
        self.cat = catalog
        v = QVBoxLayout(self)
        v.setContentsMargins(32, 24, 32, 24)
        v.setSpacing(12)
        v.addWidget(label(t("history.title"), "title"))
        v.addWidget(label(t("history.sub"), "secondary", wrap=True))
        self.list = QListWidget()
        self.list.setStyleSheet("QListWidget::item { padding: 10px; border-bottom: 1px solid "
                                f"{T['border']}; }}")
        v.addWidget(self.list, 1)
        h = QHBoxLayout()
        h.addStretch()
        self.undo_b = btn(t("history.undo"), "primary", "undo")
        self.undo_b.clicked.connect(self._undo)
        h.addWidget(self.undo_b)
        v.addLayout(h)

    def refresh(self) -> None:
        self.list.clear()
        for sid, ts, n, undone in self.cat.sessions():
            when = datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")
            txt = t("history.row", when=when, n=n)
            if undone:
                txt += "   ·   " + t("history.undone", n=undone)
            it = QListWidgetItem(txt)
            it.setData(Qt.UserRole, sid)
            self.list.addItem(it)
        self.undo_b.setEnabled(self.list.count() > 0)

    def _undo(self):
        it = self.list.currentItem() or self.list.item(0)
        if it:
            self.undo.emit(it.data(Qt.UserRole))
