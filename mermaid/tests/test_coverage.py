"""coverage.md is the checked matrix of types, catalog files, and builders."""

from __future__ import annotations

from skill_docs import BUILDER_STATES, coverage_rows, load_render, type_set

render = load_render()

def serializer_keywords() -> set[str]:
    keywords = {target for _family, target in render.SERIALIZERS}
    keywords |= set(getattr(render, "HAND_AUTHOR_ONLY", {}))
    return keywords


def test_one_row_per_type() -> None:
    ids = [row.type_id for row in coverage_rows()]
    assert len(ids) == len(set(ids)), "duplicate coverage rows"
    assert set(ids) == type_set(), (
        f"missing rows: {sorted(type_set() - set(ids))}; extra rows: {sorted(set(ids) - type_set())}"
    )


def test_catalog_column_names_the_type_file() -> None:
    for row in coverage_rows():
        assert row.catalog == f"catalog/{row.type_id}.md", row


def test_builder_column_values() -> None:
    for row in coverage_rows():
        assert row.builder in BUILDER_STATES, f"{row.type_id}: Builder column {row.builder!r}"


def test_builder_rows_have_no_gaps() -> None:
    bad = [row.type_id for row in coverage_rows() if row.builder == "builder" and row.gaps != "—"]
    assert not bad, f"builder rows with gaps: {bad}"


def test_keywords_match_the_serializer_table() -> None:
    listed: dict[str, str] = {}
    for row in coverage_rows():
        for keyword in row.keywords:
            assert keyword not in listed, f"{keyword} listed for {listed.get(keyword)} and {row.type_id}"
            listed[keyword] = row.type_id
    known = serializer_keywords()
    only_doc = sorted(set(listed) - known)
    only_code = sorted(known - set(listed))
    assert not only_doc and not only_code, (
        f"in coverage.md but not render.py: {only_doc}; in render.py but not coverage.md: {only_code}"
    )


def test_hand_author_only_rows_have_no_serializer() -> None:
    targets = {target for _family, target in render.SERIALIZERS}
    for row in coverage_rows():
        if row.builder == "hand-author-only":
            overlap = sorted(set(row.keywords) & targets)
            assert not overlap, f"{row.type_id} is hand-author-only but render.py serializes {overlap}"
