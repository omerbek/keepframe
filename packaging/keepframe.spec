# PyInstaller spec for KeepFrame (Windows, onedir).
# Build:  packaging\build_exe.bat   (or: pyinstaller packaging\keepframe.spec --noconfirm --clean)
# Output: dist\KeepFrame\KeepFrame.exe

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).parent          # noqa: F821  (SPECPATH is set by PyInstaller)
SRC = ROOT / "src"

datas = [
    (str(SRC / "keepframe" / "ui" / "app_icon.png"), "keepframe/ui"),
]
models = SRC / "keepframe" / "models"
for f in models.glob("*.onnx"):
    datas.append((str(f), "keepframe/models"))
datas += collect_data_files("pillow_heif")

binaries = []
binaries += collect_dynamic_libs("onnxruntime")
binaries += collect_dynamic_libs("pillow_heif")
try:
    binaries += collect_dynamic_libs("rawpy")
except Exception:
    pass

hidden = ["pillow_heif", "send2trash", "keepframe.ui.main_window"]
hidden += collect_submodules("onnxruntime.capi")
try:
    import win32com  # noqa: F401
    hidden += ["win32com.client", "pythoncom", "pywintypes"]
except ImportError:
    pass

excludes = [
    "tkinter", "matplotlib", "torch", "torchvision", "transformers", "tensorflow", "IPython",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtQuick3D", "PySide6.Qt3DCore",
    "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtSensors", "PySide6.QtSerialPort",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp",
]

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="KeepFrame",
    icon=str(ROOT / "packaging" / "keepframe.ico"),
    console=False,
    upx=False,                       # UPX breaks DLLs and triggers antivirus false positives
    manifest=str(ROOT / "packaging" / "keepframe.manifest"),
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="KeepFrame",
)
