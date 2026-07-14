from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gitgood import config
from gitgood.auth import github_auth
from gitgood.git_ops.graph import CommitGraph, build_commit_graph
from gitgood.git_ops.repo_state import OpKind, get_repo_state
from gitgood.git_ops.repository import ConflictInfo, StashEntry, StatusResult
from gitgood.ui.dialogs.branch_dialog import BranchDialog
from gitgood.ui.widgets.changes_panel import ChangesPanel
from gitgood.ui.widgets.commit_box import CommitBox
from gitgood.ui.widgets.commit_details_panel import CommitDetailsPanel
from gitgood.ui.widgets.commit_graph_view import CommitGraphView, GraphColumnHeader
from gitgood.ui.widgets.conflict_resolver import ConflictResolverDialog
from gitgood.ui.widgets.diff_view import SideBySideDiffView
from gitgood.ui.widgets.stash_panel import StashPanel
from gitgood.workers.git_worker import RepoWorker, make_repo_worker, wrap_progress


def _bundle(repo, source: str) -> dict:
    """Standard post-mutation payload: fresh status + graph, and -- if the
    operation left a merge/rebase in progress -- the conflict data needed to
    pop the shared ConflictResolverDialog."""
    result = {
        "kind": "bundle",
        "source": source,
        "status": repo.status(),
        "graph": build_commit_graph(repo.repo),
    }
    state = get_repo_state(repo.repo)
    if state.in_progress:
        result["conflict_state"] = state.kind.value
        result["conflicts"] = repo.conflicts()
    return result


class RepoTab(QWidget):
    """A single open repository's full view (graph, changes, diff, stash,
    commit box) plus its own worker thread -- one instance lives per tab in
    AppWindow's QTabWidget. Has no window chrome of its own: AppWindow owns
    the single persistent toolbar and dispatches actions to whichever
    RepoTab is currently active."""

    status_message = Signal(str)
    changes_count_changed = Signal(int)

    def __init__(self, repo_path: str):
        super().__init__()
        self.repo_path = repo_path
        self._conflict_dialog: ConflictResolverDialog | None = None
        self._selected_commit_sha: str | None = None

        self.worker: RepoWorker
        self.thread = None
        self.worker, self.thread = make_repo_worker(repo_path)
        self.worker.progress.connect(self._on_progress)
        self.worker.succeeded.connect(self._on_job_succeeded)
        self.worker.failed.connect(self._on_job_failed)

        root_layout = QVBoxLayout(self)

        main_splitter = QSplitter()

        left_container = QWidget()
        left_layout = QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        search_row = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Filter by message, author, or SHA...")
        self.search_box.textChanged.connect(self._on_search_changed)
        search_row.addWidget(self.search_box)
        left_layout.addLayout(search_row)
        self.graph_view = CommitGraphView()
        self.graph_view.commit_selected.connect(self._on_commit_selected)
        settings = config.load_settings()
        self.graph_view.set_show_author(settings.get("graph_show_author", True))
        self.graph_view.set_show_date(settings.get("graph_show_date", True))
        self.graph_header = GraphColumnHeader(self.graph_view)
        self.graph_header.author_action.toggled.connect(self._on_graph_show_author_toggled)
        self.graph_header.date_action.toggled.connect(self._on_graph_show_date_toggled)
        left_layout.addWidget(self.graph_header)
        left_layout.addWidget(self.graph_view)
        main_splitter.addWidget(left_container)

        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)

        right_splitter = QSplitter()
        right_splitter.setOrientation(Qt.Orientation.Vertical)

        self.changes_panel = ChangesPanel()
        self.changes_panel.stage_requested.connect(self._on_stage_requested)
        self.changes_panel.unstage_requested.connect(self._on_unstage_requested)
        self.changes_panel.discard_requested.connect(self._on_discard_requested)
        self.changes_panel.gitignore_requested.connect(self._on_gitignore_requested)
        self.changes_panel.file_selected.connect(self._on_file_selected)
        right_splitter.addWidget(self.changes_panel)

        self.side_tabs = QTabWidget()
        self.diff_view = SideBySideDiffView()
        self.side_tabs.addTab(self.diff_view, "Diff")
        self.commit_details_panel = CommitDetailsPanel()
        self.commit_details_panel.file_selected.connect(self._on_commit_file_selected)
        self.side_tabs.addTab(self.commit_details_panel, "Commit")
        self.stash_panel = StashPanel()
        self.stash_panel.save_requested.connect(self._on_stash_save_requested)
        self.stash_panel.apply_requested.connect(self._on_stash_apply_requested)
        self.stash_panel.pop_requested.connect(self._on_stash_pop_requested)
        self.stash_panel.drop_requested.connect(self._on_stash_drop_requested)
        self.side_tabs.addTab(self.stash_panel, "Stash")
        right_splitter.addWidget(self.side_tabs)

        right_layout.addWidget(right_splitter)

        self.commit_box = CommitBox()
        self.commit_box.commit_requested.connect(self._on_commit_requested)
        right_layout.addWidget(self.commit_box)

        main_splitter.addWidget(right_container)
        main_splitter.setStretchFactor(0, 2)
        main_splitter.setStretchFactor(1, 1)

        root_layout.addWidget(main_splitter)

        self.refresh_all()

    # ---- loading ------------------------------------------------------------------

    def refresh_all(self) -> None:
        self.reload_graph()
        self.reload_status()
        self.reload_stashes()

    def reload_graph(self) -> None:
        def job(repo, progress_cb):
            return build_commit_graph(repo.repo)

        self.worker.submit(job)

    def reload_status(self) -> None:
        def job(repo, progress_cb):
            return repo.status()

        self.worker.submit(job)

    def reload_stashes(self) -> None:
        def job(repo, progress_cb):
            return repo.stash_list()

        self.worker.submit(job)

    # ---- global-toolbar actions (called by AppWindow on the active tab) ---------------

    def fetch(self) -> None:
        self.status_message.emit("Fetching...")
        token = github_auth.get_token()

        def job(repo, progress_cb):
            repo.fetch(token=token, progress=wrap_progress(progress_cb))
            return _bundle(repo, "fetch")

        self.worker.submit(job)

    def pull(self) -> None:
        self.status_message.emit("Pulling...")
        token = github_auth.get_token()

        def job(repo, progress_cb):
            repo.pull(token=token, progress=wrap_progress(progress_cb))
            return _bundle(repo, "pull")

        self.worker.submit(job)

    def push(self) -> None:
        self.status_message.emit("Pushing...")
        token = github_auth.get_token()

        def job(repo, progress_cb):
            repo.push(token=token, progress=wrap_progress(progress_cb))
            return _bundle(repo, "push")

        self.worker.submit(job)

    def open_branches_dialog(self) -> None:
        def job(repo, progress_cb):
            return {"kind": "branch_list", "branches": repo.list_branches(), "current": repo.current_branch()}

        self.worker.submit(job)

    def _open_branch_dialog(self, branches, current, selection_only: bool, on_selected=None) -> None:
        dialog = BranchDialog(branches, current, selection_only=selection_only, parent=self)
        if selection_only:
            if dialog.exec() == BranchDialog.DialogCode.Accepted and dialog.selected_branch and on_selected:
                on_selected(dialog.selected_branch)
            return
        dialog.checkout_requested.connect(self._on_checkout_requested)
        dialog.create_requested.connect(self._on_create_branch_requested)
        dialog.rename_requested.connect(self._on_rename_branch_requested)
        dialog.delete_requested.connect(self._on_delete_branch_requested)
        dialog.exec()

    def _on_checkout_requested(self, name: str) -> None:
        def job(repo, progress_cb):
            repo.checkout_branch(name)
            return _bundle(repo, "checkout")

        self.worker.submit(job)

    def _on_create_branch_requested(self, name: str, start_point: str) -> None:
        def job(repo, progress_cb):
            repo.create_branch(name, start_point or None)
            return _bundle(repo, "create-branch")

        self.worker.submit(job)

    def _on_rename_branch_requested(self, old: str, new: str) -> None:
        def job(repo, progress_cb):
            repo.rename_branch(old, new)
            return _bundle(repo, "rename-branch")

        self.worker.submit(job)

    def _on_delete_branch_requested(self, name: str) -> None:
        def job(repo, progress_cb):
            repo.delete_branch(name, force=False)
            return _bundle(repo, "delete-branch")

        self.worker.submit(job)

    def open_merge_dialog(self) -> None:
        def job(repo, progress_cb):
            return {
                "kind": "branch_list",
                "branches": repo.list_branches(),
                "current": repo.current_branch(),
                "purpose": "merge",
            }

        self.worker.submit(job)

    def open_rebase_dialog(self) -> None:
        def job(repo, progress_cb):
            return {
                "kind": "branch_list",
                "branches": repo.list_branches(),
                "current": repo.current_branch(),
                "purpose": "rebase",
            }

        self.worker.submit(job)

    def _do_merge(self, branch_name: str) -> None:
        def job(repo, progress_cb):
            repo.merge(branch_name)
            return _bundle(repo, "merge")

        self.worker.submit(job)

    def _do_rebase(self, branch_name: str) -> None:
        def job(repo, progress_cb):
            repo.rebase(upstream=branch_name, action="start")
            return _bundle(repo, "rebase")

        self.worker.submit(job)

    def _on_search_changed(self, text: str) -> None:
        matches = self.graph_view.set_filter(text)
        if matches:
            self.graph_view.scroll_to_sha(matches[0])

    def _on_commit_selected(self, sha: str) -> None:
        self.status_message.emit(f"Selected {sha[:7]}")
        self._selected_commit_sha = sha
        node = self.graph_view.get_node(sha)
        summary = node.summary if node else ""

        def job(repo, progress_cb):
            return {"kind": "commit_files", "sha": sha, "summary": summary, "files": repo.commit_changed_files(sha)}

        self.worker.submit(job)
        self.side_tabs.setCurrentWidget(self.commit_details_panel)

    def _on_commit_file_selected(self, path: str) -> None:
        sha = self._selected_commit_sha
        if not sha:
            return

        def job(repo, progress_cb):
            old, new = repo.commit_file_diff_sources(sha, path)
            return {"kind": "commit_diff", "old": old, "new": new}

        self.worker.submit(job)

    def _on_graph_show_author_toggled(self, checked: bool) -> None:
        settings = config.load_settings()
        settings["graph_show_author"] = checked
        config.save_settings(settings)

    def _on_graph_show_date_toggled(self, checked: bool) -> None:
        settings = config.load_settings()
        settings["graph_show_date"] = checked
        config.save_settings(settings)

    # ---- changes panel actions --------------------------------------------------------

    def _on_stage_requested(self, paths: list[str]) -> None:
        def job(repo, progress_cb):
            repo.stage(paths)
            return repo.status()

        self.worker.submit(job)

    def _on_unstage_requested(self, paths: list[str]) -> None:
        def job(repo, progress_cb):
            repo.unstage(paths)
            return repo.status()

        self.worker.submit(job)

    def _on_discard_requested(self, paths: list[str]) -> None:
        def job(repo, progress_cb):
            repo.discard(paths)
            return repo.status()

        self.worker.submit(job)

    def _on_gitignore_requested(self, paths: list[str]) -> None:
        def job(repo, progress_cb):
            gitignore = Path(repo.path) / ".gitignore"
            existing = gitignore.read_text() if gitignore.exists() else ""
            lines = existing.splitlines()
            for path in paths:
                if path not in lines:
                    lines.append(path)
            gitignore.write_text("\n".join(lines) + "\n")
            return repo.status()

        self.worker.submit(job)

    def _on_file_selected(self, path: str, is_staged: bool) -> None:
        def job(repo, progress_cb):
            old, new = repo.side_by_side_diff_sources(path, is_staged)
            return {"kind": "diff", "old": old, "new": new}

        self.worker.submit(job)

    def _on_commit_requested(self, message: str, amend: bool) -> None:
        def job(repo, progress_cb):
            repo.commit(message, amend=amend)
            return _bundle(repo, "commit")

        self.worker.submit(job)

    # ---- stash actions --------------------------------------------------------------------

    def _on_stash_save_requested(self, message: str, include_untracked: bool) -> None:
        def job(repo, progress_cb):
            repo.stash_save(message or None, include_untracked=include_untracked)
            return {"kind": "stash_bundle", "status": repo.status(), "stashes": repo.stash_list()}

        self.worker.submit(job)

    def _on_stash_apply_requested(self, index: int) -> None:
        def job(repo, progress_cb):
            repo.stash_apply(index)
            result = _bundle(repo, "stash-apply")
            result["stashes"] = repo.stash_list()
            return result

        self.worker.submit(job)

    def _on_stash_pop_requested(self, index: int) -> None:
        def job(repo, progress_cb):
            repo.stash_pop(index)
            result = _bundle(repo, "stash-pop")
            result["stashes"] = repo.stash_list()
            return result

        self.worker.submit(job)

    def _on_stash_drop_requested(self, index: int) -> None:
        def job(repo, progress_cb):
            repo.stash_drop(index)
            return {"kind": "stash_bundle", "status": repo.status(), "stashes": repo.stash_list()}

        self.worker.submit(job)

    # ---- conflict resolution ------------------------------------------------------------

    def _open_conflict_dialog(self, conflicts: list[ConflictInfo], operation_label: str) -> None:
        if self._conflict_dialog is not None:
            self._conflict_dialog.close()
        dialog = ConflictResolverDialog(conflicts, operation_label, parent=self)
        dialog.resolve_file_requested.connect(self._on_resolve_file_requested)
        dialog.conclude_requested.connect(self._on_conclude_requested)
        self._conflict_dialog = dialog
        dialog.exec()

    def _on_resolve_file_requested(self, path: str, content: str) -> None:
        def job(repo, progress_cb):
            repo.resolve_conflict(path, content)
            return "resolved"

        self.worker.submit(job)

    def _on_conclude_requested(self) -> None:
        def job(repo, progress_cb):
            state = get_repo_state(repo.repo)
            if state.kind is OpKind.MERGE:
                repo.conclude_merge()
            elif state.kind is OpKind.REBASE:
                repo.rebase(action="continue")
            return _bundle(repo, "conclude")

        self.worker.submit(job)

    # ---- signal handlers ---------------------------------------------------------------

    def _on_progress(self, job_id: str, stage: str, percent: int) -> None:
        self.status_message.emit(f"{stage}: {percent}%")

    def _apply_status(self, status: StatusResult) -> None:
        self.changes_panel.set_status(status)
        self.commit_box.set_has_staged_changes(bool(status.staged))
        total = len(status.staged) + len(status.unstaged) + len(status.untracked) + len(status.conflicted)
        self.changes_count_changed.emit(total)

    def _on_job_succeeded(self, job_id: str, result) -> None:
        if isinstance(result, CommitGraph):
            self.graph_view.set_graph(result)
            self.status_message.emit(f"Loaded {len(result.nodes)} commits")
        elif isinstance(result, StatusResult):
            self._apply_status(result)
            self.status_message.emit("Ready")
        elif isinstance(result, list) and (not result or isinstance(result[0], StashEntry)):
            self.stash_panel.set_stashes(result)
        elif isinstance(result, dict) and result.get("kind") == "diff":
            self.diff_view.set_diff(result["old"], result["new"])
        elif isinstance(result, dict) and result.get("kind") == "commit_files":
            self.commit_details_panel.set_commit(result["sha"], result["summary"], result["files"])
        elif isinstance(result, dict) and result.get("kind") == "commit_diff":
            self.commit_details_panel.diff_view.set_diff(result["old"], result["new"])
        elif isinstance(result, dict) and result.get("kind") == "stash_bundle":
            self._apply_status(result["status"])
            self.stash_panel.set_stashes(result["stashes"])
            self.status_message.emit("Ready")
        elif isinstance(result, dict) and result.get("kind") == "branch_list":
            purpose = result.get("purpose")
            if purpose == "merge":
                self._open_branch_dialog(result["branches"], result["current"], True, self._do_merge)
            elif purpose == "rebase":
                self._open_branch_dialog(result["branches"], result["current"], True, self._do_rebase)
            else:
                self._open_branch_dialog(result["branches"], result["current"], False)
        elif isinstance(result, dict) and result.get("kind") == "bundle":
            self.graph_view.set_graph(result["graph"])
            self._apply_status(result["status"])
            if result.get("source") == "commit":
                self.commit_box.clear()
            if "stashes" in result:
                self.stash_panel.set_stashes(result["stashes"])
            if result.get("conflicts"):
                self._open_conflict_dialog(result["conflicts"], result["conflict_state"])
                self.status_message.emit(f"{result['source'].capitalize()}: conflicts to resolve")
            else:
                if self._conflict_dialog is not None:
                    self._conflict_dialog.close()
                    self._conflict_dialog = None
                self.status_message.emit(f"{result['source'].capitalize()} complete")
        elif result == "resolved":
            pass
        else:
            self.status_message.emit("Done")

    def _on_job_failed(self, job_id: str, message: str, detail: str) -> None:
        self.status_message.emit(f"Failed: {message}")
        QMessageBox.warning(self, "GitGood", f"{message}\n\n{detail}" if detail else message)

    def shutdown(self) -> None:
        """Called explicitly by AppWindow when this tab is closed -- a QWidget
        embedded in a QTabWidget never receives a real closeEvent."""
        self.worker.stop()
        self.thread.quit()
        self.thread.wait(2000)
