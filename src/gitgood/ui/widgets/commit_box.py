from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget


class CommitBox(QWidget):
    commit_requested = Signal(str, bool)  # message, amend

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.message_edit = QPlainTextEdit()
        self.message_edit.setPlaceholderText("Commit message...")
        self.message_edit.setFixedHeight(80)
        self.message_edit.textChanged.connect(self._update_button_state)
        layout.addWidget(self.message_edit)

        self.amend_checkbox = QCheckBox("Amend last commit")
        self.amend_checkbox.toggled.connect(self._update_button_state)
        layout.addWidget(self.amend_checkbox)

        self.commit_button = QPushButton("Commit")
        self.commit_button.clicked.connect(self._on_commit_clicked)
        layout.addWidget(self.commit_button)

        self._has_staged_changes = False
        self._update_button_state()

    def set_has_staged_changes(self, has_staged: bool) -> None:
        self._has_staged_changes = has_staged
        self._update_button_state()

    def _update_button_state(self) -> None:
        message_present = bool(self.message_edit.toPlainText().strip())
        can_commit = message_present and (self._has_staged_changes or self.amend_checkbox.isChecked())
        self.commit_button.setEnabled(can_commit)

    def _on_commit_clicked(self) -> None:
        message = self.message_edit.toPlainText().strip()
        if not message:
            return
        self.commit_requested.emit(message, self.amend_checkbox.isChecked())

    def clear(self) -> None:
        self.message_edit.clear()
        self.amend_checkbox.setChecked(False)
