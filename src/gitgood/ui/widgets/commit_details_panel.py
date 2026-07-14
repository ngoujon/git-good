"""Files changed in a selected historical commit, with a diff view -- the
read-only, history-browsing counterpart to ChangesPanel/SideBySideDiffView."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from gitgood.git_ops.repository import ChangeEntry
from gitgood.ui.widgets.diff_view import SideBySideDiffView


def _entry_label(path: str, change_type: str) -> str:
    return f"[{change_type}]  {path}"


class CommitDetailsPanel(QWidget):
    file_selected = Signal(str)  # path

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.summary_label = QLabel("Select a commit to see what changed")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("font-weight: 600; padding: 4px;")
        layout.addWidget(self.summary_label)

        splitter = QSplitter()
        self.file_list = QListWidget()
        self.file_list.setMaximumWidth(280)
        self.file_list.itemSelectionChanged.connect(self._on_selection_changed)
        splitter.addWidget(self.file_list)

        self.diff_view = SideBySideDiffView()
        splitter.addWidget(self.diff_view)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

    def set_commit(self, sha: str, summary: str, files: list[ChangeEntry]) -> None:
        self.summary_label.setText(f"{sha[:7]}  {summary}")
        self.file_list.clear()
        for change in files:
            item = QListWidgetItem(_entry_label(change.path, change.change_type))
            item.setData(1000, change.path)
            self.file_list.addItem(item)
        self.diff_view.set_diff("", "")
        if files:
            self.file_list.setCurrentRow(0)

    def refresh_theme(self) -> None:
        self.diff_view.refresh_theme()

    def _on_selection_changed(self) -> None:
        items = self.file_list.selectedItems()
        if items:
            self.file_selected.emit(items[0].data(1000))
