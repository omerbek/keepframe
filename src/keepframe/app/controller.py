"""Run long core jobs in background QThreads and relay progress as Qt signals.

Every job gets its own thread and a token. A new job never waits for an old one, and
results from an old (cancelled / abandoned) job are ignored, so the UI can never get
stuck on "Scanning…" or "Cancelling…".
"""

from __future__ import annotations

import threading
import time
import traceback
from collections.abc import Callable

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from ..core.pipeline import Cancelled


class _Worker(QObject):
    progress = Signal(int, str, int, int)
    finished = Signal(int, object)
    failed = Signal(int, str)
    cancelled = Signal(int)

    def __init__(self, token: int, fn: Callable, cancel: threading.Event):
        super().__init__()
        self.token, self.fn, self.cancel = token, fn, cancel
        self._last = 0.0

    def _progress(self, stage: str, done: int, total: int) -> None:
        if self.cancel.is_set():
            raise Cancelled
        now = time.monotonic()
        if now - self._last >= 0.05 or (total and done >= total):   # ~20 Hz
            self._last = now
            self.progress.emit(self.token, stage, done, total)

    def run(self) -> None:
        try:
            res = self.fn(self._progress, self.cancel)
            if self.cancel.is_set():
                self.cancelled.emit(self.token)
            else:
                self.finished.emit(self.token, res)
        except Cancelled:
            self.cancelled.emit(self.token)
        except Exception:
            self.failed.emit(self.token, traceback.format_exc())


class TaskRunner(QObject):
    """``start(fn)`` runs ``fn(progress, cancel) -> result`` in the background."""

    progress = Signal(str, int, int)
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._token = 0
        self._active = 0                  # token of the job the UI waits for (0 = none)
        self._cancel = threading.Event()
        self._threads: list[tuple[QThread, _Worker]] = []

    @property
    def running(self) -> bool:
        return self._active != 0

    def start(self, fn: Callable) -> bool:
        self._token += 1
        tok = self._token
        self._active = tok
        self._cancel = threading.Event()
        th = QThread()
        wk = _Worker(tok, fn, self._cancel)
        wk.moveToThread(th)
        th.started.connect(wk.run)
        wk.progress.connect(self._on_progress)
        wk.finished.connect(self._on_finished)
        wk.failed.connect(self._on_failed)
        wk.cancelled.connect(self._on_cancelled)
        for sig in (wk.finished, wk.failed, wk.cancelled):
            sig.connect(th.quit)
        th.finished.connect(lambda th=th: self._reap(th))
        self._threads.append((th, wk))       # keep references until the thread ends
        th.start()
        return True

    def cancel(self) -> None:
        """Ask the job to stop; if it does not answer within 3 s, release the UI anyway."""
        if not self._active:
            return
        self._cancel.set()
        tok = self._active
        QTimer.singleShot(3000, lambda: self._force_cancel(tok))

    def _force_cancel(self, tok: int) -> None:
        if self._active == tok:              # worker is still busy (e.g. a slow disk)
            self._active = 0
            self.cancelled.emit()

    # --- token filtering ----------------------------------------------------------
    def _on_progress(self, tok, stage, done, total):
        if tok == self._active:
            self.progress.emit(stage, done, total)

    def _on_finished(self, tok, res):
        if tok == self._active:
            self._active = 0
            self.finished.emit(res)

    def _on_failed(self, tok, tb):
        if tok == self._active:
            self._active = 0
            self.failed.emit(tb)

    def _on_cancelled(self, tok):
        if tok == self._active:
            self._active = 0
            self.cancelled.emit()

    def _reap(self, th: QThread) -> None:
        self._threads = [(t, w) for t, w in self._threads if t is not th]
        th.deleteLater()

    def shutdown(self, timeout_ms: int = 4000) -> None:
        self._cancel.set()
        for th, _ in list(self._threads):
            th.quit()
            th.wait(timeout_ms)


ScanController = TaskRunner   # backwards compatible name
