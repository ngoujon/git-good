"""Left sidebar listing every open repository -- the GitKraken/Fork-style
replacement for a plain top tab bar. Owns the repo list, the Open/Clone
entry points, and the persistent GitHub account indicator; AppWindow just
wires its signals to RepoTab lifecycle."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from gitgood.ui import theme as theme_mod
from gitgood.ui.widgets.account_widget import AccountWidget

_TAB_DATA_ROLE = Qt.ItemDataRole.UserRole


class _RepoRow(QWidget):
    """One sidebar entry: avatar, repo name + path, pending-changes badge,
    and a close button. Purely presentational -- RepoSidebar owns identity
    (which RepoTab this row maps to) and list membership."""

    close_clicked = Signal()

    def __init__(self, name: str, path: str, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

        self.avatar = QLabel(name[:1].upper() if name else "?")
        self.avatar.setFixedSize(28, 28)
        self.avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        color = theme_mod.avatar_color(name)
        self.avatar.setStyleSheet(
            f"background-color: {color}; color: white; border-radius: 6px; font-weight: 700;"
        )
        layout.addWidget(self.avatar)

        text_col = QVBoxLayout()
        text_col.setSpacing(0)
        self.name_label = QLabel(name)
        self.name_label.setStyleSheet("font-weight: 600;")
        text_col.addWidget(self.name_label)
        self.path_label = QLabel(path)
        self.path_label.setStyleSheet("color: palette(mid); font-size: 11px;")
        text_col.addWidget(self.path_label)
        layout.addLayout(text_col, 1)

        self.badge = QLabel("")
        self.badge.setObjectName("repoBadge")
        self.badge.setVisible(False)
        layout.addWidget(self.badge)

        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("repoCloseButton")
        self.close_btn.setFixedSize(20, 20)
        self.close_btn.setToolTip("Close repository")
        self.close_btn.clicked.connect(self.close_clicked.emit)
        layout.addWidget(self.close_btn)

        self.setToolTip(path)

    def set_change_count(self, count: int) -> None:
        if count > 0:
            self.badge.setText(str(count) if count <= 99 else "99+")
            self.badge.setVisible(True)
        else:
            self.badge.setVisible(False)


class RepoSidebar(QWidget):
    open_requested = Signal()
    clone_requested = Signal()
    repo_activated = Signal(object)  # RepoTab | None
    repo_close_requested = Signal(object)  # RepoTab

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("repoSidebar")
        self.setMinimumWidth(220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        header = QHBoxLayout()
        style = self.style()
        open_btn = QPushButton(style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon), " Open")
        open_btn.setObjectName("sidebarIconButton")
        open_btn.clicked.connect(self.open_requested.emit)
        clone_btn = QPushButton(style.standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon), " Clone")
        clone_btn.setObjectName("sidebarIconButton")
        clone_btn.clicked.connect(self.clone_requested.emit)
        header.addWidget(open_btn)
        header.addWidget(clone_btn)
        layout.addLayout(header)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("repoList")
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.list_widget.currentItemChanged.connect(self._on_current_item_changed)
        layout.addWidget(self.list_widget, 1)

        self.account_widget = AccountWidget()
        layout.addWidget(self.account_widget)

        self._rows: dict[object, _RepoRow] = {}

    # ---- repo list management ---------------------------------------------------

    def add_repo(self, tab, path: str) -> None:
        name = Path(path).name
        item = QListWidgetItem()
        item.setData(_TAB_DATA_ROLE, tab)
        row = _RepoRow(name, path)
        row.close_clicked.connect(lambda t=tab: self.repo_close_requested.emit(t))
        item.setSizeHint(row.sizeHint())
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, row)
        self._rows[tab] = row
        self.list_widget.setCurrentItem(item)

    def remove_repo(self, tab) -> None:
        for i in range(self.list_widget.count()):
            if self.list_widget.item(i).data(_TAB_DATA_ROLE) is tab:
                self.list_widget.takeItem(i)
                break
        self._rows.pop(tab, None)

    def set_change_count(self, tab, count: int) -> None:
        row = self._rows.get(tab)
        if row is not None:
            row.set_change_count(count)

    def _on_current_item_changed(self, current: QListWidgetItem | None, _previous) -> None:
        tab = current.data(_TAB_DATA_ROLE) if current is not None else None
        self.repo_activated.emit(tab)
