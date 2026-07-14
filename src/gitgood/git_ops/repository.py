"""GitPython-backed wrapper around a single working tree.

All results are returned as plain dataclasses (never raw GitPython objects)
so they can safely cross the thread boundary from a RepoWorker back to the UI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import git
from git.exc import GitCommandError


class GitOpError(Exception):
    """Raised for any failed git operation, wrapping the underlying stderr."""

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.detail = detail


@dataclass
class ChangeEntry:
    path: str
    change_type: str  # 'A' added, 'M' modified, 'D' deleted, 'R' renamed, '?' untracked


@dataclass
class StatusResult:
    staged: list[ChangeEntry] = field(default_factory=list)
    unstaged: list[ChangeEntry] = field(default_factory=list)
    untracked: list[str] = field(default_factory=list)
    conflicted: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not (self.staged or self.unstaged or self.untracked or self.conflicted)


@dataclass
class BranchInfo:
    name: str
    is_current: bool
    is_remote: bool
    upstream: str | None
    commit_sha: str


@dataclass
class StashEntry:
    index: int
    message: str
    sha: str


@dataclass
class ConflictInfo:
    path: str
    ancestor_text: str | None
    ours_text: str | None
    theirs_text: str | None


def _auth_kwarg(token: str | None) -> dict:
    """A one-off `-c http.extraHeader=...` override -- never written to .git/config."""
    if not token:
        return {}
    return {"c": f"http.extraHeader=Authorization: Bearer {token}"}


def _blob_text(blob: git.Blob | None) -> str | None:
    if blob is None:
        return None
    try:
        return blob.data_stream.read().decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return None


def _show_at(repo: git.Repo, ref: str, path: str) -> str:
    """`git show <ref>:<path>`, or "" if the file didn't exist at that ref
    (e.g. it was added later, or deleted at that point in history)."""
    try:
        return repo.git.show(f"{ref}:{path}")
    except GitCommandError:
        return ""


class Repository:
    def __init__(self, path: str | Path):
        self.repo = git.Repo(path)
        # Never let a git subprocess block waiting on an interactive editor/prompt.
        self.repo.git.update_environment(
            GIT_EDITOR="true",
            GIT_SEQUENCE_EDITOR="true",
            GIT_TERMINAL_PROMPT="0",
        )

    @property
    def path(self) -> str:
        return self.repo.working_dir

    # ---- status / staging -------------------------------------------------

    def status(self) -> StatusResult:
        result = StatusResult()

        if self.repo.head.is_valid():
            diff_staged = self.repo.index.diff(self.repo.head.commit)
            for d in diff_staged:
                result.staged.append(ChangeEntry(d.a_path or d.b_path, d.change_type or "M"))
        else:
            # No commits yet: everything in the index is a new "staged" add.
            for path in self.repo.index.entries:
                result.staged.append(ChangeEntry(path[0], "A"))

        diff_unstaged = self.repo.index.diff(None)
        for d in diff_unstaged:
            result.unstaged.append(ChangeEntry(d.a_path or d.b_path, d.change_type or "M"))

        result.untracked = list(self.repo.untracked_files)

        unmerged = self.repo.index.unmerged_blobs()
        result.conflicted = sorted(unmerged.keys())

        return result

    def stage(self, paths: list[str]) -> None:
        self.repo.index.add(paths)

    def unstage(self, paths: list[str]) -> None:
        if self.repo.head.is_valid():
            self.repo.index.reset(self.repo.head.commit, paths=paths)
        else:
            self.repo.index.remove(paths, cached=True)

    def discard(self, paths: list[str]) -> None:
        """Revert tracked files to HEAD and delete untracked ones."""
        untracked = set(self.repo.untracked_files)
        tracked = [p for p in paths if p not in untracked]
        if tracked and self.repo.head.is_valid():
            self.repo.git.checkout("--", *tracked)
        for p in paths:
            if p in untracked:
                full = Path(self.repo.working_dir) / p
                full.unlink(missing_ok=True)

    def commit(self, message: str, amend: bool = False) -> str:
        # Always shell out to `git commit` (rather than IndexFile.commit) so that
        # merge/rebase/cherry-pick state markers (MERGE_HEAD, etc.) get cleaned up
        # the way real git does after a conflict-resolution commit.
        args = ["--amend", "-m", message] if amend else ["-m", message]
        self.repo.git.commit(*args)
        return self.repo.head.commit.hexsha

    # ---- branches -----------------------------------------------------------

    def current_branch(self) -> str | None:
        return None if self.repo.head.is_detached else self.repo.active_branch.name

    def list_branches(self) -> list[BranchInfo]:
        branches: list[BranchInfo] = []
        current = None if self.repo.head.is_detached else self.repo.active_branch
        for head in self.repo.heads:
            upstream = None
            try:
                if head.tracking_branch():
                    upstream = head.tracking_branch().name
            except (TypeError, ValueError):
                pass
            branches.append(
                BranchInfo(
                    name=head.name,
                    is_current=(current is not None and head.name == current.name),
                    is_remote=False,
                    upstream=upstream,
                    commit_sha=head.commit.hexsha,
                )
            )
        for remote in self.repo.remotes:
            for ref in remote.refs:
                if ref.name.endswith("/HEAD"):
                    continue
                branches.append(
                    BranchInfo(
                        name=ref.name,
                        is_current=False,
                        is_remote=True,
                        upstream=None,
                        commit_sha=ref.commit.hexsha,
                    )
                )
        return branches

    def create_branch(self, name: str, start_point: str | None = None) -> None:
        if start_point:
            self.repo.create_head(name, start_point)
        else:
            self.repo.create_head(name)

    def checkout_branch(self, name: str) -> None:
        self.repo.git.checkout(name)

    def delete_branch(self, name: str, force: bool = False) -> None:
        self.repo.delete_head(name, force=force)

    def rename_branch(self, old: str, new: str) -> None:
        self.repo.heads[old].rename(new)

    # ---- tags -----------------------------------------------------------------

    def list_tags(self) -> list[str]:
        return [t.name for t in self.repo.tags]

    def create_tag(self, name: str, ref: str = "HEAD", message: str | None = None) -> None:
        self.repo.create_tag(name, ref=ref, message=message)

    def delete_tag(self, name: str) -> None:
        self.repo.delete_tag(name)

    # ---- remotes ----------------------------------------------------------------

    def fetch(self, remote_name: str = "origin", token: str | None = None, progress=None) -> None:
        remote = self.repo.remote(remote_name)
        try:
            remote.fetch(progress=progress, **_auth_kwarg(token))
        except GitCommandError as e:
            raise GitOpError(f"Fetch from '{remote_name}' failed", str(e)) from e

    def pull(
        self,
        remote_name: str = "origin",
        branch: str | None = None,
        token: str | None = None,
        progress=None,
    ) -> None:
        remote = self.repo.remote(remote_name)
        args = [branch] if branch else []
        try:
            remote.pull(*args, progress=progress, **_auth_kwarg(token))
        except GitCommandError as e:
            raise GitOpError(f"Pull from '{remote_name}' failed", str(e)) from e

    def push(
        self,
        remote_name: str = "origin",
        branch: str | None = None,
        token: str | None = None,
        set_upstream: bool = False,
        progress=None,
    ) -> None:
        remote = self.repo.remote(remote_name)
        branch = branch or self.current_branch()
        refspec = f"{branch}:{branch}" if branch else None
        kwargs = _auth_kwarg(token)
        if set_upstream:
            kwargs["set_upstream"] = True
        try:
            remote.push(refspec, progress=progress, **kwargs)
        except GitCommandError as e:
            raise GitOpError(f"Push to '{remote_name}' failed", str(e)) from e

    # ---- merge / rebase ------------------------------------------------------

    def merge(self, branch_name: str) -> None:
        try:
            self.repo.git.merge(branch_name)
        except GitCommandError as e:
            if not self.repo.index.unmerged_blobs():
                raise GitOpError(f"Merge of '{branch_name}' failed", str(e)) from e
            # Conflicts are expected here -- caller inspects repo_state()/conflicts().

    def conclude_merge(self) -> None:
        """Commit a conflict-resolved merge using git's own prepared MERGE_MSG
        (GIT_EDITOR=true means `git commit` with no -m just accepts it as-is)."""
        self.repo.git.commit()

    def rebase(self, upstream: str | None = None, action: str = "start") -> None:
        try:
            if action == "start":
                self.repo.git.rebase(upstream)
            elif action == "continue":
                self.repo.git.rebase("--continue")
            elif action == "abort":
                self.repo.git.rebase("--abort")
            elif action == "skip":
                self.repo.git.rebase("--skip")
            else:
                raise ValueError(f"Unknown rebase action: {action}")
        except GitCommandError as e:
            if not self.repo.index.unmerged_blobs():
                raise GitOpError(f"Rebase {action} failed", str(e)) from e

    # ---- stash ------------------------------------------------------------------

    def stash_list(self) -> list[StashEntry]:
        entries: list[StashEntry] = []
        try:
            output = self.repo.git.stash("list")
        except GitCommandError:
            return entries
        for i, line in enumerate(output.splitlines()):
            if not line.strip():
                continue
            sha = self.repo.git.rev_parse(f"stash@{{{i}}}")
            message = line.split(":", 2)[-1].strip()
            entries.append(StashEntry(index=i, message=message, sha=sha))
        return entries

    def stash_save(self, message: str | None = None, include_untracked: bool = False) -> None:
        args = []
        if include_untracked:
            args.append("--include-untracked")
        if message:
            args += ["-m", message]
        self.repo.git.stash("push", *args)

    def stash_apply(self, index: int = 0) -> None:
        self.repo.git.stash("apply", f"stash@{{{index}}}")

    def stash_pop(self, index: int = 0) -> None:
        self.repo.git.stash("pop", f"stash@{{{index}}}")

    def stash_drop(self, index: int = 0) -> None:
        self.repo.git.stash("drop", f"stash@{{{index}}}")

    # ---- diff / conflicts ------------------------------------------------------

    def diff_file(self, path: str, staged: bool = False) -> str:
        args = ["--no-color"]
        if staged:
            args.append("--cached")
        args += ["--", path]
        return self.repo.git.diff(*args)

    def file_content(self, path: str, source: str) -> str:
        """source: 'working' (on-disk), 'index' (staged), or 'head' (last commit)."""
        if source == "working":
            full = Path(self.repo.working_dir) / path
            try:
                return full.read_text(errors="replace")
            except (OSError, UnicodeDecodeError):
                return ""
        ref = "HEAD" if source == "head" else ""
        try:
            return self.repo.git.show(f"{ref}:{path}")
        except GitCommandError:
            return ""

    def side_by_side_diff_sources(self, path: str, staged: bool) -> tuple[str, str]:
        """Returns (old_text, new_text) for a full-file side-by-side diff."""
        if staged:
            return self.file_content(path, "head"), self.file_content(path, "index")
        old = self.file_content(path, "index")
        if not old and path not in {e[0] for e in self.repo.index.entries}:
            old = self.file_content(path, "head")
        return old, self.file_content(path, "working")

    def conflicts(self) -> list[ConflictInfo]:
        unmerged = self.repo.index.unmerged_blobs()
        result: list[ConflictInfo] = []
        for path, entries in unmerged.items():
            blobs = {stage: blob for stage, blob in entries}
            result.append(
                ConflictInfo(
                    path=path,
                    ancestor_text=_blob_text(blobs.get(1)),
                    ours_text=_blob_text(blobs.get(2)),
                    theirs_text=_blob_text(blobs.get(3)),
                )
            )
        return result

    def resolve_conflict(self, path: str, content: str) -> None:
        full_path = Path(self.repo.working_dir) / path
        full_path.write_text(content)
        # `git add` (not IndexFile.add) is what actually clears the stage 1/2/3
        # conflict entries -- GitPython's in-memory add() can leave them behind.
        self.repo.git.add(path)

    def commit_changed_files(self, sha: str) -> list[ChangeEntry]:
        """Files changed by a single historical commit, diffed against its
        first parent (or against the empty tree for a root commit)."""
        commit = self.repo.commit(sha)
        parent = commit.parents[0] if commit.parents else None
        diffs = parent.diff(commit) if parent is not None else commit.diff(git.NULL_TREE)
        return [ChangeEntry(d.a_path or d.b_path, d.change_type or "M") for d in diffs]

    def commit_file_diff_sources(self, sha: str, path: str) -> tuple[str, str]:
        """Returns (old_text, new_text) for one file as of a historical
        commit vs. its first parent -- the history counterpart of
        side_by_side_diff_sources()."""
        commit = self.repo.commit(sha)
        parent = commit.parents[0] if commit.parents else None
        new_text = _show_at(self.repo, sha, path)
        old_text = _show_at(self.repo, parent.hexsha, path) if parent is not None else ""
        return old_text, new_text

    def cherry_pick(self, sha: str) -> None:
        try:
            self.repo.git.cherry_pick(sha)
        except GitCommandError as e:
            if not self.repo.index.unmerged_blobs():
                raise GitOpError(f"Cherry-pick of '{sha}' failed", str(e)) from e
