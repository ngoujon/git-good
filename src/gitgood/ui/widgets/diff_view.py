"""Side-by-side diff viewer: old text on the left, new text on the right,
row-aligned with blank-line padding (the classic technique), backgrounds
highlighted per changed line, scrollbars kept in sync.
"""
from __future__ import annotations

import difflib

from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QSplitter, QWidget

from gitgood.ui import theme as theme_mod


def _aligned_lines(old_lines: list[str], new_lines: list[str]) -> tuple[list[str], list[str], list[str | None], list[str | None]]:
    """Returns (left_lines, right_lines, left_kinds, right_kinds) where kinds
    are 'del'/'ins'/None, row-aligned so unchanged lines line up."""
    left: list[str] = []
    right: list[str] = []
    left_kinds: list[str | None] = []
    right_kinds: list[str | None] = []

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        old_chunk = old_lines[i1:i2]
        new_chunk = new_lines[j1:j2]
        if op == "equal":
            left.extend(old_chunk)
            right.extend(new_chunk)
            left_kinds.extend([None] * len(old_chunk))
            right_kinds.extend([None] * len(new_chunk))
        else:
            pad = max(len(old_chunk), len(new_chunk))
            left.extend(old_chunk + [""] * (pad - len(old_chunk)))
            right.extend(new_chunk + [""] * (pad - len(new_chunk)))
            left_kinds.extend(["del"] * len(old_chunk) + [None] * (pad - len(old_chunk)))
            right_kinds.extend(["ins"] * len(new_chunk) + [None] * (pad - len(new_chunk)))

    return left, right, left_kinds, right_kinds


class SideBySideDiffView(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._theme = theme_mod.current_theme()

        self.left = QPlainTextEdit()
        self.right = QPlainTextEdit()
        for editor in (self.left, self.right):
            editor.setReadOnly(True)
            editor.setFont(QFont("Menlo", 12))
            editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self._syncing = False
        self.left.verticalScrollBar().valueChanged.connect(self._sync_from_left)
        self.right.verticalScrollBar().valueChanged.connect(self._sync_from_right)

        splitter = QSplitter(self)
        splitter.addWidget(self.left)
        splitter.addWidget(self.right)

        from PySide6.QtWidgets import QHBoxLayout

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

    def refresh_theme(self) -> None:
        self._theme = theme_mod.current_theme()

    def _sync_from_left(self, value: int) -> None:
        if self._syncing:
            return
        self._syncing = True
        self.right.verticalScrollBar().setValue(value)
        self._syncing = False

    def _sync_from_right(self, value: int) -> None:
        if self._syncing:
            return
        self._syncing = True
        self.left.verticalScrollBar().setValue(value)
        self._syncing = False

    def set_diff(self, old_text: str, new_text: str) -> None:
        old_lines = old_text.splitlines()
        new_lines = new_text.splitlines()
        left_lines, right_lines, left_kinds, right_kinds = _aligned_lines(old_lines, new_lines)

        self.left.setPlainText("\n".join(left_lines))
        self.right.setPlainText("\n".join(right_lines))
        self._highlight(self.left, left_kinds, "diff_del_bg")
        self._highlight(self.right, right_kinds, "diff_add_bg")

    def _highlight(self, editor: QPlainTextEdit, kinds: list[str | None], bg_key: str) -> None:
        color = QColor(self._theme[bg_key])
        fmt = QTextCharFormat()
        fmt.setBackground(color)

        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        for kind in kinds:
            cursor.select(QTextCursor.SelectionType.LineUnderCursor)
            if kind is not None:
                cursor.mergeCharFormat(fmt)
            cursor.movePosition(QTextCursor.MoveOperation.NextBlock)
