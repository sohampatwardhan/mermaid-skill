"""Reliability bar for every kept builder (coverage.md Builder column `builder`).

Per type: minimal and maximal fixtures serialize deterministically, the maximal fixtures cover
every catalog feature id, every text field takes the corpus, unknown keys and bad values fail
at the right JSON path, and every accepted source parses with the pinned Mermaid 12.0.0 in one
`check.sh --markdown` batch. "Accepted IR parses" is the reliability bar: unrepresentable input
is rejected with a JSON path, and everything accepted parses with the pin.
"""

from __future__ import annotations

import pytest

import builder_harness as h
from skill_docs import HAVE_CLI, coverage_rows, load_render

render = load_render()

KEPT = sorted(row.type_id for row in coverage_rows() if row.builder == "builder")
BY_TYPE = {b.type_id: b for b in render.BUILDERS.values()}


def renderer(builder):
    keyword = builder.keywords[0]

    def run(doc: dict) -> str:
        return render.render(doc, target=doc.get("target") or keyword)

    return run


def fixtures(type_id: str):
    return h.load_fixtures(type_id, "minimal"), h.load_fixtures(type_id, "maximal")


def all_cases(builder) -> tuple[list[str], list[h.Case]]:
    minimal, maximal = fixtures(builder.type_id)
    problems, cases = h.check_fixtures(renderer(builder), minimal, maximal)
    corpus_problems, corpus_cases = h.check_corpus(renderer(builder), render.IRError, builder.text_fields, maximal)
    return problems + corpus_problems, cases + corpus_cases


def test_kept_types_have_builders() -> None:
    missing = [t for t in KEPT if t not in BY_TYPE]
    assert not missing, f"coverage.md marks these as builder but render.py has none: {missing}"


@pytest.mark.parametrize("type_id", KEPT)
def test_fixtures_render(type_id: str) -> None:
    minimal, maximal = fixtures(type_id)
    problems, _ = h.check_fixtures(renderer(BY_TYPE[type_id]), minimal, maximal)
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("type_id", KEPT)
def test_feature_parity(type_id: str) -> None:
    _, maximal = fixtures(type_id)
    problems = h.check_parity(BY_TYPE[type_id].features, h.catalog_features(type_id), maximal)
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("type_id", KEPT)
def test_text_corpus(type_id: str) -> None:
    builder = BY_TYPE[type_id]
    _, maximal = fixtures(type_id)
    problems, _ = h.check_corpus(renderer(builder), render.IRError, builder.text_fields, maximal)
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("type_id", KEPT)
def test_strictness(type_id: str) -> None:
    builder = BY_TYPE[type_id]
    _, maximal = fixtures(type_id)
    problems = h.check_strictness(renderer(builder), render.IRError, builder.probes, maximal)
    assert not problems, "\n".join(problems)


@pytest.mark.skipif(not HAVE_CLI, reason="needs Node and the pinned Mermaid 12.0.0 parser")
@pytest.mark.parametrize("type_id", KEPT)
def test_pinned_check(type_id: str) -> None:
    """Every fixture and every accepted corpus substitution parses, in one check.sh run."""
    _, cases = all_cases(BY_TYPE[type_id])
    assert cases, "nothing to check"
    problems = h.run_batch(cases)
    assert not problems, "\n".join(problems)
