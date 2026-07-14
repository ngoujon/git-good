"""Conflict resolution UI shared by merge AND rebase -- both leave the same
stage-1/2/3 unmerged-blob data in the index, so one widget handles both."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from gitgood.git_ops.repository import ConflictInfo


class ConflictResolverDialog(QDialog):
    resolve_file_requested = Signal(str, str)  # path, resolved content
    conclude_requested = Signal()  # user clicked Continue once everything is resolved

    def __init__(self, conflicts: list[ConflictInfo], operation_label: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Resolve conflicts ({operation_label})")
        self.setMinimumSize(800, 560)

        self._conflicts = {c.path: c for c in conflicts}
        self._resolved: set[str] = set()

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"{operation_label} has conflicts. Resolve each file, then continue."))

        splitter = QSplitter()
        self.file_list = QListWidget()
        self.file_list.itemSelectionChanged.connect(self._on_file_selected)
        splitter.addWidget(self.file_list)

        right = QWidget()
        right_layout = QVBoxLayout(right)

        three_way = QHBoxLayout()
        self.ours_view = self._make_readonly_view("Ours (current)")
        self.theirs_view = self._make_readonly_view("Theirs (incoming)")
        three_way.addLayout(self._labeled(self.ours_view, "Ours"))
        three_way.addLayout(self._labeled(self.theirs_view, "Theirs"))
        right_layout.addLayout(three_way)

        right_layout.addWidget(QLabel("Resolution (edit freely, or use a quick pick above):"))
        self.resolution_edit = QPlainTextEdit()
        right_layout.addWidget(self.resolution_edit)

        pick_row = QHBoxLayout()
        use_ours_btn = QPushButton("Use Ours")
        use_ours_btn.clicked.connect(lambda: self.resolution_edit.setPlainText(self._current().ours_text or ""))
        use_theirs_btn = QPushButton("Use Theirs")
        use_theirs_btn.clicked.connect(lambda: self.resolution_edit.setPlainText(self._current().theirs_text or ""))
        mark_resolved_btn = QPushButton("Mark Resolved")
        mark_resolved_btn.clicked.connect(self._on_mark_resolved)
        pick_row.addWidget(use_ours_btn)
        pick_row.addWidget(use_theirs_btn)
        pick_row.addWidget(mark_resolved_btn)
        right_layout.addLayout(pick_row)

        splitter.addWidget(right)
        layout.addWidget(splitter)

        bottom_row = QHBoxLayout()
        self.status_label = QLabel("")
        self.continue_btn = QPushButton("Continue")
        self.continue_btn.setEnabled(False)
        self.continue_btn.clicked.connect(self.conclude_requested.emit)
        bottom_row.addWidget(self.status_label)
        bottom_row.addStretch(1)
        bottom_row.addWidget(self.continue_btn)
        layout.addLayout(bottom_row)

        self._refresh_file_list()

    def _make_readonly_view(self, _label: str) -> QPlainTextEdit:
        view = QPlainTextEdit()
        view.setReadOnly(True)
        return view

    def _labeled(self, widget: QWidget, text: str):
        col = QVBoxLayout()
        col.addWidget(QLabel(text))
        col.addWidget(widget)
        return col

    def _current(self) -> ConflictInfo:
        items = self.file_list.selectedItems()
        return self._conflicts[items[0].data(1000)]

    def _refresh_file_list(self) -> None:
        self.file_list.clear()
        for path in self._conflicts:
            mark = "✓ " if path in self._resolved else ""
            item = QListWidgetItem(f"{mark}{path}")
            item.setData(1000, path)
            self.file_list.addItem(item)
        self.continue_btn.setEnabled(len(self._resolved) == len(self._conflicts))
        self.status_label.setText(f"{len(self._resolved)}/{len(self._conflicts)} resolved")

    def _on_file_selected(self) -> None:
        if not self.file_list.selectedItems():
            return
        conflict = self._current()
        self.ours_view.setPlainText(conflict.ours_text or "(deleted)")
        self.theirs_view.setPlainText(conflict.theirs_text or "(deleted)")
        self.resolution_edit.setPlainText(conflict.ours_text or conflict.theirs_text or "")

    def _on_mark_resolved(self) -> None:
        if not self.file_list.selectedItems():
            return
        path = self.file_list.selectedItems()[0].data(1000)
        content = self.resolution_edit.toPlainText()
        self.resolve_file_requested.emit(path, content)
        self._resolved.add(path)
        self._refresh_file_list()
