"""Pick one of the signed-in user's GitHub repos and a destination folder,
then clone it with a cancellable progress bar."""
from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from gitgood.auth.github_api import GitHubAuthError, GitHubClient, GitHubRepo
from gitgood.workers.clone_worker import CloneWorker, start_clone


class CloneDialog(QDialog):
    repo_cloned = Signal(str)  # local path of the freshly cloned repo
    _repos_loaded = Signal(list, str)  # list[GitHubRepo], error message

    def __init__(self, token: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Clone a repository")
        self.setMinimumSize(520, 480)
        self._token = token
        self._repos: list[GitHubRepo] = []
        self._clone_worker: CloneWorker | None = None
        self._clone_thread = None

        layout = QVBoxLayout(self)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Filter repositories...")
        self.search_box.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search_box)

        self.repo_list = QListWidget()
        layout.addWidget(self.repo_list)

        dest_row = QHBoxLayout()
        self.dest_edit = QLineEdit(str(Path.home()))
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._on_browse)
        dest_row.addWidget(QLabel("Clone into:"))
        dest_row.addWidget(self.dest_edit)
        dest_row.addWidget(browse_btn)
        layout.addLayout(dest_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        self.status_label = QLabel("")
        layout.addWidget(self.status_label)

        button_row = QHBoxLayout()
        self.clone_btn = QPushButton("Clone")
        self.clone_btn.clicked.connect(self._on_clone_clicked)
        self.cancel_clone_btn = QPushButton("Cancel Clone")
        self.cancel_clone_btn.setVisible(False)
        self.cancel_clone_btn.clicked.connect(self._on_cancel_clone_clicked)
        close_btn = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btn.rejected.connect(self.reject)
        button_row.addWidget(self.clone_btn)
        button_row.addWidget(self.cancel_clone_btn)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

        self._repos_loaded.connect(self._on_repos_loaded)
        self._load_repos()

    # ---- repo listing -----------------------------------------------------------

    def _load_repos(self) -> None:
        self.status_label.setText("Loading your repositories...")

        def work():
            try:
                repos = GitHubClient(self._token).list_repos()
            except GitHubAuthError as e:
                self._repos_loaded.emit([], str(e))
            except Exception as e:  # noqa: BLE001 - an uncaught error here would silently kill this
                # background thread and leave the dialog stuck on "Loading..." forever.
                self._repos_loaded.emit([], f"Unexpected error: {e}")
            else:
                self._repos_loaded.emit(repos, "")

        threading.Thread(target=work, daemon=True).start()

    def _on_repos_loaded(self, repos: list[GitHubRepo], error: str) -> None:
        self._repos = repos
        self.status_label.setText(error if error else f"{len(repos)} repositories")
        self._apply_filter(self.search_box.text())

    def _apply_filter(self, text: str) -> None:
        self.repo_list.clear()
        text = text.strip().lower()
        for repo in self._repos:
            if text and text not in repo.full_name.lower():
                continue
            label = repo.full_name + ("  (private)" if repo.private else "")
            item = QListWidgetItem(label)
            item.setData(1000, repo)
            self.repo_list.addItem(item)

    def _on_browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose destination folder", self.dest_edit.text())
        if path:
            self.dest_edit.setText(path)

    # ---- clone --------------------------------------------------------------------

    def _on_clone_clicked(self) -> None:
        items = self.repo_list.selectedItems()
        if not items:
            QMessageBox.warning(self, "Clone", "Select a repository first.")
            return
        repo: GitHubRepo = items[0].data(1000)
        parent_dir = Path(self.dest_edit.text())
        if not parent_dir.is_dir():
            QMessageBox.warning(self, "Clone", "Destination folder does not exist.")
            return
        dest = parent_dir / repo.full_name.split("/")[-1]
        if dest.exists():
            QMessageBox.warning(self, "Clone", f"'{dest}' already exists.")
            return

        self.clone_btn.setEnabled(False)
        self.cancel_clone_btn.setVisible(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.status_label.setText("Starting clone...")

        self._clone_worker, self._clone_thread = start_clone(repo.clone_url, str(dest), self._token)
        self._clone_worker.progress.connect(self._on_clone_progress)
        self._clone_worker.succeeded.connect(self._on_clone_succeeded)
        self._clone_worker.failed.connect(self._on_clone_failed)
        self._clone_worker.canceled.connect(self._on_clone_canceled)

    def _on_cancel_clone_clicked(self) -> None:
        if self._clone_worker:
            self._clone_worker.cancel()

    def _on_clone_progress(self, stage: str, percent: int) -> None:
        self.progress_bar.setValue(percent)
        self.status_label.setText(stage)

    def _reset_clone_ui(self) -> None:
        self.clone_btn.setEnabled(True)
        self.cancel_clone_btn.setVisible(False)
        self.progress_bar.setVisible(False)

    def _on_clone_succeeded(self, dest: str) -> None:
        self._reset_clone_ui()
        self.status_label.setText("Clone complete")
        self.repo_cloned.emit(dest)
        self.accept()

    def _on_clone_failed(self, message: str, detail: str) -> None:
        self._reset_clone_ui()
        self.status_label.setText("Clone failed")
        QMessageBox.critical(self, "Clone failed", f"{message}\n\n{detail}" if detail else message)

    def _on_clone_canceled(self) -> None:
        self._reset_clone_ui()
        self.status_label.setText("Clone canceled")
