"""GitHub sign-in via OAuth Device Flow: opens the user's browser to GitHub's
device-authorization page and polls in the background until they approve it
there -- no Personal Access Token to create or paste."""
from __future__ import annotations

import threading
import webbrowser

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from gitgood.auth import github_auth, github_oauth
from gitgood.auth.github_api import GitHubAuthError, GitHubClient, GitHubUser


class _DeviceFlowRunner(QObject):
    """Runs request_device_code() + poll_for_token() on a background thread
    and marshals results back via signals -- the same pattern CloneDialog
    and the old token validator used for background GitHub calls."""

    code_ready = Signal(object)  # DeviceCode
    finished = Signal(object, str)  # GitHubUser | None, error message

    def __init__(self):
        super().__init__()
        self._cancel_event = threading.Event()

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def cancel(self) -> None:
        self._cancel_event.set()

    def _run(self) -> None:
        try:
            code = github_oauth.request_device_code()
        except github_oauth.DeviceFlowError as e:
            self.finished.emit(None, str(e))
            return
        self.code_ready.emit(code)

        try:
            token = github_oauth.poll_for_token(code, self._cancel_event)
        except github_oauth.DeviceFlowCancelled:
            return
        except github_oauth.DeviceFlowError as e:
            self.finished.emit(None, str(e))
            return

        try:
            user = GitHubClient(token).current_user()
        except GitHubAuthError as e:
            self.finished.emit(None, str(e))
            return
        try:
            github_auth.set_token(token)
        except Exception as e:  # noqa: BLE001 - a broken Keychain backend must show an error, not crash
            self.finished.emit(None, f"Could not save token: {e}")
            return
        self.finished.emit(user, "")


class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sign in to GitHub")
        self.setMinimumWidth(420)
        self.authenticated_user: GitHubUser | None = None

        layout = QVBoxLayout(self)

        self.status_label = QLabel("Requesting a sign-in code from GitHub...")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.code_label = QLabel("")
        self.code_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.code_label.setStyleSheet("font-size: 28px; font-weight: 700; letter-spacing: 4px; padding: 8px;")
        self.code_label.setVisible(False)
        layout.addWidget(self.code_label)

        self.copy_btn = QPushButton("Copy code")
        self.copy_btn.setVisible(False)
        self.copy_btn.clicked.connect(self._on_copy_clicked)
        layout.addWidget(self.copy_btn)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.buttons.rejected.connect(self._on_cancel)
        layout.addWidget(self.buttons)

        self._runner = _DeviceFlowRunner()
        self._runner.code_ready.connect(self._on_code_ready)
        self._runner.finished.connect(self._on_finished)
        self._runner.start()

    def _on_code_ready(self, code) -> None:
        self.code_label.setText(code.user_code)
        self.code_label.setVisible(True)
        self.copy_btn.setVisible(True)
        self.status_label.setText(
            f"We opened {code.verification_uri} in your browser. Enter the code above "
            "there and approve GitGood -- this window closes automatically once you do."
        )
        webbrowser.open(code.verification_uri)

    def _on_copy_clicked(self) -> None:
        QGuiApplication.clipboard().setText(self.code_label.text())

    def _on_cancel(self) -> None:
        self._runner.cancel()
        self.reject()

    def _on_finished(self, user: GitHubUser | None, error: str) -> None:
        if user is None:
            self.status_label.setText(error or "Sign-in failed.")
            self.code_label.setVisible(False)
            self.copy_btn.setVisible(False)
            cancel_btn = self.buttons.button(QDialogButtonBox.StandardButton.Cancel)
            if cancel_btn:
                cancel_btn.setText("Close")
            return
        self.authenticated_user = user
        self.accept()
