"""Runs a single cancellable clone on its own QThread. Separate from
RepoWorker since there's no existing Repository to own a job queue for yet --
this object is created fresh per clone and discarded when it finishes."""
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal

from gitgood.git_ops.clone import CloneCancelled, CloneFailed, CloneHandle, clone_repo


class CloneWorker(QObject):
    progress = Signal(str, int)  # stage, percent
    succeeded = Signal(str)  # dest path
    failed = Signal(str, str)  # message, detail
    canceled = Signal()

    def __init__(self, url: str, dest: str, token: str | None):
        super().__init__()
        self._url = url
        self._dest = dest
        self._token = token
        self.handle = CloneHandle()

    def run(self) -> None:
        try:
            clone_repo(self._url, self._dest, self._token, self._emit_progress, self.handle)
        except CloneCancelled:
            self.canceled.emit()
        except CloneFailed as e:
            self.failed.emit(str(e), e.detail)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e), "")
        else:
            self.succeeded.emit(self._dest)

    def _emit_progress(self, stage: str, percent: int) -> None:
        self.progress.emit(stage, percent)

    def cancel(self) -> None:
        self.handle.cancel()


def start_clone(url: str, dest: str, token: str | None) -> tuple[CloneWorker, QThread]:
    thread = QThread()
    worker = CloneWorker(url, dest, token)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    for sig in (worker.succeeded, worker.failed, worker.canceled):
        sig.connect(thread.quit)
    thread.start()
    return worker, thread
