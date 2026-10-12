"""GUI entry point: ``python -m keepframe`` (or KeepFrame.exe)."""

from __future__ import annotations

import faulthandler
import logging
import os
import sys


def _setup_logging() -> None:
    from .core.paths import data_dir

    logdir = data_dir() / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    f = logdir / "keepframe.log"
    logging.basicConfig(filename=f, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        faulthandler.enable(open(logdir / "crash.log", "a"))  # noqa: SIM115
    except Exception:
        pass
    if sys.stderr is None:                    # windowed exe has no console
        sys.stderr = open(logdir / "stderr.log", "a")  # noqa: SIM115
    if sys.stdout is None:
        sys.stdout = sys.stderr


def main() -> int:
    _setup_logging()
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        logging.error("PySide6 is not installed. Run: pip install -e .[gui]")
        return 1

    from PySide6.QtCore import QCoreApplication

    from . import APP_NAME

    QCoreApplication.setOrganizationName(APP_NAME)
    QCoreApplication.setApplicationName(APP_NAME)
    app = QApplication(sys.argv)

    from .ui import theme
    from .ui.i18n import set_language
    from .ui.settings import Settings

    settings = Settings.load()
    if settings.language:
        set_language(settings.language)
    theme.apply(app, settings.theme)
    from pathlib import Path

    from PySide6.QtGui import QIcon
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "ui" / "app_icon.png")))

    from .ui.main_window import MainWindow

    w = MainWindow(settings)
    w.show()
    rc = app.exec()
    # A job abandoned after "Cancel" may still be blocked on a slow disk; leave
    # immediately instead of letting Qt destroy a running thread at shutdown.
    logging.shutdown()
    sys.stdout.flush()
    os._exit(rc)


if __name__ == "__main__":
    raise SystemExit(main())
