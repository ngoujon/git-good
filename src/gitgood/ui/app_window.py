"""The app's single top-level window: a persistent toolbar of per-repo git
actions, with a GitKraken/Fork-style left sidebar (open repos + GitHub
account) beside a QStackedWidget where each page is an independently-running
RepoTab. Replaces the old one-window-per-repo MainWindow and the one-shot
startup dialog that used to be the only way to sign in to GitHub or clone a
repo."""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QToolBar,
)

from gitgood.auth import github_auth
from gitgood.auth.github_api import GitHubAuthError, GitHubClient
from gitgood.ui.dialogs.clone_dialog import CloneDialog
from gitgood.ui.dialogs.login_dialog import LoginDialog
from gitgood.ui.repo_tab import RepoTab
from gitgood.ui.widgets.repo_sidebar import RepoSidebar


class AppWindow(QMainWindow):
    _account_resolved = Signal(object)  # str login | None -- see _refresh_account_state

    def __init__(self):
        super().__init__()
        self.setWindowTitle("GitGood")
        self.resize(1200, 720)

        self._repo_toolbar_buttons: list[QPushButton] = []

        toolbar = QToolBar()
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        for label, handler in (
            ("Fetch", lambda: self._on_active_tab(RepoTab.fetch)),
            ("Pull", lambda: self._on_active_tab(RepoTab.pull)),
            ("Push", lambda: self._on_active_tab(RepoTab.push)),
            ("Branches...", lambda: self._on_active_tab(RepoTab.open_branches_dialog)),
            ("Merge...", lambda: self._on_active_tab(RepoTab.open_merge_dialog)),
            ("Rebase...", lambda: self._on_active_tab(RepoTab.open_rebase_dialog)),
            ("Refresh", lambda: self._on_active_tab(RepoTab.refresh_all)),
        ):
            btn = QPushButton(label)
            btn.clicked.connect(handler)
            toolbar.addWidget(btn)
            self._repo_toolbar_buttons.append(btn)

        self.sidebar = RepoSidebar()
        self.sidebar.open_requested.connect(self._on_open_clicked)
        self.sidebar.clone_requested.connect(self._on_clone_clicked)
        self.sidebar.repo_activated.connect(self._on_repo_activated)
        self.sidebar.repo_close_requested.connect(self._on_repo_close_requested)
        self.sidebar.account_widget.sign_in_requested.connect(self._on_sign_in_requested)
        self.sidebar.account_widget.sign_out_requested.connect(self._on_sign_out_requested)
        self._account_resolved.connect(self.sidebar.account_widget.set_signed_in)

        self.empty_label = QLabel("Open or clone a repository to get started")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: palette(mid); font-size: 15px;")

        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(self.empty_label)

        splitter = QSplitter()
        splitter.addWidget(self.sidebar)
        splitter.addWidget(self.content_stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 960])
        self.setCentralWidget(splitter)

        self.statusBar().showMessage("Ready")
        self._update_repo_toolbar_enabled()
        self._refresh_account_state()

    # ---- repo management -----------------------------------------------------------

    def open_repo_path(self, path: str) -> None:
        try:
            tab = RepoTab(path)
        except Exception as e:  # noqa: BLE001 - surface a dialog instead of a silent crash
            QMessageBox.critical(self, "GitGood", f"Could not open repository:\n{e}")
            return
        tab.status_message.connect(lambda msg, t=tab: self._on_tab_status_message(t, msg))
        tab.changes_count_changed.connect(lambda n, t=tab: self.sidebar.set_change_count(t, n))
        self.content_stack.addWidget(tab)
        self.sidebar.add_repo(tab, path)  # selects it, which triggers _on_repo_activated

    def all_repo_tabs(self) -> list[RepoTab]:
        return [
            self.content_stack.widget(i)
            for i in range(self.content_stack.count())
            if isinstance(self.content_stack.widget(i), RepoTab)
        ]

    def _on_repo_activated(self, tab) -> None:
        if tab is None:
            self.content_stack.setCurrentWidget(self.empty_label)
            self.setWindowTitle("GitGood")
        else:
            self.content_stack.setCurrentWidget(tab)
            self.setWindowTitle(f"GitGood — {Path(tab.repo_path).name}")
        self._update_repo_toolbar_enabled()

    def _on_repo_close_requested(self, tab) -> None:
        tab.shutdown()
        self.sidebar.remove_repo(tab)
        self.content_stack.removeWidget(tab)
        tab.deleteLater()
        self._update_repo_toolbar_enabled()

    def _on_tab_status_message(self, tab: RepoTab, message: str) -> None:
        if self._current_tab() is tab:
            self.statusBar().showMessage(message)

    def _current_tab(self) -> RepoTab | None:
        widget = self.content_stack.currentWidget()
        return widget if isinstance(widget, RepoTab) else None

    def _on_active_tab(self, method) -> None:
        tab = self._current_tab()
        if tab is not None:
            method(tab)

    def _update_repo_toolbar_enabled(self) -> None:
        enabled = self._current_tab() is not None
        for btn in self._repo_toolbar_buttons:
            btn.setEnabled(enabled)

    # ---- open / clone ---------------------------------------------------------------

    def _on_open_clicked(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Open a git repository")
        if path:
            self.open_repo_path(path)

    def _on_clone_clicked(self) -> None:
        token = github_auth.get_token()
        if not token:
            login = LoginDialog(self)
            if login.exec() != LoginDialog.DialogCode.Accepted:
                return
            token = github_auth.get_token()
            self._refresh_account_state()
        clone_dialog = CloneDialog(token, self)
        clone_dialog.repo_cloned.connect(self.open_repo_path)
        clone_dialog.exec()

    # ---- GitHub account ---------------------------------------------------------------

    def _refresh_account_state(self) -> None:
        token = github_auth.get_token()
        if not token:
            self.sidebar.account_widget.set_signed_in(None)
            return

        def work():
            try:
                user = GitHubClient(token).current_user()
            except GitHubAuthError:
                github_auth.clear_token()
                self._account_resolved.emit(None)
            else:
                self._account_resolved.emit(user.login)

        threading.Thread(target=work, daemon=True).start()

    def _on_sign_in_requested(self) -> None:
        login = LoginDialog(self)
        if login.exec() == LoginDialog.DialogCode.Accepted and login.authenticated_user:
            self.sidebar.account_widget.set_signed_in(login.authenticated_user.login)

    def _on_sign_out_requested(self) -> None:
        reply = QMessageBox.question(
            self,
            "Sign out",
            "Sign out of GitHub? You can sign back in at any time.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            github_auth.clear_token()
            self.sidebar.account_widget.set_signed_in(None)

    # ---- lifecycle ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        for tab in self.all_repo_tabs():
            tab.shutdown()
        super().closeEvent(event)
