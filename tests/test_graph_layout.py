import sys
from pathlib import Path

import git
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gitgood.git_ops.graph import (
    CommitData,
    assign_lanes,
    build_commit_graph,
    deterministic_tips,
)


def test_linear_history_single_lane():
    commits = [
        CommitData("c3", ("c2",)),
        CommitData("c2", ("c1",)),
        CommitData("c1", ()),
    ]
    layout = assign_lanes(commits, tips=["c3"])

    assert layout.lane_count == 1
    assert all(a.lane == 0 for a in layout.lanes.values())
    assert layout.edges["c3"][0].to_lane == 0
    assert layout.edges["c2"][0].to_lane == 0
    assert layout.edges["c1"] == []


def test_feature_branch_and_merge_diamond():
    # main: c1 -> c2 -> M(c2, f2)   feature: c2 -> f2
    commits = [
        CommitData("M", ("c2", "f2")),
        CommitData("f2", ("c2",)),
        CommitData("c2", ("c1",)),
        CommitData("c1", ()),
    ]
    layout = assign_lanes(commits, tips=["M", "f2"])

    assert layout.lanes["M"].lane == 0
    assert layout.lanes["f2"].lane == 1
    assert layout.lanes["c2"].lane == 0
    assert layout.lanes["c1"].lane == 0
    assert layout.lane_count == 2

    m_edges = {e.parent_sha: e for e in layout.edges["M"]}
    assert m_edges["c2"].to_lane == 0  # straight, first-parent line
    assert m_edges["f2"].to_lane == 1  # curved merge line

    f2_edge = layout.edges["f2"][0]
    assert f2_edge.parent_sha == "c2"
    assert f2_edge.from_lane == 1
    assert f2_edge.to_lane == 0  # feature line curves back into main's lane


def test_diverged_branches_no_merge_yet():
    # main: c1 -> c2      feature: c1 -> f1  (not yet merged)
    commits = [
        CommitData("c2", ("c1",)),
        CommitData("f1", ("c1",)),
        CommitData("c1", ()),
    ]
    layout = assign_lanes(commits, tips=["c2", "f1"])

    assert layout.lanes["c2"].lane == 0
    assert layout.lanes["f1"].lane == 1
    assert layout.lanes["c1"].lane == 0
    assert layout.lane_count == 2


def test_root_orphan_commits_free_their_lane_without_crashing():
    commits = [CommitData("a1", ())]
    layout = assign_lanes(commits, tips=["a1"])
    assert layout.lanes["a1"].lane == 0
    assert layout.edges["a1"] == []

    # Two unrelated orphan branches.
    commits = [CommitData("a1", ()), CommitData("b1", ())]
    layout = assign_lanes(commits, tips=["a1", "b1"])
    assert layout.lanes["a1"].lane == 0
    assert layout.lanes["b1"].lane == 1
    assert layout.lane_count == 2
    assert layout.edges["a1"] == []
    assert layout.edges["b1"] == []


def test_multiple_refs_on_the_same_commit_share_one_lane():
    commits = [CommitData("c1", ())]
    # main, a tag, and a release branch all point at the same commit.
    layout = assign_lanes(commits, tips=["c1", "c1", "c1"])
    assert layout.lane_count == 1
    assert layout.lanes["c1"].lane == 0


def test_reconverging_merge_reuses_lane_instead_of_bloating():
    # Two branch tips (M_a, M_b) each merge in a THIRD, already-deleted
    # branch's tip ("shared_tip") which is not itself a ref anymore -- only
    # reachable as a second merge-parent. Without lane reuse this would
    # allocate a spurious 4th column instead of sharing the 3rd.
    commits = [
        CommitData("M_a", ("c2a", "shared_tip")),
        CommitData("M_b", ("c2b", "shared_tip")),
        CommitData("shared_tip", ()),
        CommitData("c2a", ()),
        CommitData("c2b", ()),
    ]
    layout = assign_lanes(commits, tips=["M_a", "M_b"])

    assert layout.lane_count == 3  # not 4

    a_edge = next(e for e in layout.edges["M_a"] if e.parent_sha == "shared_tip")
    b_edge = next(e for e in layout.edges["M_b"] if e.parent_sha == "shared_tip")
    assert a_edge.to_lane == layout.lanes["shared_tip"].lane
    assert b_edge.to_lane == layout.lanes["shared_tip"].lane
    assert a_edge.to_lane == b_edge.to_lane


def test_octopus_merge_creates_one_edge_per_parent():
    commits = [
        CommitData("M", ("c1", "c2", "c3")),
        CommitData("c1", ()),
        CommitData("c2", ()),
        CommitData("c3", ()),
    ]
    layout = assign_lanes(commits, tips=["M"])

    assert layout.lanes["M"].lane == 0
    parent_shas = {e.parent_sha for e in layout.edges["M"]}
    assert parent_shas == {"c1", "c2", "c3"}
    assert layout.lane_count == 3


# ---- integration: real repo, stash exclusion ---------------------------------


@pytest.fixture
def scratch_repo(tmp_path):
    repo = git.Repo.init(tmp_path)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test User")
        cw.set_value("user", "email", "test@example.com")
    (tmp_path / "a.txt").write_text("hello\n")
    repo.index.add(["a.txt"])
    repo.index.commit("initial commit")
    return repo


def test_stash_is_never_included_in_tips_or_graph(scratch_repo):
    repo = scratch_repo
    (Path(repo.working_dir) / "a.txt").write_text("dirty\n")
    repo.git.stash("push", "-m", "wip")

    assert "refs/stash" in [r.path for r in repo.refs]  # sanity: stash ref exists

    tips = deterministic_tips(repo)
    stash_sha = repo.git.rev_parse("stash@{0}")
    assert stash_sha not in tips

    graph = build_commit_graph(repo)
    shas = {n.sha for n in graph.nodes}
    assert stash_sha not in shas
    assert len(graph.nodes) == 1  # only the initial commit, no WIP/index commits


def test_build_commit_graph_with_multiple_real_branches(scratch_repo):
    # Regression test: build_commit_graph must pass multiple tip SHAs to
    # GitPython as a list, not a space-joined string -- the joined string is
    # sent to `git rev-list` as a single (invalid) revision argument and
    # `iter_commits` raises, which only shows up with 2+ tips.
    repo = scratch_repo
    repo.create_head("feature")
    repo.heads.feature.checkout()
    (Path(repo.working_dir) / "a.txt").write_text("feature version\n")
    repo.index.add(["a.txt"])
    repo.index.commit("feature change")
    base_branch_name = next(h.name for h in repo.heads if h.name != "feature")
    repo.heads[base_branch_name].checkout()

    graph = build_commit_graph(repo)
    assert len(graph.nodes) == 2
    assert graph.lane_count == 2
