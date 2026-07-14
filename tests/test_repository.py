import sys
from pathlib import Path

import git
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gitgood.git_ops.repo_state import OpKind, get_repo_state
from gitgood.git_ops.repository import Repository


@pytest.fixture
def scratch_repo(tmp_path):
    repo = git.Repo.init(tmp_path)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test User")
        cw.set_value("user", "email", "test@example.com")
    (tmp_path / "a.txt").write_text("hello\n")
    repo.index.add(["a.txt"])
    repo.index.commit("initial commit")
    return tmp_path


def test_status_clean_repo(scratch_repo):
    r = Repository(scratch_repo)
    status = r.status()
    assert status.is_clean


def test_stage_unstage_commit(scratch_repo):
    r = Repository(scratch_repo)
    (Path(scratch_repo) / "a.txt").write_text("changed\n")
    (Path(scratch_repo) / "b.txt").write_text("new\n")

    status = r.status()
    assert any(c.path == "a.txt" for c in status.unstaged)
    assert "b.txt" in status.untracked

    r.stage(["a.txt", "b.txt"])
    status = r.status()
    assert {c.path for c in status.staged} == {"a.txt", "b.txt"}
    assert not status.unstaged
    assert not status.untracked

    r.unstage(["b.txt"])
    status = r.status()
    assert {c.path for c in status.staged} == {"a.txt"}
    assert "b.txt" in status.untracked

    r.stage(["b.txt"])
    sha = r.commit("second commit")
    assert r.repo.head.commit.hexsha == sha
    assert r.status().is_clean


def test_discard_changes(scratch_repo):
    r = Repository(scratch_repo)
    path = Path(scratch_repo) / "a.txt"
    path.write_text("dirty\n")
    (Path(scratch_repo) / "untracked.txt").write_text("x\n")

    r.discard(["a.txt", "untracked.txt"])

    assert path.read_text() == "hello\n"
    assert not (Path(scratch_repo) / "untracked.txt").exists()


def test_branch_create_checkout_delete(scratch_repo):
    r = Repository(scratch_repo)
    assert r.current_branch() in ("main", "master")

    r.create_branch("feature")
    r.checkout_branch("feature")
    assert r.current_branch() == "feature"

    names = {b.name for b in r.list_branches() if not b.is_remote}
    assert "feature" in names

    r.checkout_branch(r.repo.heads[0].name if r.repo.heads[0].name != "feature" else r.repo.heads[1].name)
    r.delete_branch("feature")
    names = {b.name for b in r.list_branches() if not b.is_remote}
    assert "feature" not in names


def test_merge_conflict_and_resolve(scratch_repo):
    r = Repository(scratch_repo)
    base_branch = r.current_branch()

    r.create_branch("feature")
    r.checkout_branch("feature")
    (Path(scratch_repo) / "a.txt").write_text("feature version\n")
    r.stage(["a.txt"])
    r.commit("feature change")

    r.checkout_branch(base_branch)
    (Path(scratch_repo) / "a.txt").write_text("main version\n")
    r.stage(["a.txt"])
    r.commit("main change")

    r.merge("feature")

    state = get_repo_state(r.repo)
    assert state.kind is OpKind.MERGE

    conflicts = r.conflicts()
    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.path == "a.txt"
    assert conflict.ours_text == "main version\n"
    assert conflict.theirs_text == "feature version\n"

    r.resolve_conflict("a.txt", "resolved version\n")
    r.commit("merge commit")

    state = get_repo_state(r.repo)
    assert state.kind is OpKind.NONE
    assert r.status().is_clean


def test_merge_conflict_conclude_with_default_message(scratch_repo):
    r = Repository(scratch_repo)
    base_branch = r.current_branch()

    r.create_branch("feature")
    r.checkout_branch("feature")
    (Path(scratch_repo) / "a.txt").write_text("feature version\n")
    r.stage(["a.txt"])
    r.commit("feature change")

    r.checkout_branch(base_branch)
    (Path(scratch_repo) / "a.txt").write_text("main version\n")
    r.stage(["a.txt"])
    r.commit("main change")

    r.merge("feature")
    r.resolve_conflict("a.txt", "resolved version\n")
    r.conclude_merge()

    state = get_repo_state(r.repo)
    assert state.kind is OpKind.NONE
    assert r.status().is_clean
    assert "merge" in r.repo.head.commit.message.lower()


def test_stash_roundtrip(scratch_repo):
    r = Repository(scratch_repo)
    (Path(scratch_repo) / "a.txt").write_text("wip\n")

    r.stash_save(message="wip work")
    assert r.status().is_clean
    stashes = r.stash_list()
    assert len(stashes) == 1
    assert "wip work" in stashes[0].message

    r.stash_pop(0)
    assert not r.status().is_clean
    assert (Path(scratch_repo) / "a.txt").read_text() == "wip\n"
    assert r.stash_list() == []


def test_repo_state_none_by_default(scratch_repo):
    r = Repository(scratch_repo)
    state = get_repo_state(r.repo)
    assert state.kind is OpKind.NONE
    assert not state.in_progress


def test_side_by_side_diff_sources_unstaged(scratch_repo):
    r = Repository(scratch_repo)
    (Path(scratch_repo) / "a.txt").write_text("changed\n")

    old, new = r.side_by_side_diff_sources("a.txt", staged=False)
    assert old == "hello"  # GitPython strips the trailing newline from `git show` output
    assert new == "changed\n"


def test_side_by_side_diff_sources_staged(scratch_repo):
    r = Repository(scratch_repo)
    (Path(scratch_repo) / "a.txt").write_text("staged change\n")
    r.stage(["a.txt"])

    old, new = r.side_by_side_diff_sources("a.txt", staged=True)
    assert old == "hello"
    assert new == "staged change"


def test_side_by_side_diff_sources_untracked_file(scratch_repo):
    r = Repository(scratch_repo)
    (Path(scratch_repo) / "new.txt").write_text("brand new\n")

    old, new = r.side_by_side_diff_sources("new.txt", staged=False)
    assert old == ""
    assert new == "brand new\n"


def test_commit_changed_files_root_commit(scratch_repo):
    r = Repository(scratch_repo)
    sha = r.repo.head.commit.hexsha

    files = r.commit_changed_files(sha)
    assert {c.path for c in files} == {"a.txt"}


def test_commit_changed_files_and_diff_sources_second_commit(scratch_repo):
    r = Repository(scratch_repo)
    (Path(scratch_repo) / "a.txt").write_text("changed\n")
    (Path(scratch_repo) / "b.txt").write_text("new\n")
    r.stage(["a.txt", "b.txt"])
    sha = r.commit("second commit")

    files = r.commit_changed_files(sha)
    assert {c.path for c in files} == {"a.txt", "b.txt"}

    old, new = r.commit_file_diff_sources(sha, "a.txt")
    assert old == "hello"
    assert new == "changed"

    old, new = r.commit_file_diff_sources(sha, "b.txt")
    assert old == ""
    assert new == "new"
