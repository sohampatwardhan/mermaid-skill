"""Type-specific rules for group 6 builders: ishikawa, treeView, railroad, info, and zenuml (removed).

The shared reliability bar lives in tests/test_builders.py. These tests pin the semantic rules
behind it: Mermaid 12.0.0 lexer traps each builder rejects, and the railroad notations that
test_builders.py does not reach (its corpus pass uses only the first matching fixture).
"""

from __future__ import annotations

import copy
import json

import pytest

import builder_harness as h
from skill_docs import HAVE_CLI, load_render

render = load_render()
IRError = render.IRError
FIXTURES = h.FIXTURES


def fixture(type_id: str, name: str) -> dict:
    return json.loads((FIXTURES / type_id / name).read_text())


def rejects(doc: dict, path: str, reason: str = "") -> IRError:
    with pytest.raises(IRError) as info:
        render.render(doc)
    assert info.value.path == path, str(info.value)
    assert reason in info.value.reason, str(info.value)
    return info.value


# --- ishikawa -------------------------------------------------------------------------------


def test_ishikawa_nests_by_indentation() -> None:
    source = render.render(fixture("ishikawa", "maximal.json"))
    assert "    Blurry Photo\n    Process\n        Out of focus\n" in source
    assert "        LENS\n            Inappropriate lens\n" in source


def test_ishikawa_alias_keyword() -> None:
    assert render.render(fixture("ishikawa", "maximal.ishikawa.json")).startswith("ishikawa\n")


def test_ishikawa_rejects_lexer_traps() -> None:
    doc = fixture("ishikawa", "maximal.json")
    rejects(h.with_value(doc, "/causes/0/label", "Ishikawa notes"), "/causes/0/label", "keyword")
    rejects(h.with_value(doc, "/effect", "x < y"), "/effect", "'<'")
    rejects(h.with_value(doc, "/causes/1/children/0/label", "%%note"), "/causes/1/children/0/label", "%%")
    rejects(h.with_value(doc, "/causes/1/children/0/label", "a #amp; b"), "/causes/1/children/0/label", "entity")


def test_ishikawa_has_no_accessibility() -> None:
    doc = {**fixture("ishikawa", "minimal.json"), "accessibility": {"title": "Fish"}}
    rejects(doc, "/accessibility", "unknown key")


# --- treeView -------------------------------------------------------------------------------


def test_treeview_quotes_only_when_needed() -> None:
    doc = {"diagram": "tree", "target": "treeView-beta", "nodes": [
        {"name": "src", "directory": True, "children": [{"name": "title.md"}, {"name": 'say "hi"'}]},
    ]}
    source = render.render(doc)
    assert "    src/\n" in source
    assert '"title.md"' in source  # a bare name starting with `title` is read as a title
    assert "'say \"hi\"'" in source


def test_treeview_rejects_unrepresentable_names() -> None:
    doc = fixture("treeView", "minimal.json")
    rejects(h.with_value(doc, "/nodes/0/name", "it's \"x\""), "/nodes/0/name", "both")
    rejects(h.with_value(doc, "/nodes/0/name", "src/"), "/nodes/0/name", "directory")
    rejects(h.with_value(doc, "/nodes/0/name", "├── a"), "/nodes/0/name", "'├'")
    rejects(h.with_value(doc, "/nodes/0/name", "#lt;b"), "/nodes/0/name", "entity")


def test_treeview_description_rejects_lt() -> None:
    doc = fixture("treeView", "maximal.json")
    rejects(h.with_value(doc, "/nodes/0/children/2/description", "a < b"), "/nodes/0/children/2/description", "'<'")


def test_treeview_icon_rules() -> None:
    doc = fixture("treeView", "maximal.json")
    rejects(h.with_value(doc, "/nodes/0/children/0/children/0/icon", {"pack": "logos"}),
            "/nodes/0/children/0/children/0/icon/name", "required")
    rejects(h.with_value(doc, "/nodes/0/children/0/children/0/icon", {"name": "a b"}),
            "/nodes/0/children/0/children/0/icon/name", "identifier")


def test_treeview_box_drawing_prefixes() -> None:
    source = render.render(fixture("treeView", "maximal.box-heavy.json"))
    assert source.splitlines()[1:] == ["┣━━ packages/", "┃   ┣━━ mermaid/", "┃   ┃   ┗━━ parser.ts",
                                       "┃   ┗━━ parser/", "┗━━ README.md"]


def test_treeview_box_style_needs_one_line_description() -> None:
    doc = {**fixture("treeView", "maximal.box.json"), "accessibility": {"description": "one\ntwo"}}
    rejects(doc, "/accessibility/description", "one line")


# --- railroad -------------------------------------------------------------------------------

RAILROAD_FIXTURES = {
    "railroad-ebnf-beta": "maximal.json",
    "railroad-abnf-beta": "maximal.railroad-abnf-beta.json",
    "railroad-peg-beta": "maximal.railroad-peg-beta.json",
    "railroad-beta": "maximal.railroad-beta.json",
}
# Text fields per notation (test_builders.py's corpus pass reaches only the EBNF fixture).
RAILROAD_TEXT = {
    "railroad-abnf-beta": ("/title", "/rules/0/comment/text", "/rules/0/expression/items/2/text"),
    "railroad-peg-beta": ("/title", "/rules/0/comment/text", "/rules/1/expression/items/0/text",
                          "/rules/1/expression/items/1/text"),
    "railroad-beta": ("/title", "/accessibility/description", "/rules/0/comment/text",
                      "/rules/1/expression/items/0/item/text", "/rules/1/expression/items/2/text"),
}
NOTATION_PREFIX = {"railroad-ebnf-beta": "railroad.ebnf-", "railroad-abnf-beta": "railroad.abnf-",
                   "railroad-peg-beta": "railroad.peg-", "railroad-beta": "railroad.ir-"}


def railroad_builder():
    return render.BUILDERS["railroad-ebnf-beta"]


@pytest.mark.parametrize("keyword", sorted(NOTATION_PREFIX))
def test_railroad_notation_features_live_in_their_own_fixture(keyword: str) -> None:
    doc = fixture("railroad", RAILROAD_FIXTURES[keyword])
    assert doc["target"] == keyword
    for feature_id, pattern in railroad_builder().features.items():
        if feature_id.startswith(NOTATION_PREFIX[keyword]):
            assert h.matches(doc, pattern), f"{feature_id}: {pattern} not in {RAILROAD_FIXTURES[keyword]}"


def railroad_corpus_cases() -> tuple[list[str], list[h.Case]]:
    problems: list[str] = []
    cases: list[h.Case] = []
    for keyword, fields in RAILROAD_TEXT.items():
        name = RAILROAD_FIXTURES[keyword]
        found, more = h.check_corpus(render.render, IRError, fields, {name: fixture("railroad", name)})
        problems += found
        cases += more
    return problems, cases


def test_railroad_corpus_in_every_notation() -> None:
    problems, _ = railroad_corpus_cases()
    assert not problems, "\n".join(problems)


@pytest.mark.skipif(not HAVE_CLI, reason="needs Node and the pinned Mermaid 12.0.0 parser")
def test_railroad_corpus_in_every_notation_renders() -> None:
    _, cases = railroad_corpus_cases()
    problems = h.run_batch(cases)
    assert not problems, "\n".join(problems)


def test_railroad_groups_by_precedence() -> None:
    doc = fixture("railroad", "maximal.json")
    source = render.render(doc)
    assert 'expression = term ( ( "+" | "-" ) term )* ;' in source
    assert "term ::= factor , { ( '*' | '/' ) , factor } ;" in source
    peg = render.render(fixture("railroad", "maximal.railroad-peg-beta.json"))
    assert "Identifier <- !Keyword &Letter Letter Letter* Digit? ;" in peg


def test_railroad_escapes_quotes_per_notation() -> None:
    doc = fixture("railroad", "minimal.json")
    doc = h.with_value(doc, "/rules/0/expression/items/0/text", 'say "hi" \\ ok')
    assert '"say \\"hi\\" \\\\ ok"' in render.render(doc)
    abnf = fixture("railroad", "maximal.railroad-abnf-beta.json")
    rejects(h.with_value(abnf, "/rules/0/expression/items/2/text", 'a"b'), "/rules/0/expression/items/2/text", "'\"'")
    rejects(h.with_value(abnf, "/rules/0/expression/items/2", {"kind": "terminal", "text": "@", "quote": "single"}),
            "/rules/0/expression/items/2/quote", "unknown value")


def test_railroad_rule_names() -> None:
    doc = fixture("railroad", "maximal.json")
    rejects(h.with_value(doc, "/rules/8/name", "titles"), "/rules/8/name", "title")
    rejects(h.with_value(doc, "/rules/8/name", "sign"), "/rules/8/name", "duplicate")
    ir = fixture("railroad", "maximal.railroad-beta.json")
    rejects(h.with_value(ir, "/rules/2/name", "choice"), "/rules/2/name", "constructor")
    abnf = fixture("railroad", "maximal.railroad-abnf-beta.json")
    rejects(h.with_value(abnf, "/rules/1/name", "my_code"), "/rules/1/name", "identifier")


def test_railroad_references() -> None:
    doc = fixture("railroad", "maximal.json")
    rejects(h.with_value(doc, "/rules/7/expression/item/name", "ALPHA"), "/rules/7/expression/item/name", "undeclared")
    # ABNF core rules (RFC 5234 appendix B) need no declaration.
    assert "1*DIGIT" in render.render(fixture("railroad", "minimal.railroad-abnf-beta.json"))


@pytest.mark.parametrize("keyword, pointer, node", [
    ("railroad-abnf-beta", "/rules/1/expression", {"kind": "special", "text": "x"}),
    ("railroad-peg-beta", "/rules/4/expression", {"kind": "exception", "item": {"kind": "anyChar"},
                                                  "except": {"kind": "anyChar"}}),
    ("railroad-beta", "/rules/4/expression", {"kind": "group", "item": {"kind": "nonterminal", "name": "digit"}}),
    ("railroad-ebnf-beta", "/rules/8/expression", {"kind": "anyChar"}),
])
def test_railroad_kinds_outside_their_notation(keyword: str, pointer: str, node: dict) -> None:
    doc = h.with_value(fixture("railroad", RAILROAD_FIXTURES[keyword]), pointer, node)
    rejects(doc, f"{pointer}/kind", "cannot be written")


def test_railroad_forms_and_separators_per_notation() -> None:
    peg = fixture("railroad", "maximal.railroad-peg-beta.json")
    rejects(h.with_value(peg, "/rules/0/expression/items/4/form", "brackets"), "/rules/0/expression/items/4/form")
    ir = fixture("railroad", "maximal.railroad-beta.json")
    bad = copy.deepcopy(ir)
    bad["rules"][1]["expression"]["items"][0]["form"] = "postfix"
    rejects(bad, "/rules/1/expression/items/0/form", "no form")
    bad = copy.deepcopy(ir)
    bad["rules"][0]["expression"]["separator"] = "comma"
    rejects(bad, "/rules/0/expression/separator", "no separator")


def test_railroad_postfix_question_mark_before_another_is_rejected() -> None:
    # `sign? digit+ ? any ?` would lex `? digit+ ?` as one special sequence.
    doc = fixture("railroad", "maximal.json")
    special = {"kind": "special", "text": "any"}
    doc["rules"][3]["expression"]["items"].append(special)
    rejects(doc, "/rules/3/expression/items/0", "special sequence")
    doc["rules"][3]["expression"]["items"][0]["form"] = "brackets"
    assert "number = [ sign ] digit+" in render.render(doc)


def test_railroad_abnf_numbers() -> None:
    doc = fixture("railroad", "maximal.railroad-abnf-beta.json")
    assert "hex = %x30-39 / %d65 / %b1000001 / %x41 ;" in render.render(doc)
    rejects(h.with_value(doc, "/rules/5/expression/items/0/to", 48), "/rules/5/expression/items/0/to", "> 48")
    rejects(h.with_value(doc, "/rules/4/expression/items/0/max", 1), "/rules/4/expression/items/0/max", ">= 2")
    rejects(h.with_value(doc, "/rules/4/expression/items/0/min", 1.5), "/rules/4/expression/items/0/min", "integer")


# --- info and zenuml -------------------------------------------------------------------------


def test_info_show_info_flag() -> None:
    assert render.render({"diagram": "info", "target": "info", "showInfo": False}) == "info\n"
    assert render.render({"diagram": "info", "target": "info", "showInfo": True}) == "info showInfo\n"
    rejects({"diagram": "info", "target": "info", "showInfo": "yes"}, "/showInfo", "true or false")


def test_zenuml_is_hand_author_only() -> None:
    ir = {"diagram": "sequence", "target": "zenuml", "actors": [{"id": "A"}], "steps": []}
    err = rejects(ir, "/target", "hand-author-only")
    assert "reference/catalog/zenuml.md" in err.reason
    assert "zenuml" not in render.BUILDERS
