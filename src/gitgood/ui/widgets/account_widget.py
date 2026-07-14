"""Persistent GitHub connection indicator, always visible in AppWindow's
toolbar -- the fix for there being no way back to sign in / see connection
status once the old one-shot startup dialog was dismissed."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QPushButton, QWidget


class AccountWidget(QPushButton):
    sign_in_requested = Signal()
    sign_out_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._signed_in = False
        self.set_signed_in(None)
        self.clicked.connect(self._on_clicked)

    def set_signed_in(self, login: str | None) -> None:
        self._signed_in = login is not None
        self.setText(f"@{login}" if login else "Sign in to GitHub")
        self.setToolTip("Click to sign out" if login else "Connect your GitHub account")

    def _on_clicked(self) -> None:
        if self._signed_in:
            self.sign_out_requested.emit()
        else:
            self.sign_in_requested.emit()
