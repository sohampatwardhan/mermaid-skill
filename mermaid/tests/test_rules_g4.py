"""Type-specific semantic rules for group 4 builders: c4, architecture, block, packet, requirementDiagram.

The generic reliability bar (fixtures, parity, corpus, strictness, pinned check) lives in
test_builders.py. These tests pin the rules that come from Mermaid 12.0.0 behaviour: inputs that
would parse but draw something else, or crash the layout, must fail with a JSON path.
"""

from __future__ import annotations

import copy
import json

import pytest

from skill_docs import SKILL_DIR, load_render

render = load_render()
IRError = render.IRError
FIXTURES = SKILL_DIR / "tests" / "fixtures"


def fixture(type_id: str, name: str = "maximal.json") -> dict:
    return json.loads((FIXTURES / type_id / name).read_text())


def error_path(doc: dict) -> str:
    with pytest.raises(IRError) as info:
        render.render(doc)
    return info.value.path


# --- packet ---------------------------------------------------------------------------------

PACKET = {"diagram": "packet", "target": "packet"}


def test_packet_fields_must_be_contiguous() -> None:
    gap = {**PACKET, "fields": [{"start": 0, "end": 7, "label": "A"}, {"start": 16, "end": 31, "label": "B"}]}
    assert error_path(gap) == "/fields/1/start"
    late_start = {**PACKET, "fields": [{"start": 8, "end": 15, "label": "A"}]}
    assert error_path(late_start) == "/fields/0/start"
    single = {**PACKET, "fields": [{"bits": 4, "label": "A"}, {"bit": 5, "label": "B"}]}
    assert error_path(single) == "/fields/1/bit"


def test_packet_bit_counts_advance_the_cursor() -> None:
    doc = {**PACKET, "fields": [{"bits": 16, "label": "A"}, {"start": 16, "end": 31, "label": "B"}, {"bit": 32, "label": "C"}]}
    assert render.render(doc).splitlines()[1:] == ['    +16: "A"', '    16-31: "B"', '    32: "C"']


def test_packet_rejects_zero_widths_and_reversed_ranges() -> None:
    assert error_path({**PACKET, "fields": [{"bits": 0, "label": "A"}]}) == "/fields/0/bits"
    assert error_path({**PACKET, "fields": [{"start": 0, "end": 0, "label": "A"}]}) == "/fields/0/end"
    assert error_path({**PACKET, "fields": [{"start": 0, "label": "A"}]}) == "/fields/0/end"
    assert error_path({**PACKET, "fields": [{"bits": 2, "bit": 0, "label": "A"}]}) == "/fields/0"


def test_packet_title_goes_to_frontmatter_only_on_request() -> None:
    doc = {**PACKET, "title": "UDP", "fields": [{"bits": 8, "label": "A"}]}
    assert "    title UDP" in render.render(doc)
    front = render.render({**doc, "title_in_frontmatter": True})
    assert front.startswith('---\ntitle: "UDP"\n---\npacket\n') and "    title" not in front
    assert error_path({**PACKET, "title_in_frontmatter": True, "fields": [{"bits": 8, "label": "A"}]}) == "/title_in_frontmatter"


def test_packet_label_encodes_quote_hash_and_backslash() -> None:
    doc = {**PACKET, "fields": [{"bits": 8, "label": 'say "hi" #1 a\\b'}]}
    assert '+8: "say #quot;hi#quot; #35;1 a#92;b"' in render.render(doc)


# --- block ----------------------------------------------------------------------------------

BLOCK = {"diagram": "graph", "target": "block"}


def test_block_edge_to_undeclared_block_is_rejected() -> None:
    # Mermaid would silently create a new block and shift the grid.
    doc = {**BLOCK, "blocks": [{"id": "a"}], "edges": [{"from": "a", "to": "ghost"}]}
    assert error_path(doc) == "/edges/0/to"


def test_block_composites_nest_and_can_be_edge_endpoints() -> None:
    doc = {**BLOCK, "blocks": [
        {"kind": "composite", "id": "outer", "children": [{"kind": "composite", "id": "inner", "children": [{"id": "a"}]}]},
        {"id": "b"},
    ], "edges": [{"from": "inner", "to": "b"}]}
    assert render.render(doc).splitlines()[1:] == [
        "  block:outer", "    block:inner", "      a", "    end", "  end", "  b", "  inner --> b"]


def test_block_rejects_keywords_and_misplaced_keys() -> None:
    assert error_path({**BLOCK, "blocks": [{"id": "end"}]}) == "/blocks/0/id"
    assert error_path({**BLOCK, "blocks": [{"id": "a", "shape": "round"}]}) == "/blocks/0/shape"
    assert error_path({**BLOCK, "blocks": [{"kind": "composite", "label": "L", "children": [{"id": "a"}]}]}) == "/blocks/0/label"
    assert error_path({**BLOCK, "blocks": [{"kind": "composite", "children": []}]}) == "/blocks/0/children"
    assert error_path({**BLOCK, "blocks": [{"id": "a"}, {"id": "a"}]}) == "/blocks/1/id"
    assert error_path({**BLOCK, "blocks": [{"id": "a"}], "edges": [{"from": "a", "to": "a", "kind": "dotted"}]}) == "/edges/0/kind"


def test_block_class_must_be_defined_and_style_values_are_typed() -> None:
    doc = {**BLOCK, "blocks": [{"id": "a"}], "class_assignments": [{"blocks": ["a"], "class": "blue"}]}
    assert error_path(doc) == "/class_assignments/0/class"
    raw = {**BLOCK, "blocks": [{"id": "a"}], "styles": [{"block": "a", "style": {"fill": "#f9f;stroke:#000"}}]}
    assert error_path(raw) == "/styles/0/style/fill"
    empty = {**BLOCK, "blocks": [{"id": "a"}], "styles": [{"block": "a", "style": {}}]}
    assert error_path(empty) == "/styles/0/style"


def test_block_non_breaking_space_becomes_an_html_entity() -> None:
    doc = {**BLOCK, "blocks": [{"kind": "arrow", "id": "x", "label": "a\u00a0b", "directions": ["x", "down"]}]}
    assert '  x<["a&nbsp;b"]>(x, down)' in render.render(doc)
    dup = {**BLOCK, "blocks": [{"kind": "arrow", "id": "x", "label": "a", "directions": ["x", "x"]}]}
    assert error_path(dup) == "/blocks/0/directions/1"


# --- architecture ---------------------------------------------------------------------------

ARCH = {"diagram": "graph", "target": "architecture-beta"}
TWO = [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]


def test_architecture_second_edge_between_the_same_pair_is_rejected() -> None:
    # Mermaid 12.0.0: "Can not create second element with ID a-b".
    doc = {**ARCH, "nodes": TWO, "edges": [
        {"from": "a", "from_side": "R", "to": "b", "to_side": "L"},
        {"from": "a", "from_side": "T", "to": "b", "to_side": "B"},
    ]}
    assert error_path(doc) == "/edges/1"
    reverse = copy.deepcopy(doc)
    reverse["edges"][1] = {"from": "b", "from_side": "B", "to": "a", "to_side": "T"}
    render.render(reverse)


def test_architecture_group_modifier_needs_a_grouped_service() -> None:
    doc = {**ARCH, "nodes": TWO, "edges": [{"from": "a", "from_side": "R", "from_group": True, "to": "b", "to_side": "L"}]}
    assert error_path(doc) == "/edges/0/from_group"


def test_architecture_group_is_not_an_edge_endpoint() -> None:
    doc = {**ARCH, "groups": [{"id": "g", "label": "G"}], "nodes": [{"id": "a", "label": "A", "group": "g"}],
           "edges": [{"from": "a", "from_side": "R", "to": "g", "to_side": "L"}]}
    assert error_path(doc) == "/edges/0/to"


def test_architecture_parent_group_must_come_first() -> None:
    doc = {**ARCH, "groups": [{"id": "inner", "label": "I", "group": "outer"}, {"id": "outer", "label": "O"}],
           "nodes": [{"id": "a", "label": "A"}]}
    assert error_path(doc) == "/groups/0/group"


def test_architecture_ids_and_icons() -> None:
    for bad in ("Rack", "Box", "title_x", "service", "in"):
        assert error_path({**ARCH, "nodes": [{"id": bad, "label": "A"}]}) == "/nodes/0/id", bad
    assert error_path({**ARCH, "nodes": [{"id": "a", "label": "A", "icon": "made-up"}]}) == "/nodes/0/icon"
    assert "service a(logos:aws-s3)[A]" in render.render({**ARCH, "nodes": [{"id": "a", "label": "A", "icon": "logos:aws-s3"}]})
    assert error_path({**ARCH, "nodes": [{"id": "j", "kind": "junction", "label": "x"}]}) == "/nodes/0/label"


def test_architecture_brackets_switch_to_the_quoted_title_form() -> None:
    assert 'service a["[x] y"]' in render.render({**ARCH, "nodes": [{"id": "a", "label": "[x] y"}]})
    assert 'service a[say "hi"]' in render.render({**ARCH, "nodes": [{"id": "a", "label": 'say "hi"'}]})
    assert error_path({**ARCH, "nodes": [{"id": "a", "label": '[say "hi"]'}]}) == "/nodes/0/label"
    assert error_path({**ARCH, "nodes": [{"id": "a", "label": "*bold*"}]}) == "/nodes/0/label"


def test_architecture_alignment_needs_two_declared_members() -> None:
    doc = {**ARCH, "nodes": TWO, "alignments": [{"axis": "row", "members": ["a"]}]}
    assert error_path(doc) == "/alignments/0/members"
    doc["alignments"][0]["members"] = ["a", "a"]
    assert error_path(doc) == "/alignments/0/members/1"


# --- c4 -------------------------------------------------------------------------------------

C4 = {"diagram": "graph", "target": "C4Context"}


def test_c4_kinds_follow_the_diagram_level() -> None:
    assert error_path({**C4, "nodes": [{"id": "spa", "label": "SPA", "kind": "container"}]}) == "/nodes/0/kind"
    rel_index = {**C4, "nodes": [{"id": "a", "label": "A", "kind": "person"}, {"id": "b", "label": "B", "kind": "system"}],
                 "edges": [{"from": "a", "to": "b", "label": "x", "kind": "rel_index", "index": 1}]}
    assert error_path(rel_index) == "/edges/0/kind"
    assert error_path({**C4, "nodes": [{"id": "a", "label": "A", "kind": "person", "technology": "x"}]}) == "/nodes/0/technology"


def test_c4_boundary_needs_a_child() -> None:
    doc = {**C4, "groups": [{"id": "b", "label": "B", "kind": "system_boundary"}],
           "nodes": [{"id": "a", "label": "A", "kind": "person"}]}
    assert error_path(doc) == "/groups/0"


def test_c4_description_without_technology_uses_named_descr() -> None:
    doc = {"diagram": "graph", "target": "C4Container",
           "nodes": [{"id": "c", "label": "C", "kind": "container", "description": "D"}]}
    assert '    Container(c, "C", $descr="D")' in render.render(doc)


def test_c4_title_and_acc_title_share_one_slot() -> None:
    doc = {**C4, "title": "T", "accessibility": {"title": "A"}, "nodes": [{"id": "a", "label": "A", "kind": "person"}]}
    assert error_path(doc) == "/accessibility/title"


def test_c4_rel_style_needs_a_matching_relationship() -> None:
    doc = fixture("c4", "maximal.C4Context.json")
    doc["rel_styles"][0] = {"from": "sysAA", "to": "customerA", "line_color": "red"}
    assert error_path(doc) == "/rel_styles/0"


def test_c4_positional_style_needs_every_earlier_parameter() -> None:
    doc = fixture("c4", "maximal.C4Context.json")
    doc["rel_styles"][1] = {"from": "sysAA", "to": "mail", "line_color": "red", "form": "positional"}
    assert error_path(doc) == "/rel_styles/1/form"


def test_c4_line_breaks_and_shape_text_limits() -> None:
    ok = {**C4, "nodes": [{"id": "a", "label": "Line one\nline two", "kind": "person"}]}
    assert 'Person(a, "Line one<br/>line two")' in render.render(ok)
    for bad in ("a > b", "a  b", "#quot;", "x\n\ny"):
        assert error_path({**C4, "nodes": [{"id": "a", "label": bad, "kind": "person"}]}) == "/nodes/0/label", bad


def test_c4_title_encodes_lexer_breakers() -> None:
    doc = {**C4, "title": "A; B #1 & co", "nodes": [{"id": "a", "label": "A", "kind": "person"}]}
    assert "    title A#59; B #35;1 #amp; co" in render.render(doc)


# --- requirementDiagram ---------------------------------------------------------------------

REQ = {"diagram": "requirement-links", "target": "requirementDiagram"}


def test_requirement_rejects_lexer_keywords_as_names() -> None:
    for bad in ("element", "High", "TEST", "contains", "text"):
        assert error_path({**REQ, "requirements": [{"id": bad}]}) == "/requirements/0/id", bad
    render.render({**REQ, "requirements": [{"id": "testing"}]})


def test_requirement_link_kinds_and_references() -> None:
    base = {**REQ, "requirements": [{"id": "r1", "text": "text"}], "elements": [{"id": "e1", "type": "component"}]}
    assert error_path({**base, "links": [{"from": "e1", "to": "r1", "kind": "implies"}]}) == "/links/0/kind"
    assert error_path({**base, "links": [{"from": "e1", "to": "missing", "kind": "satisfies"}]}) == "/links/0/to"
    reverse = render.render({**base, "links": [{"from": "e1", "to": "r1", "kind": "copies", "reverse": True}]})
    assert "    r1 <- copies - e1" in reverse


def test_requirement_quoted_names_are_used_in_links() -> None:
    doc = {**REQ, "requirements": [{"id": "r1", "name": "Login works"}], "elements": [{"id": "e1"}],
           "links": [{"from": "e1", "to": "r1", "kind": "verifies"}]}
    source = render.render(doc)
    assert '    requirement "Login works" {' in source and '    e1 - verifies -> "Login works"' in source
    clash = {**REQ, "requirements": [{"id": "r1"}, {"id": "r2", "name": "r1"}]}
    assert error_path(clash) == "/requirements/1/name"


def test_requirement_text_escapes_markdown_unless_marked() -> None:
    plain = render.render({**REQ, "requirements": [{"id": "r1", "text": "a *b* __c__ <d>"}]})
    assert 'text: "a #42;b#42; #95;#95;c#95;#95; #lt;d#gt;"' in plain
    markdown = render.render({**REQ, "requirements": [{"id": "r1", "text": "a *b* <d>", "markdown": True}]})
    assert 'text: "a *b* #lt;d#gt;"' in markdown


def test_requirement_shorthand_takes_one_node_and_defined_classes() -> None:
    doc = {**REQ, "requirements": [{"id": "r1"}, {"id": "r2"}], "class_defs": [{"name": "hot", "style": {"fill": "#f00"}}],
           "class_assignments": [{"nodes": ["r1", "r2"], "classes": ["hot"], "shorthand": True}]}
    assert error_path(doc) == "/class_assignments/0/nodes"
    doc["class_assignments"] = [{"nodes": ["r1"], "classes": ["cold"]}]
    assert error_path(doc) == "/class_assignments/0/classes/0"
    doc["requirements"][0]["classes"] = ["cold"]
    assert error_path(doc) == "/requirements/0/classes/0"
