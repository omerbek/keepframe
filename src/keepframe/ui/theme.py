"""'Darkroom, not dashboard' theme: photos are the only saturated thing on screen."""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

DARK = dict(
    bg_app="#121316", bg_sidebar="#17181C", bg_panel="#1B1D21", bg_card="#22252A",
    bg_elevated="#2A2D33", bg_hover="#2F333A", bg_pressed="#383C44", bg_input="#1A1C20",
    border="#2E3137", border_strong="#3D4148",
    text="#ECEDEF", text_secondary="#A8ADB6", text_muted="#8A8F99", text_on_accent="#FFFFFF",
    accent="#4D9CFF", accent_fill="#2670D6", accent_fill_hover="#3580E6",
    accent_fill_pressed="#1F60BA",
    success="#3FBF7F", danger="#F2605C", danger_fill="#C93A36", danger_fill_hover="#D84A45",
    danger_tint="rgba(242,96,92,0.14)", warning="#E8A33D", info="#5BC0EB",
    selection_bg="#1E3550", photo_matte="#0D0E10",
)
LIGHT = dict(
    bg_app="#F6F6F4", bg_sidebar="#EDEEEB", bg_panel="#FBFBFA", bg_card="#FFFFFF",
    bg_elevated="#FFFFFF", bg_hover="#E8E9E6", bg_pressed="#DCDDDA", bg_input="#FFFFFF",
    border="#DEDFDB", border_strong="#C6C8C3",
    text="#16181C", text_secondary="#545A63", text_muted="#656B74", text_on_accent="#FFFFFF",
    accent="#1F6FD1", accent_fill="#1F6FD1", accent_fill_hover="#2A7BE0",
    accent_fill_pressed="#195DB0",
    success="#1A7D4C", danger="#C8322E", danger_fill="#C8322E", danger_fill_hover="#B22B27",
    danger_tint="rgba(200,50,46,0.10)", warning="#A0620A", info="#1C7BAA",
    selection_bg="#D7E6FA", photo_matte="#1A1B1E",
)

T: dict[str, str] = dict(DARK)     # current tokens (read by painters/delegates)


def c(name: str) -> QColor:
    v = T[name]
    if v.startswith("rgba"):
        r, g, b, a = (float(x) for x in v[5:-1].split(","))
        return QColor(int(r), int(g), int(b), int(a * 255))
    return QColor(v)


QSS = r"""
* { font-family: "Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans", sans-serif; font-size: 13px; }
QWidget { background: @bg_app; color: @text; selection-background-color: @selection_bg; selection-color: @text; }
QWidget:disabled { color: @text_muted; }
QWidget#Sidebar { background: @bg_sidebar; border-right: 1px solid @border; }
QWidget#TopBar  { background: @bg_panel; border-bottom: 1px solid @border; }
QWidget#Inspector { background: @bg_panel; border-left: 1px solid @border; }
QWidget#ActionBar { background: @bg_panel; border-top: 1px solid @border; }
QWidget#Toolbar { background: @bg_app; border-bottom: 1px solid @border; }
QWidget#Matte, QGraphicsView#Matte { background: @photo_matte; border: none; }
QWidget#Transparent { background: transparent; }
QFrame[role="card"] { background: @bg_card; border: 1px solid @border; border-radius: 10px; }
QFrame[role="chip"] { background: @bg_card; border: 1px solid @border; border-radius: 14px; }
QFrame[role="chip"]:hover { border-color: @border_strong; }
QFrame[role="segmented"] { background: @bg_input; border: 1px solid @border; border-radius: 8px; }
QFrame[role="toast"] { background: @bg_elevated; border: 1px solid @border_strong; border-radius: 12px; }
QFrame[role="divider"] { background: @border; max-height: 1px; min-height: 1px; border: none; }
QFrame[role="dropzone"] { background: @bg_panel; border: 1px dashed @border_strong; border-radius: 14px; }

QLabel { background: transparent; }
QLabel[role="display"]   { font-size: 28px; font-weight: 600; }
QLabel[role="title"]     { font-size: 20px; font-weight: 600; }
QLabel[role="section"]   { font-size: 15px; font-weight: 600; }
QLabel[role="secondary"] { color: @text_secondary; }
QLabel[role="caption"]   { color: @text_secondary; font-size: 12px; }
QLabel[role="muted"]     { color: @text_muted; font-size: 12px; }
QLabel[role="overline"]  { color: @text_muted; font-size: 11px; font-weight: 600; letter-spacing: 1px; }
QLabel[role="stat"]      { font-size: 24px; font-weight: 600; }
QLabel[role="success"]   { color: @success; }
QLabel[role="danger"]    { color: @danger; }
QLabel[role="warning"]   { color: @warning; }
QLabel[role="logo"]      { font-size: 17px; font-weight: 700; }

QPushButton, QToolButton {
    background: @bg_card; color: @text; border: 1px solid @border_strong; border-radius: 6px;
    padding: 0 14px; min-height: 30px; font-weight: 600;
}
QToolButton { padding: 0 10px; }
QPushButton:hover, QToolButton:hover { background: @bg_hover; }
QPushButton:pressed, QToolButton:pressed { background: @bg_pressed; }
QPushButton:focus, QToolButton:focus { border-color: @accent; }
QPushButton:disabled, QToolButton:disabled { background: @bg_card; color: @text_muted; border-color: @border; }
QToolButton::menu-indicator { image: none; width: 0; }
QPushButton[variant="primary"] { background: @accent_fill; color: @text_on_accent; border: 1px solid @accent_fill; }
QPushButton[variant="primary"]:hover { background: @accent_fill_hover; border-color: @accent_fill_hover; }
QPushButton[variant="primary"]:pressed { background: @accent_fill_pressed; }
QPushButton[variant="primary"]:disabled { background: @bg_hover; color: @text_muted; border-color: @bg_hover; }
QPushButton[variant="danger"] { background: @danger_fill; color: #FFFFFF; border: 1px solid @danger_fill; }
QPushButton[variant="danger"]:hover { background: @danger_fill_hover; }
QPushButton[variant="danger"]:disabled { background: @bg_hover; color: @text_muted; border-color: @bg_hover; }
QPushButton[variant="ghost"], QToolButton[variant="ghost"] { background: transparent; border: 1px solid transparent; color: @text_secondary; }
QPushButton[variant="ghost"]:hover, QToolButton[variant="ghost"]:hover { background: @bg_hover; color: @text; }
QPushButton[variant="ghost"]:checked, QToolButton[variant="ghost"]:checked { background: @selection_bg; color: @text; }
QPushButton[variant="link"] { background: transparent; border: none; color: @accent; padding: 0 4px; min-height: 0; }
QToolButton[variant="icon"], QPushButton[variant="icon"] {
    background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 0;
    min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px;
}
QToolButton[variant="icon"]:hover, QPushButton[variant="icon"]:hover { background: @bg_hover; }
QToolButton[variant="icon"]:checked, QPushButton[variant="icon"]:checked { background: @selection_bg; }
QPushButton[variant="chip-close"] { background: transparent; border: none; border-radius: 4px; padding: 0;
    min-width: 18px; max-width: 18px; min-height: 18px; max-height: 18px; }
QPushButton[variant="chip-close"]:hover { background: @danger_tint; }
QPushButton[variant="nav"] {
    background: transparent; border: none; border-radius: 6px;
    color: @text_secondary; text-align: left; padding: 0 10px; min-height: 34px; font-weight: 400;
}
QPushButton[variant="nav"]:hover { background: @bg_hover; color: @text; }
QPushButton[variant="nav"]:checked { background: @selection_bg; color: @text; font-weight: 600; }
QPushButton[variant="segment"] {
    background: transparent; border: 1px solid transparent; border-radius: 6px; color: @text_secondary;
    padding: 0 12px; min-height: 26px; font-weight: 600;
}
QPushButton[variant="segment"]:hover { color: @text; }
QPushButton[variant="segment"]:checked { background: @bg_elevated; border-color: @border_strong; color: @text; }

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: @bg_input; color: @text; border: 1px solid @border_strong; border-radius: 6px;
    padding: 0 8px; min-height: 30px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border: 1px solid @accent; }
QComboBox { padding-right: 26px; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: center right; width: 24px; border: none; }
QComboBox::down-arrow { image: url(@icon_dir/chevron-down.svg); width: 14px; height: 14px; }
QComboBox QAbstractItemView { background: @bg_elevated; border: 1px solid @border_strong; padding: 4px; outline: 0; }
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 0; border: none; }
QCheckBox, QRadioButton { background: transparent; spacing: 8px; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; background: @bg_input; border: 1px solid @border_strong; }
QCheckBox::indicator { border-radius: 4px; }
QRadioButton::indicator { border-radius: 8px; }
QCheckBox::indicator:hover, QRadioButton::indicator:hover { border-color: @accent; }
QCheckBox::indicator:checked { background: @accent_fill; border-color: @accent_fill; image: url(@icon_dir/check.svg); }
QRadioButton::indicator:checked { background: @bg_input; border: 5px solid @accent_fill; width: 8px; height: 8px; }

QSlider { background: transparent; min-height: 22px; }
QSlider::groove:horizontal { height: 4px; background: @border_strong; border-radius: 2px; }
QSlider::sub-page:horizontal { background: @accent; border-radius: 2px; }
QSlider::handle:horizontal { background: #ECEDEF; border: 1px solid @border_strong; width: 14px; height: 14px; margin: -6px 0; border-radius: 8px; }
QSlider::handle:horizontal:hover { background: #FFFFFF; border: 2px solid @accent; }

QProgressBar { background: @bg_hover; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; color: transparent; }
QProgressBar::chunk { background: @accent; border-radius: 3px; }

QAbstractItemView { background: @bg_app; border: none; outline: 0; alternate-background-color: @bg_panel;
    selection-background-color: @selection_bg; selection-color: @text; }
QListView#GroupList { background: @bg_panel; border: none; }
QListView#PhotoGrid, QListView#Filmstrip { background: @bg_app; border: none; }
QTreeView { background: @bg_app; }
QTreeView::item { min-height: 28px; border: none; }
QTreeView::item:hover { background: @bg_hover; }
QTreeView::item:selected { background: @selection_bg; color: @text; }
QTreeView::branch { background: transparent; }
QTreeView::indicator { width: 16px; height: 16px; background: @bg_input; border: 1px solid @border_strong; border-radius: 4px; }
QTreeView::indicator:hover { border-color: @accent; }
QTreeView::indicator:checked { background: @danger_fill; border-color: @danger_fill; image: url(@icon_dir/check.svg); }
QHeaderView { background: @bg_panel; }
QHeaderView::section { background: @bg_panel; color: @text_secondary; border: none; border-bottom: 1px solid @border;
    padding: 6px 8px; font-size: 12px; font-weight: 600; }

QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px; }
QScrollBar::handle:vertical { background: @border_strong; border-radius: 4px; min-height: 32px; margin: 0 2px; }
QScrollBar::handle:horizontal { background: @border_strong; border-radius: 4px; min-width: 32px; margin: 2px 0; }
QScrollBar::handle:hover { background: @text_muted; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; border: none; background: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }

QTabBar::tab { background: transparent; color: @text_secondary; border: none; border-bottom: 2px solid transparent;
    padding: 8px 14px; font-weight: 600; }
QTabBar::tab:selected { color: @text; border-bottom: 2px solid @accent; }
QSplitter::handle { background: @border; }
QSplitter::handle:horizontal { width: 1px; }
QSplitter::handle:vertical { height: 1px; }
QMenu { background: @bg_elevated; border: 1px solid @border_strong; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 7px 28px 7px 12px; border-radius: 4px; background: transparent; }
QMenu::item:selected { background: @bg_hover; }
QMenu::item:disabled { color: @text_muted; }
QMenu::separator { height: 1px; background: @border; margin: 4px 8px; }
QMenu::section { color: @text_muted; font-size: 11px; font-weight: 600; padding: 6px 12px 2px 12px; }
QToolTip { background: @bg_elevated; color: @text; border: 1px solid @border_strong; border-radius: 6px; padding: 6px 8px; font-size: 12px; }
QStatusBar { background: @bg_sidebar; color: @text_secondary; border-top: 1px solid @border; font-size: 12px; }
QStatusBar::item { border: none; }
QStatusBar QLabel { padding: 0 10px; }
QDialog, QMessageBox { background: @bg_panel; }
"""


def _icon_dir(tokens: dict) -> Path:
    from .icons import write_qss_icons

    d = Path(tempfile.gettempdir()) / "keepframe_icons"
    write_qss_icons(d, tokens)
    return d


def apply(app: QApplication, mode: str = "dark") -> None:
    if mode == "system":
        from PySide6.QtCore import Qt
        try:
            dark = app.styleHints().colorScheme() != Qt.ColorScheme.Light
        except Exception:
            dark = True
        mode = "dark" if dark else "light"
    tokens = DARK if mode == "dark" else LIGHT
    T.clear()
    T.update(tokens)
    qss = QSS.replace("@icon_dir", str(_icon_dir(tokens)).replace("\\", "/"))
    for k in sorted(tokens, key=len, reverse=True):
        qss = qss.replace("@" + k, tokens[k])
    app.setStyle("Fusion")
    pal = QPalette()
    for role, key in ((QPalette.Window, "bg_app"), (QPalette.Base, "bg_input"),
                      (QPalette.AlternateBase, "bg_panel"), (QPalette.Text, "text"),
                      (QPalette.WindowText, "text"), (QPalette.Button, "bg_card"),
                      (QPalette.ButtonText, "text"), (QPalette.Highlight, "selection_bg"),
                      (QPalette.HighlightedText, "text"), (QPalette.ToolTipBase, "bg_elevated"),
                      (QPalette.ToolTipText, "text"), (QPalette.PlaceholderText, "text_muted")):
        pal.setColor(role, c(key))
    app.setPalette(pal)
    f = QFont()
    f.setFamilies(["Segoe UI Variable Text", "Segoe UI", "Inter", "Noto Sans"])
    f.setPixelSize(13)
    app.setFont(f)
    app.setStyleSheet(qss)


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"
