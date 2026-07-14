"""Cancellable clone via a raw subprocess -- deliberately NOT GitPython's
Repo.clone_from(), which blocks synchronously with no handle to kill mid-flight.
"""
from __future__ import annotations

import os
import re
import subprocess
import threading
from typing import Callable

_PERCENT_RE = re.compile(r"(\d+)%")


class CloneCancelled(Exception):
    pass


class CloneFailed(Exception):
    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.detail = detail


class CloneHandle:
    """Returned immediately so the UI can offer a Cancel button while the
    clone runs on a worker thread."""

    def __init__(self):
        self._process: subprocess.Popen | None = None
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()
        if self._process is not None:
            self._process.terminate()


def clone_repo(
    url: str,
    dest: str,
    token: str | None,
    progress_cb: Callable[[str, int], None],
    handle: CloneHandle,
) -> None:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"

    cmd = ["git"]
    if token:
        cmd += ["-c", f"http.extraHeader=Authorization: Bearer {token}"]
    cmd += ["clone", "--progress", url, dest]

    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, bufsize=1
    )
    handle._process = process

    stderr_lines: list[str] = []
    assert process.stderr is not None
    for line in process.stderr:
        stderr_lines.append(line)
        if handle._cancel_event.is_set():
            process.terminate()
            process.wait()
            raise CloneCancelled()
        stage = line.split(":", 1)[0].strip() or "Cloning"
        match = _PERCENT_RE.search(line)
        percent = int(match.group(1)) if match else 0
        progress_cb(stage, percent)

    process.wait()

    if handle._cancel_event.is_set():
        raise CloneCancelled()
    if process.returncode != 0:
        raise CloneFailed(f"git clone failed (exit code {process.returncode})", "".join(stderr_lines))
