from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gitgood.git_ops.repository import StashEntry


class StashPanel(QWidget):
    save_requested = Signal(str, bool)  # message, include_untracked
    apply_requested = Signal(int)
    pop_requested = Signal(int)
    drop_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        button_row = QHBoxLayout()
        save_btn = QPushButton("Stash Changes")
        save_btn.clicked.connect(self._on_save_clicked)
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(lambda: self._emit_for_selected(self.apply_requested))
        pop_btn = QPushButton("Pop")
        pop_btn.clicked.connect(lambda: self._emit_for_selected(self.pop_requested))
        drop_btn = QPushButton("Drop")
        drop_btn.clicked.connect(self._on_drop_clicked)
        for btn in (save_btn, apply_btn, pop_btn, drop_btn):
            button_row.addWidget(btn)
        layout.addLayout(button_row)

    def set_stashes(self, stashes: list[StashEntry]) -> None:
        self.list_widget.clear()
        for entry in stashes:
            item = QListWidgetItem(f"stash@{{{entry.index}}}: {entry.message}")
            item.setData(1000, entry.index)
            self.list_widget.addItem(item)

    def _selected_index(self) -> int | None:
        items = self.list_widget.selectedItems()
        return items[0].data(1000) if items else None

    def _emit_for_selected(self, signal: Signal) -> None:
        index = self._selected_index()
        if index is not None:
            signal.emit(index)

    def _on_save_clicked(self) -> None:
        message, ok = QInputDialog.getText(self, "Stash changes", "Message (optional):")
        if ok:
            self.save_requested.emit(message.strip(), True)

    def _on_drop_clicked(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        reply = QMessageBox.question(
            self, "Drop stash", "Delete this stash entry? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.drop_requested.emit(index)
