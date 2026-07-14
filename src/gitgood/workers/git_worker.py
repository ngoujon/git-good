"""One long-lived worker per open repository, running on its own QThread with
a serial job queue -- concurrent git operations on the same working tree race
on index.lock, so this deliberately is NOT a thread pool. The UI thread never
touches a `Repository`/`git.Repo` object directly; it only submits callables
and reacts to signals.
"""
from __future__ import annotations

import queue
import uuid
from dataclasses import dataclass
from typing import Any, Callable

import git
from PySide6.QtCore import QObject, QThread, Signal

from gitgood.git_ops.repository import GitOpError, Repository

JobFunc = Callable[[Repository, Callable[[str, int], None]], Any]


class _ProgressRelay(git.RemoteProgress):
    """Adapts GitPython's RemoteProgress callbacks into (stage, percent)."""

    _OP_NAMES = {
        git.RemoteProgress.COUNTING: "Counting objects",
        git.RemoteProgress.COMPRESSING: "Compressing objects",
        git.RemoteProgress.RECEIVING: "Receiving objects",
        git.RemoteProgress.RESOLVING: "Resolving deltas",
    }

    def __init__(self, callback: Callable[[str, int], None]):
        super().__init__()
        self._callback = callback

    def update(self, op_code, cur_count, max_count=None, message=""):
        stage = self._OP_NAMES.get(op_code & self.OP_MASK, "Working")
        percent = int(cur_count / float(max_count) * 100) if max_count else 0
        self._callback(stage, percent)


@dataclass
class _Job:
    job_id: str
    func: JobFunc


class RepoWorker(QObject):
    progress = Signal(str, str, int)  # job_id, stage, percent
    succeeded = Signal(str, object)  # job_id, result
    failed = Signal(str, str, str)  # job_id, message, detail

    def __init__(self, repo_path: str):
        super().__init__()
        self._repo_path = repo_path
        self._repo: Repository | None = None
        self._queue: queue.Queue[_Job | None] = queue.Queue()

    def submit(self, func: JobFunc) -> str:
        """Thread-safe: called from the UI thread, queued for the worker thread."""
        job_id = str(uuid.uuid4())
        self._queue.put(_Job(job_id, func))
        return job_id

    def run(self) -> None:
        """Entry point once this QObject has been moved to its QThread."""
        self._repo = Repository(self._repo_path)
        while True:
            job = self._queue.get()
            if job is None:
                break
            try:
                result = job.func(self._repo, lambda stage, pct: self.progress.emit(job.job_id, stage, pct))
            except GitOpError as e:
                self.failed.emit(job.job_id, str(e), e.detail)
            except Exception as e:  # noqa: BLE001 - surface any failure to the UI, never crash the worker thread
                self.failed.emit(job.job_id, str(e), "")
            else:
                self.succeeded.emit(job.job_id, result)

    def stop(self) -> None:
        self._queue.put(None)


def wrap_progress(progress_cb: Callable[[str, int], None]) -> _ProgressRelay:
    """Adapt a plain (stage, percent) callback into a git.RemoteProgress
    instance, for passing to Repository.fetch/pull/push(progress=...)."""
    return _ProgressRelay(progress_cb)


def make_repo_worker(repo_path: str) -> tuple[RepoWorker, QThread]:
    """Create a RepoWorker already moved to (and started on) its own QThread."""
    thread = QThread()
    worker = RepoWorker(repo_path)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    thread.start()
    return worker, thread
