"""Commit graph lane layout.

Split into two parts on purpose:

- `assign_lanes()` is pure Python (no GitPython, no Qt) operating on plain
  (sha, parents) tuples, so the lane-assignment algorithm -- the trickiest and
  most important piece of this app -- is fully unit-testable without a real
  repo or a display.
- `build_commit_graph()` is the thin GitPython adapter that feeds it real data.

Algorithm (newest-first walk, commits appear before their parents):
  1. Lanes are seeded up front from a deterministic, de-duplicated tip list
     (current branch first, then local branches, remotes, tags -- see
     `deterministic_tips()`) so the same branch always lands in the same
     column across refreshes.
  2. For each commit: if one or more active lanes already expect this SHA, it
     takes the lowest such lane index and the others are freed (this is how
     converging branches / merge targets get drawn).
  3. A commit with no parents (root/orphan branch) frees its lane instead of
     continuing it.
  4. Each extra parent of a merge commit reuses an active lane already
     expecting that parent SHA if one exists, instead of always allocating a
     new column (avoids column bloat on octopus / reconverging merges).
  5. Edges are resolved in a second pass, once every commit's lane is known;
     a parent SHA outside the loaded commit set (shallow/truncated history)
     resolves to `to_lane=None` so the renderer can draw a stub.

Important: never build the tip list from `git log --all` -- that means
"every ref under refs/", which includes `refs/stash` and would inject the
stash's synthetic WIP/index commits into the visible graph.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import git

PALETTE_SIZE = 8  # matches the validated categorical palette in ui/theme.py


@dataclass(frozen=True)
class CommitData:
    sha: str
    parents: tuple[str, ...]


@dataclass
class LaneAssignment:
    lane: int
    color_index: int


@dataclass
class GraphEdge:
    parent_sha: str
    from_lane: int
    to_lane: int | None = None  # resolved in a second pass; None = truncated history


@dataclass
class GraphLayout:
    lanes: dict[str, LaneAssignment] = field(default_factory=dict)
    edges: dict[str, list[GraphEdge]] = field(default_factory=dict)
    lane_count: int = 0


def assign_lanes(commits: list[CommitData], tips: list[str]) -> GraphLayout:
    """`commits` must be newest-first with every commit appearing before its
    parents (i.e. topological order). `tips` is the deduplicated, ordered
    list of ref-tip SHAs used only to seed initial lane/column order."""
    commit_shas = {c.sha for c in commits}
    active_lanes: list[str | None] = []

    def alloc_lane(expected_sha: str) -> int:
        for i, slot in enumerate(active_lanes):
            if slot is None:
                active_lanes[i] = expected_sha
                return i
        active_lanes.append(expected_sha)
        return len(active_lanes) - 1

    seen_tips: set[str] = set()
    for sha in tips:
        if sha in seen_tips or sha not in commit_shas:
            continue
        seen_tips.add(sha)
        alloc_lane(sha)

    lanes: dict[str, LaneAssignment] = {}
    edges: dict[str, list[GraphEdge]] = {}

    for commit in commits:
        matches = [i for i, slot in enumerate(active_lanes) if slot == commit.sha]
        if matches:
            lane = min(matches)
            for i in matches:
                if i != lane:
                    active_lanes[i] = None
        else:
            lane = alloc_lane(commit.sha)

        lanes[commit.sha] = LaneAssignment(lane=lane, color_index=lane % PALETTE_SIZE)

        commit_edges: list[GraphEdge] = []
        if not commit.parents:
            active_lanes[lane] = None
        else:
            first_parent, *merge_parents = commit.parents
            active_lanes[lane] = first_parent
            commit_edges.append(GraphEdge(parent_sha=first_parent, from_lane=lane))

            for parent_sha in merge_parents:
                already_expected = any(slot == parent_sha for slot in active_lanes)
                if not already_expected:
                    alloc_lane(parent_sha)
                commit_edges.append(GraphEdge(parent_sha=parent_sha, from_lane=lane))

        edges[commit.sha] = commit_edges

    for commit_edges in edges.values():
        for edge in commit_edges:
            parent_assignment = lanes.get(edge.parent_sha)
            edge.to_lane = parent_assignment.lane if parent_assignment else None

    return GraphLayout(lanes=lanes, edges=edges, lane_count=len(active_lanes))


# ---- GitPython adapter ---------------------------------------------------------


@dataclass
class GraphNode:
    sha: str
    short_sha: str
    summary: str
    author_name: str
    authored_date: int
    parents: tuple[str, ...]
    lane: int
    color_index: int
    refs: tuple[str, ...] = ()


@dataclass
class CommitGraph:
    nodes: list[GraphNode] = field(default_factory=list)
    lane_count: int = 0
    edges: dict[str, list[GraphEdge]] = field(default_factory=dict)


def deterministic_tips(repo: git.Repo) -> list[str]:
    """Ref tips in a fixed, stable order: current branch, other local
    branches (sorted), remote-tracking branches (sorted), tags -- never
    `refs/stash`, which `git log --all` would otherwise include."""
    tips: list[str] = []

    current_name = None if repo.head.is_detached else repo.active_branch.name
    if not repo.head.is_detached and repo.head.is_valid():
        tips.append(repo.active_branch.commit.hexsha)

    local_heads = sorted(repo.heads, key=lambda h: h.name)
    for head in local_heads:
        if head.name != current_name:
            tips.append(head.commit.hexsha)

    remote_refs = []
    for remote in repo.remotes:
        for ref in remote.refs:
            if not ref.name.endswith("/HEAD"):
                remote_refs.append(ref)
    for ref in sorted(remote_refs, key=lambda r: r.name):
        tips.append(ref.commit.hexsha)

    for tag in sorted(repo.tags, key=lambda t: t.name):
        tips.append(tag.commit.hexsha)

    return tips


def _ref_names_by_sha(repo: git.Repo) -> dict[str, list[str]]:
    by_sha: dict[str, list[str]] = {}
    for head in repo.heads:
        by_sha.setdefault(head.commit.hexsha, []).append(head.name)
    for remote in repo.remotes:
        for ref in remote.refs:
            if not ref.name.endswith("/HEAD"):
                by_sha.setdefault(ref.commit.hexsha, []).append(ref.name)
    for tag in repo.tags:
        by_sha.setdefault(tag.commit.hexsha, []).append(f"tags/{tag.name}")
    return by_sha


def build_commit_graph(repo: git.Repo, max_count: int | None = None) -> CommitGraph:
    tips = deterministic_tips(repo)
    if not tips:
        return CommitGraph()

    seen: set[str] = set()
    ordered_tips: list[str] = []
    for sha in tips:
        if sha not in seen:
            seen.add(sha)
            ordered_tips.append(sha)

    # NOTE: `rev` must be a list, not a joined string -- GitPython passes it
    # straight through as a single argv token, so a space-joined string
    # becomes one bad revision instead of multiple revs to `git rev-list`.
    raw_commits = list(
        repo.iter_commits(rev=ordered_tips, max_count=max_count, topo_order=True)
    )
    commit_data = [CommitData(sha=c.hexsha, parents=tuple(p.hexsha for p in c.parents)) for c in raw_commits]
    layout = assign_lanes(commit_data, ordered_tips)
    ref_names = _ref_names_by_sha(repo)

    nodes = [
        GraphNode(
            sha=c.hexsha,
            short_sha=c.hexsha[:7],
            summary=c.summary,
            author_name=c.author.name or "",
            authored_date=c.authored_date,
            parents=tuple(p.hexsha for p in c.parents),
            lane=layout.lanes[c.hexsha].lane,
            color_index=layout.lanes[c.hexsha].color_index,
            refs=tuple(ref_names.get(c.hexsha, ())),
        )
        for c in raw_commits
    ]

    return CommitGraph(nodes=nodes, lane_count=layout.lane_count, edges=layout.edges)
