"""Prove the reliability harness fails on broken builders (it is not vacuous)."""

from __future__ import annotations

from pathlib import Path

import pytest

import builder_harness as h
from skill_docs import HAVE_CLI, load_render

render = load_render()
IRError = render.IRError

TOY_MAX = {"diagram": "toy", "target": "toy", "title": "Alpha", "items": [{"label": "Beta", "size": 2}]}
TOY_FEATURES = {"toy.title": "/title", "toy.item": "/items/*/label", "toy.size": "/items/*/size"}
TOY_PROBES = {"object": "/items/0", "number": "/items/0/size", "enum": None, "ref": None}


def strict_toy(doc: dict) -> str:
    v = render.Validator("toy")
    v.fields(doc, "", ("title", "items"))
    lines = [f"toy {v.text(doc['title'], '/title', 'bare.word.or.space')}"]
    for i, item in enumerate(v.array(doc["items"], "/items")):
        v.fields(item, f"/items/{i}", ("label", "size"))
        lines.append(f"  {v.text(item['label'], f'/items/{i}/label', 'bare.word.or.space')} {v.number(item['size'], f'/items/{i}/size')}")
    return "\n".join(lines) + "\n"


render.text_context("bare.word.or.space", reject_patterns=((r"[^\w ]", "only word characters and spaces"),))


def dropping_toy(doc: dict) -> str:
    """Validates like strict_toy but silently drops every item label."""
    strict_toy(doc)
    return f"toy {doc['title']}\n"


def lax_toy(doc: dict) -> str:
    """Never validates: accepts unknown keys and booleans as numbers."""
    return f"toy {doc.get('title')}\n" + "".join(f"  {i.get('label')} {i.get('size')}\n" for i in doc.get("items", []))


def test_strict_toy_passes_every_check() -> None:
    maximal = {"maximal.json": TOY_MAX}
    assert h.check_fixtures(strict_toy, {"minimal.json": TOY_MAX}, maximal)[0] == []
    assert h.check_parity(TOY_FEATURES, list(TOY_FEATURES), maximal) == []
    assert h.check_corpus(strict_toy, IRError, ("/title", "/items/*/label"), maximal)[0] == []
    assert h.check_strictness(strict_toy, IRError, TOY_PROBES, maximal) == []


def test_dropped_key_fails_the_corpus_check() -> None:
    problems, _ = h.check_corpus(dropping_toy, IRError, ("/items/*/label",), {"maximal.json": TOY_MAX})
    assert problems and all("/items/0/label" in p and "dropped" in p for p in problems)


def test_lax_builder_fails_strictness() -> None:
    problems = h.check_strictness(lax_toy, IRError, TOY_PROBES, {"maximal.json": TOY_MAX})
    joined = "\n".join(problems)
    assert "unknown root key: accepted" in joined
    assert "unknown nested key: accepted" in joined
    assert "number probe: accepted" in joined


def test_lax_builder_fails_corpus_rejection_paths() -> None:
    def wrong_path(doc: dict) -> str:
        if "%" in doc["title"]:
            raise IRError("toy", "/items", "wrong place")
        return strict_toy(doc)

    problems, _ = h.check_corpus(wrong_path, IRError, ("/title",), {"maximal.json": TOY_MAX})
    assert any("rejected at '/items', expected /title" in p for p in problems)


def test_parity_names_missing_and_unmatched_features() -> None:
    problems = h.check_parity({"toy.title": "/title", "toy.ghost": "/nope"}, ["toy.title", "toy.item", "toy.ghost"],
                              {"maximal.json": TOY_MAX})
    assert "catalog feature toy.item has no feature path in the builder" in problems
    assert "feature toy.ghost: pattern /nope matches no maximal fixture" in problems


def test_value_patterns() -> None:
    doc = {"nodes": [{"shape": "doc"}, {"shape": "rect", "n": 3}]}
    assert h.matches(doc, "/nodes/*/shape=rect") == ["/nodes/1/shape"]
    assert h.matches(doc, "/nodes/*/n=3") == ["/nodes/1/n"]
    assert h.matches(doc, "/nodes/*/shape=hex") == []


def test_catalog_features_skip_rows_that_do_not_render(tmp_path: Path) -> None:
    (tmp_path / "t.md").write_text(
        "# T\n\n## Features\n| Feature id | Construct | Snippet |\n|---|---|---|\n"
        "| `t.a` | a | `a` |\n| `t.b` | b (does not render in 12.0.0) | `b` |\n"
    )
    assert h.catalog_features("t", tmp_path) == ["t.a"]


def test_batch_maps_lines_to_cases() -> None:
    text, starts = h.batch_markdown([h.Case("one", "info\n"), h.Case("two", "pie\n  \"a\" : 1\n")])
    lines = text.splitlines()
    assert [label for _, label in starts] == ["one", "two"]
    assert lines[starts[1][0] - 1] == "pie"


@pytest.mark.skipif(not HAVE_CLI, reason="needs Mermaid CLI 12.0.0 or npx")
def test_batch_reports_the_failing_case() -> None:
    cases = [h.Case("good", "info\n"), h.Case("bad", "flowchart TD\n  A --> B\n  B --> --> C\n")]
    problems = h.run_batch(cases)
    assert len(problems) == 1 and problems[0].startswith("bad: "), problems
