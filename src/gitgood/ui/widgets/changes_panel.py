"""Unstaged/staged file lists with stage, unstage, and discard actions."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gitgood.git_ops.repository import StatusResult


def _entry_label(path: str, change_type: str) -> str:
    return f"[{change_type}]  {path}"


class ChangesPanel(QWidget):
    stage_requested = Signal(list)  # list[str] paths
    unstage_requested = Signal(list)
    discard_requested = Signal(list)
    file_selected = Signal(str, bool)  # path, is_staged
    gitignore_requested = Signal(list)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QLabel("Unstaged changes"))
        self.unstaged_list = QListWidget()
        self.unstaged_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.unstaged_list.itemSelectionChanged.connect(self._on_unstaged_selection)
        layout.addWidget(self.unstaged_list)

        unstaged_btn_row = QHBoxLayout()
        self.stage_btn = QPushButton("Stage Selected")
        self.stage_btn.clicked.connect(self._on_stage_selected)
        self.stage_all_btn = QPushButton("Stage All")
        self.stage_all_btn.clicked.connect(self._on_stage_all)
        self.discard_btn = QPushButton("Discard")
        self.discard_btn.clicked.connect(self._on_discard_selected)
        self.gitignore_btn = QPushButton("Ignore")
        self.gitignore_btn.clicked.connect(self._on_gitignore_selected)
        for btn in (self.stage_btn, self.stage_all_btn, self.discard_btn, self.gitignore_btn):
            unstaged_btn_row.addWidget(btn)
        layout.addLayout(unstaged_btn_row)

        layout.addWidget(QLabel("Staged changes"))
        self.staged_list = QListWidget()
        self.staged_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.staged_list.itemSelectionChanged.connect(self._on_staged_selection)
        layout.addWidget(self.staged_list)

        staged_btn_row = QHBoxLayout()
        self.unstage_btn = QPushButton("Unstage Selected")
        self.unstage_btn.clicked.connect(self._on_unstage_selected)
        self.unstage_all_btn = QPushButton("Unstage All")
        self.unstage_all_btn.clicked.connect(self._on_unstage_all)
        staged_btn_row.addWidget(self.unstage_btn)
        staged_btn_row.addWidget(self.unstage_all_btn)
        layout.addLayout(staged_btn_row)

        self._status: StatusResult | None = None

    def set_status(self, status: StatusResult) -> None:
        self._status = status
        self.unstaged_list.clear()
        for change in status.unstaged:
            item = QListWidgetItem(_entry_label(change.path, change.change_type))
            item.setData(1000, change.path)
            self.unstaged_list.addItem(item)
        for path in status.untracked:
            item = QListWidgetItem(_entry_label(path, "?"))
            item.setData(1000, path)
            self.unstaged_list.addItem(item)
        for path in status.conflicted:
            item = QListWidgetItem(_entry_label(path, "!"))
            item.setData(1000, path)
            self.unstaged_list.addItem(item)

        self.staged_list.clear()
        for change in status.staged:
            item = QListWidgetItem(_entry_label(change.path, change.change_type))
            item.setData(1000, change.path)
            self.staged_list.addItem(item)

    def _selected_paths(self, list_widget: QListWidget) -> list[str]:
        return [item.data(1000) for item in list_widget.selectedItems()]

    def _all_paths(self, list_widget: QListWidget) -> list[str]:
        return [list_widget.item(i).data(1000) for i in range(list_widget.count())]

    def _on_stage_selected(self) -> None:
        paths = self._selected_paths(self.unstaged_list)
        if paths:
            self.stage_requested.emit(paths)

    def _on_stage_all(self) -> None:
        paths = self._all_paths(self.unstaged_list)
        if paths:
            self.stage_requested.emit(paths)

    def _on_unstage_selected(self) -> None:
        paths = self._selected_paths(self.staged_list)
        if paths:
            self.unstage_requested.emit(paths)

    def _on_unstage_all(self) -> None:
        paths = self._all_paths(self.staged_list)
        if paths:
            self.unstage_requested.emit(paths)

    def _on_discard_selected(self) -> None:
        paths = self._selected_paths(self.unstaged_list)
        if not paths:
            return
        reply = QMessageBox.question(
            self,
            "Discard changes",
            f"Discard changes to {len(paths)} file(s)? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.discard_requested.emit(paths)

    def _on_gitignore_selected(self) -> None:
        paths = self._selected_paths(self.unstaged_list)
        if paths:
            self.gitignore_requested.emit(paths)

    def _on_unstaged_selection(self) -> None:
        items = self.unstaged_list.selectedItems()
        if items:
            self.staged_list.clearSelection()
            self.file_selected.emit(items[0].data(1000), False)

    def _on_staged_selection(self) -> None:
        items = self.staged_list.selectedItems()
        if items:
            self.unstaged_list.clearSelection()
            self.file_selected.emit(items[0].data(1000), True)
