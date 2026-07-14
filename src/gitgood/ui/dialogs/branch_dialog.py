"""Branch management: checkout/create/rename/delete. Also doubles as a plain
branch picker (`selection_only=True`) for choosing a merge/rebase target."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from gitgood.git_ops.repository import BranchInfo


class BranchDialog(QDialog):
    checkout_requested = Signal(str)
    create_requested = Signal(str, str)  # new name, start point (may be "")
    rename_requested = Signal(str, str)  # old, new
    delete_requested = Signal(str)

    def __init__(self, branches: list[BranchInfo], current_branch: str | None, selection_only: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Choose a branch" if selection_only else "Branches")
        self.setMinimumSize(420, 480)
        self._selection_only = selection_only
        self.selected_branch: str | None = None

        layout = QVBoxLayout(self)
        self.list_widget = QListWidget()
        for branch in branches:
            label = branch.name
            if branch.is_current:
                label += "  (current)"
            elif branch.is_remote:
                label += "  (remote)"
            item = QListWidgetItem(label)
            item.setData(1000, branch.name)
            self.list_widget.addItem(item)
        self.list_widget.itemDoubleClicked.connect(self._on_double_clicked)
        layout.addWidget(self.list_widget)

        button_row = QHBoxLayout()
        if selection_only:
            select_btn = QPushButton("Select")
            select_btn.clicked.connect(self._on_select_clicked)
            button_row.addWidget(select_btn)
        else:
            checkout_btn = QPushButton("Checkout")
            checkout_btn.clicked.connect(self._on_checkout_clicked)
            new_btn = QPushButton("New Branch...")
            new_btn.clicked.connect(self._on_new_clicked)
            rename_btn = QPushButton("Rename...")
            rename_btn.clicked.connect(self._on_rename_clicked)
            delete_btn = QPushButton("Delete")
            delete_btn.clicked.connect(self._on_delete_clicked)
            for btn in (checkout_btn, new_btn, rename_btn, delete_btn):
                button_row.addWidget(btn)
        layout.addLayout(button_row)

        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_box.rejected.connect(self.reject)
        layout.addWidget(close_box)

        self._current_branch = current_branch

    def _selected_name(self) -> str | None:
        items = self.list_widget.selectedItems()
        return items[0].data(1000) if items else None

    def _on_double_clicked(self, item: QListWidgetItem) -> None:
        if self._selection_only:
            self.selected_branch = item.data(1000)
            self.accept()
        else:
            self.checkout_requested.emit(item.data(1000))

    def _on_select_clicked(self) -> None:
        name = self._selected_name()
        if name:
            self.selected_branch = name
            self.accept()

    def _on_checkout_clicked(self) -> None:
        name = self._selected_name()
        if name:
            self.checkout_requested.emit(name)

    def _on_new_clicked(self) -> None:
        name, ok = QInputDialog.getText(self, "New branch", "Branch name:")
        if ok and name.strip():
            start_point = self._selected_name() or ""
            self.create_requested.emit(name.strip(), start_point)

    def _on_rename_clicked(self) -> None:
        old_name = self._selected_name()
        if not old_name:
            return
        new_name, ok = QInputDialog.getText(self, "Rename branch", "New name:", text=old_name)
        if ok and new_name.strip():
            self.rename_requested.emit(old_name, new_name.strip())

    def _on_delete_clicked(self) -> None:
        name = self._selected_name()
        if not name:
            return
        if name == self._current_branch:
            QMessageBox.warning(self, "Delete branch", "Cannot delete the currently checked-out branch.")
            return
        reply = QMessageBox.question(
            self, "Delete branch", f"Delete branch '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.delete_requested.emit(name)
