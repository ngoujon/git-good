"""Detect in-progress git operations (merge/rebase/cherry-pick/revert).

GitPython has no API for this -- it has to be read directly off the
.git directory, since these are just marker files git itself drops there.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import git


class OpKind(Enum):
    NONE = "none"
    MERGE = "merge"
    REBASE = "rebase"
    CHERRY_PICK = "cherry-pick"
    REVERT = "revert"


@dataclass
class RebaseProgress:
    current_step: int
    total_steps: int
    head_name: str | None


@dataclass
class RepoState:
    kind: OpKind
    rebase_progress: RebaseProgress | None = None

    @property
    def in_progress(self) -> bool:
        return self.kind is not OpKind.NONE


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _rebase_progress(rebase_dir: Path) -> RebaseProgress:
    current = _read_int(rebase_dir / "msgnum") or 0
    total = _read_int(rebase_dir / "end") or 0
    head_name_path = rebase_dir / "head-name"
    head_name = None
    if head_name_path.exists():
        head_name = head_name_path.read_text().strip().removeprefix("refs/heads/")
    return RebaseProgress(current_step=current, total_steps=total, head_name=head_name)


def get_repo_state(repo: git.Repo) -> RepoState:
    """Inspect the .git directory for markers left by an in-progress operation."""
    git_dir = Path(repo.git_dir)

    rebase_merge = git_dir / "rebase-merge"
    rebase_apply = git_dir / "rebase-apply"
    if rebase_merge.is_dir():
        return RepoState(OpKind.REBASE, _rebase_progress(rebase_merge))
    if rebase_apply.is_dir():
        return RepoState(OpKind.REBASE, _rebase_progress(rebase_apply))

    if (git_dir / "MERGE_HEAD").exists():
        return RepoState(OpKind.MERGE)

    if (git_dir / "CHERRY_PICK_HEAD").exists():
        return RepoState(OpKind.CHERRY_PICK)

    if (git_dir / "REVERT_HEAD").exists():
        return RepoState(OpKind.REVERT)

    return RepoState(OpKind.NONE)
