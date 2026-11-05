"""Type-specific semantic rules for group 2 (gantt, timeline, journey, gitGraph, kanban, mindmap).

tests/test_builders.py covers the generic bar (fixtures, parity, corpus, strictness). These
cases pin the rules that keep accepted IR renderable: a mindmap is one tree, gantt dates
cannot depend on themselves, gitGraph operations must be valid in order, and so on.
"""

from __future__ import annotations

import pytest

from skill_docs import load_render

render = load_render()


def error_path(doc: dict) -> str:
    with pytest.raises(render.IRError) as info:
        render.render(doc)
    return info.value.path


# --- mindmap ---------------------------------------------------------------------------------

def mindmap(nodes: list[tuple[str, str]], edges: list[tuple[str, str]], root: str = "r") -> dict:
    return {
        "diagram": "graph", "target": "mindmap", "root": root,
        "nodes": [{"id": i, "label": label} for i, label in nodes],
        "edges": [{"from": a, "to": b} for a, b in edges],
    }


@pytest.mark.parametrize(
    ("doc", "path"),
    [
        (mindmap([("r", "Root"), ("a", "A"), ("orphan", "O")], [("r", "a")]), "/nodes/2"),
        (mindmap([("r", "Root")], [("ghost", "r")]), "/edges/0/from"),
        (mindmap([("r", "Root"), ("b", "B")], [("r", "b"), ("b", "r")]), "/edges/1/to"),
        (mindmap([("r", "Root"), ("a", "A"), ("b", "B")], [("r", "a"), ("r", "b"), ("a", "b")]), "/edges/2/to"),
        (mindmap([("r", "Root"), ("a", "A"), ("b", "B")], [("r", "a"), ("a", "b"), ("b", "a")]), "/edges/2/to"),
        (mindmap([("r", "Root"), ("r", "Again")], []), "/nodes/1/id"),
        (mindmap([("r", "Root")], [], root="nope"), "/root"),
    ],
    ids=["unreachable", "undeclared-edge", "edge-to-root", "second-parent", "cycle", "duplicate-id", "bad-root"],
)
def test_mindmap_must_be_one_tree(doc: dict, path: str) -> None:
    assert error_path(doc) == path


def test_mindmap_markdown_needs_a_shape() -> None:
    doc = mindmap([("r", "Root"), ("a", "A")], [("r", "a")])
    doc["nodes"][1].update(kind="default", markdown=True)
    assert error_path(doc) == "/nodes/1/markdown"


def test_mindmap_shape_delimiters_in_labels_are_encoded() -> None:
    doc = mindmap([("r", "Root"), ("a", "Call foo(x) [y]")], [("r", "a")])
    doc["nodes"][1]["kind"] = "default"
    assert "Call foo#40;x#41; #91;y#93;" in render.render(doc)


# --- gantt -----------------------------------------------------------------------------------

def gantt(*bars: dict) -> dict:
    return {"diagram": "timeline", "target": "gantt", "dateFormat": "YYYY-MM-DD",
            "sections": [{"name": "S", "bars": list(bars)}]}


START = {"start": "2026-01-01"}


@pytest.mark.parametrize(
    ("doc", "path"),
    [
        (gantt({"label": "T", **START, "duration": "1d", "tags": ["urgent"]}), "/sections/0/bars/0/tags/0"),
        (gantt({"label": "T", **START, "duration": "1d", "tags": ["active", "done"]}), "/sections/0/bars/0/tags"),
        (gantt({"label": "T", **START, "duration": "1d", "tags": ["milestone", "done"]}), "/sections/0/bars/0/tags"),
        (gantt({"label": "T", **START, "duration": "1d", "tags": ["crit", "crit"]}), "/sections/0/bars/0/tags/1"),
        (gantt({"label": "T", "duration": "1d"}), "/sections/0/bars/0"),
        (gantt({"label": "T", **START, "duration": "1d"}, {"id": "b", "label": "U", "duration": "1d"}), "/sections/0/bars/1/id"),
        (gantt({"label": "T", **START}), "/sections/0/bars/0/duration"),
        (gantt({"label": "T", **START, "end": "2026-01-03", "duration": "1d"}), "/sections/0/bars/0/duration"),
        (gantt({"id": "a", "label": "T", "after": ["b"], "duration": "1d"}, {"id": "b", "label": "U", **START, "duration": "1d"}),
         "/sections/0/bars/0/after/0"),
        (gantt({"id": "a", "label": "T", **START, "until": "b"}, {"id": "b", "label": "U", "after": ["a"], "duration": "1d"}),
         "/sections/0/bars/1/after/0"),
        (gantt({"id": "a", "label": "T", **START, "until": "a"}), "/sections/0/bars/0/until"),
        (gantt({"label": "T", **START, "duration": "1d", "href": "https://example.com"}), "/sections/0/bars/0/href"),
        (gantt({"label": "title Oops", **START, "duration": "1d"}), "/sections/0/bars/0/label"),
        (gantt({"label": "2026-01-01 kickoff", **START, "duration": "1d"}), "/sections/0/bars/0/label"),
        (gantt({"label": "T", "start": "3d", "duration": "1d"}), "/sections/0/bars/0/start"),
        (gantt({"label": "T", "start": "after x", "duration": "1d"}), "/sections/0/bars/0/start"),
        (gantt({"label": "T", **START, "duration": "3"}), "/sections/0/bars/0/duration"),
    ],
    ids=["unknown-tag", "active-done", "milestone-done", "repeated-tag", "first-task-no-start",
         "id-without-start", "no-end", "two-ends", "after-later-task", "until-cycle", "until-self",
         "click-without-id", "keyword-label", "date-label", "start-is-length", "start-is-after",
         "length-without-unit"],
)
def test_gantt_rules(doc: dict, path: str) -> None:
    assert error_path(doc) == path


def test_gantt_colon_in_task_label_is_encoded() -> None:
    # A raw colon starts the task metadata (CLI 12.0.0 drops the rest of the title).
    source = render.render(gantt({"label": "Review: security", **START, "duration": "1d"}))
    assert "Review#58; security :2026-01-01, 1d" in source


def test_gantt_until_may_name_a_later_task() -> None:
    doc = gantt({"label": "T", **START, "duration": "1d"}, {"label": "Freeze", "until": "ship"},
                {"id": "ship", "label": "Ship", "start": "2026-02-01", "duration": "0d", "tags": ["milestone"]})
    assert "Freeze :until ship" in render.render(doc)


# --- timeline --------------------------------------------------------------------------------

def test_timeline_events_and_sections_are_exclusive() -> None:
    doc = {"diagram": "timeline", "target": "timeline",
           "events": [{"period": "1", "text": ["a"]}],
           "sections": [{"name": "S", "events": [{"period": "2", "text": ["b"]}]}]}
    assert error_path(doc) == "/events"


def test_timeline_colon_in_event_is_encoded_not_split() -> None:
    doc = {"diagram": "timeline", "target": "timeline", "events": [{"period": "2004", "text": ["A: B"]}]}
    assert "2004 : A#58; B" in render.render(doc)


@pytest.mark.parametrize("period", ["title Oops", "section Two"])
def test_timeline_keyword_period_is_rejected(period: str) -> None:
    doc = {"diagram": "timeline", "target": "timeline", "events": [{"period": period, "text": ["a"]}]}
    assert error_path(doc) == "/events/0/period"


# --- journey ---------------------------------------------------------------------------------

def journey(task: dict) -> dict:
    return {"diagram": "journey", "target": "journey", "sections": [{"name": "S", "tasks": [task]}]}


@pytest.mark.parametrize(
    ("task", "path"),
    [
        ({"name": "T", "score": 0, "actors": ["Me"]}, "/sections/0/tasks/0/score"),
        ({"name": "T", "score": 6, "actors": ["Me"]}, "/sections/0/tasks/0/score"),
        ({"name": "T", "score": 2.5, "actors": ["Me"]}, "/sections/0/tasks/0/score"),
        ({"name": "T", "score": 3, "actors": []}, "/sections/0/tasks/0/actors"),
        ({"name": "Section planning", "score": 3, "actors": ["Me"]}, "/sections/0/tasks/0/name"),
    ],
    ids=["score-0", "score-6", "decimal-score", "no-actors", "keyword-name"],
)
def test_journey_rules(task: dict, path: str) -> None:
    assert error_path(journey(task)) == path


def test_journey_comma_in_actor_is_encoded() -> None:
    assert "T: 3: Me, Smith#44; J" in render.render(journey({"name": "T", "score": 3, "actors": ["Me", "Smith, J"]}))


# --- gitGraph --------------------------------------------------------------------------------

def git(*ops: dict, **extra) -> dict:
    return {"diagram": "git", "target": "gitGraph", "ops": list(ops), **extra}


C = {"type": "commit"}


@pytest.mark.parametrize(
    ("doc", "path"),
    [
        (git(C, {"type": "checkout", "name": "nope"}), "/ops/1/name"),
        (git(C, {"type": "branch", "name": "dev"}, {"type": "branch", "name": "dev"}), "/ops/2/name"),
        (git(C, {"type": "branch", "name": "main"}), "/ops/1/name"),
        (git(C, {"type": "merge", "name": "main"}), "/ops/1/name"),
        (git({"type": "branch", "name": "dev"}, C, {"type": "checkout", "name": "main"}, {"type": "merge", "name": "dev"}), "/ops/3"),
        (git(C, {"type": "branch", "name": "dev"}, {"type": "checkout", "name": "main"}, {"type": "merge", "name": "dev"}), "/ops/3/name"),
        (git(C, {"type": "branch", "name": "dev"}, {"type": "merge", "name": "main"}), "/ops/2/name"),
        (git({"type": "commit", "id": "a"}, {"type": "commit", "id": "a"}), "/ops/1/id"),
        (git({"type": "commit", "id": "a"}, {"type": "cherry-pick", "id": "a"}), "/ops/1/id"),
        (git(C, {"type": "cherry-pick", "id": "zz"}), "/ops/1/id"),
        (git({"type": "commit", "id": "a"}, {"type": "branch", "name": "dev"}, {"type": "commit", "id": "b"},
             {"type": "checkout", "name": "main"}, {"type": "commit", "id": "c"}, {"type": "merge", "name": "dev", "id": "m"},
             {"type": "branch", "name": "rel"}, {"type": "checkout", "name": "dev"}, {"type": "cherry-pick", "id": "m"}),
         "/ops/8/parent"),
        (git({"type": "commit", "id": "a"}, {"type": "branch", "name": "dev"}, {"type": "commit", "id": "b"},
             {"type": "checkout", "name": "main"}, {"type": "cherry-pick", "id": "b", "parent": "b"}), "/ops/4/parent"),
        (git(C, orientation="TB", colon=True), "/colon"),
        (git({"type": "rebase"}), "/ops/0/type"),
    ],
    ids=["checkout-undeclared", "branch-twice", "branch-main", "merge-self", "merge-into-empty",
         "merge-same-head", "merge-own-base", "duplicate-commit-id", "cherry-pick-same-branch",
         "cherry-pick-unknown", "cherry-pick-merge-needs-parent", "cherry-pick-parent-not-parent",
         "colon-with-orientation", "unknown-op"],
)
def test_gitgraph_operations_must_be_valid_in_order(doc: dict, path: str) -> None:
    assert error_path(doc) == path


def test_gitgraph_main_branch_name_comes_from_config() -> None:
    doc = git(C, {"type": "branch", "name": "dev"}, C, {"type": "checkout", "name": "trunk"},
              {"type": "merge", "name": "dev"}, config={"gitGraph": {"mainBranchName": "trunk"}})
    assert 'merge "dev"' in render.render(doc)
    doc["config"]["gitGraph"]["mainBranchName"] = "main"
    assert error_path(doc) == "/ops/3/name"


# --- kanban ----------------------------------------------------------------------------------

def kanban(*columns: dict) -> dict:
    return {"diagram": "board", "target": "kanban", "columns": list(columns)}


@pytest.mark.parametrize(
    ("doc", "path"),
    [
        (kanban({"id": "a", "label": "A", "cards": [{"id": "a", "label": "Card"}]}), "/columns/0/cards/0/id"),
        (kanban({"id": "a", "label": "A", "plain": True}), "/columns/0/plain"),
        (kanban({"label": "A", "cards": [{"label": "C", "priority": "Urgent"}]}), "/columns/0/cards/0/priority"),
        (kanban({"label": "kanban board", "plain": True}), "/columns/0/label"),
        (kanban(), "/columns"),
    ],
    ids=["duplicate-id", "plain-with-id", "unknown-priority", "keyword-plain-column", "no-columns"],
)
def test_kanban_rules(doc: dict, path: str) -> None:
    assert error_path(doc) == path
