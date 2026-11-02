"""Catalog files: one per type, fixed sections, feature ids, and every fence passes check.sh."""

from __future__ import annotations

import pytest

from skill_docs import (
    CATALOG_DIR,
    HAVE_CLI,
    SECTIONS,
    builder_state,
    coverage_rows,
    feature_ids,
    run_check_markdown,
    sections,
    type_set,
)

# Types whose catalog file is not written yet. Emptied by task 5.6, removed by task 8.
PENDING_TYPES: set[str] = {
        "gantt", "timeline", "userJourney", "gitgraph", "kanban", "mindmap",
    "pie", "quadrantChart", "xyChart", "sankey", "radar", "treemap", "venn",
    "c4", "architecture", "block", "packet", "requirementDiagram",
    "agentflow", "usecase", "swimlanes", "wardley", "cynefin", "eventmodeling",
    "ishikawa", "treeView", "railroad", "zenuml", "info",
}


def catalog_files():
    return sorted(CATALOG_DIR.glob("*.md"))


def test_catalog_stems_equal_the_type_set() -> None:
    expected = type_set() - PENDING_TYPES
    actual = {path.stem for path in catalog_files()}
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    assert not missing, f"types without a catalog file: {missing}"
    assert not extra, f"catalog files naming no pending-free type: {extra}"
    assert PENDING_TYPES <= type_set(), f"PENDING_TYPES not in the type set: {sorted(PENDING_TYPES - type_set())}"


@pytest.mark.parametrize("path", catalog_files(), ids=lambda p: p.stem)
def test_sections_in_order(path) -> None:
    text = path.read_text()
    assert text.startswith("# "), f"{path.name} must start with an H1 title"
    assert tuple(sections(text)) == SECTIONS, f"{path.name} sections: {list(sections(text))}"


@pytest.mark.parametrize("path", catalog_files(), ids=lambda p: p.stem)
def test_feature_ids_unique_and_prefixed(path) -> None:
    ids = feature_ids(path.read_text())
    assert ids, f"{path.name} has no features"
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    assert not duplicates, f"{path.name} repeats feature ids {duplicates}"
    bad = [i for i in ids if not i.startswith(f"{path.stem}.")]
    assert not bad, f"{path.name} feature ids must start with '{path.stem}.': {bad}"


@pytest.mark.parametrize("path", catalog_files(), ids=lambda p: p.stem)
def test_builder_section_matches_coverage(path) -> None:
    rows = {row.type_id: row for row in coverage_rows()}
    assert builder_state(path.read_text()) == rows[path.stem].builder


@pytest.mark.skipif(not HAVE_CLI, reason="needs Mermaid CLI 12.0.0 or npx")
def test_every_catalog_fence_passes_check() -> None:
    files = catalog_files()
    if not files:
        pytest.skip("no catalog files yet")
    result = run_check_markdown(*files)
    assert result.returncode == 0, result.stdout + result.stderr
