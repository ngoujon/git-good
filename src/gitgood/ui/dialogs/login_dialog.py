"""GitHub PAT entry: validates the token against the API on a background
thread (so the dialog never freezes), then stores it in the Keychain."""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from gitgood.auth import github_auth
from gitgood.auth.github_api import GitHubAuthError, GitHubClient, GitHubUser


class _Validator(QObject):
    finished = Signal(object, str)  # GitHubUser | None, error message

    def validate(self, token: str) -> None:
        def work():
            try:
                user = GitHubClient(token).current_user()
            except GitHubAuthError as e:
                self.finished.emit(None, str(e))
            except Exception as e:  # noqa: BLE001 - an uncaught error here would silently kill this
                # background thread and leave the dialog stuck on "Validating..." forever.
                self.finished.emit(None, f"Unexpected error: {e}")
            else:
                self.finished.emit(user, "")

        threading.Thread(target=work, daemon=True).start()


class LoginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sign in to GitHub")
        self.setMinimumWidth(420)
        self.authenticated_user: GitHubUser | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Paste a GitHub Personal Access Token (Settings → Developer settings "
                "→ Personal access tokens) with the 'repo' scope."
            )
        )
        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit.setPlaceholderText("ghp_...")
        layout.addWidget(self.token_edit)

        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._on_ok_clicked)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self._validator = _Validator()
        self._validator.finished.connect(self._on_validated)

    def _on_ok_clicked(self) -> None:
        token = self.token_edit.text().strip()
        if not token:
            self.status_label.setText("Please enter a token.")
            return
        self.status_label.setText("Validating...")
        self.buttons.setEnabled(False)
        self._validator.validate(token)

    def _on_validated(self, user: GitHubUser | None, error: str) -> None:
        self.buttons.setEnabled(True)
        if user is None:
            self.status_label.setText(error or "Invalid token.")
            return
        try:
            github_auth.set_token(self.token_edit.text().strip())
        except Exception as e:  # noqa: BLE001 - a broken Keychain backend must show an error, not crash
            self.status_label.setText(f"Could not save token: {e}")
            return
        self.authenticated_user = user
        self.accept()
