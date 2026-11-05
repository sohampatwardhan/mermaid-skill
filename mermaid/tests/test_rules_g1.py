"""Type-specific semantic rules for the group 1 builders (core graph types).

The generic reliability bar (fixtures, parity, corpus, strictness, pinned check) lives in
test_builders.py. Each section below pins rules that come from Mermaid 12.0.0 lexer facts or
from the IR's own semantics (references, nesting, uniqueness) for one type. Helpers carry the
type prefix (_fc_, _seq_, _cls_, _st_, _er_) and tests the matching test_<prefix>_ prefix.
"""

from __future__ import annotations

import copy
import json
import subprocess

import pytest

from skill_docs import BASH, CHECK, HAVE_CLI, SKILL_DIR, load_render

render = load_render()
IRError = render.IRError



# === flowchart =================================================================================


def _fc_doc(**extra) -> dict:
    base = {"diagram": "graph", "target": "flowchart", "nodes": [{"id": "A"}, {"id": "B"}],
            "edges": [{"from": "A", "to": "B"}]}
    base.update(extra)
    return base


def _fc_error_path(ir: dict) -> str:
    with pytest.raises(IRError) as info:
        render.render(ir)
    assert info.value.target == ir["target"]
    assert info.value.reason
    return info.value.path


def test_fc_legacy_groups_kinds_and_edge_kinds_render() -> None:
    source = render.render({
        "diagram": "graph", "target": "flowchart", "direction": "TD",
        "groups": [{"id": "stage_1", "label": "Stage 1"}, {"id": "stage_2", "label": "Stage 2"}],
        "nodes": [
            {"id": "start", "label": "Begin", "kind": "terminator", "group": "stage_1"},
            {"id": "decide", "label": "Needs review?", "kind": "decision", "group": "stage_1"},
            {"id": "sub", "label": "Integration test", "kind": "subprocess", "group": "stage_2"},
            {"id": "log", "label": "Audit log", "kind": "store", "group": "stage_2"},
        ],
        "edges": [
            {"from": "start", "to": "decide", "kind": "normal"},
            {"from": "decide", "to": "sub", "kind": "dependency", "label": "yes"},
            {"from": "sub", "to": "log", "kind": "weak"},
            {"from": "log", "to": "start", "kind": "strong"},
        ],
    })
    assert source.startswith("flowchart TD\n")
    assert '    subgraph stage_1 ["Stage 1"]\n        start@{ shape: stadium, label: "Begin" }\n' in source
    assert 'decide@{ shape: diamond, label: "Needs review?" }' in source
    assert "shape: subproc" in source and "shape: cyl" in source
    assert '    decide -->|"yes"| sub\n' in source
    assert "    sub -.-> log\n" in source
    assert "    log ==> start\n" in source


@pytest.mark.parametrize("edge, token", [
    ({}, "-->"),
    ({"head": "none"}, "---"),
    ({"head": "circle"}, "--o"),
    ({"head": "cross", "bidirectional": True}, "x--x"),
    ({"head": "arrow", "bidirectional": True, "length": 2}, "<--->"),
    ({"stroke": "thick", "length": 3}, "====>"),
    ({"stroke": "thick", "head": "none"}, "==="),
    ({"stroke": "dotted", "length": 2}, "-..->"),
    ({"stroke": "dotted", "head": "none"}, "-.-"),
    ({"stroke": "invisible"}, "~~~"),
])
def test_fc_link_tokens(edge: dict, token: str) -> None:
    assert f"    A {token} B\n" in render.render(_fc_doc(edges=[{"from": "A", "to": "B", **edge}]))


@pytest.mark.parametrize("edge, text", [
    ({"label": "t"}, 'A -->|"t"| B'),
    ({"label": "t", "labelForm": "inline"}, 'A -- "t" --> B'),
    ({"label": "t", "labelForm": "inline", "head": "none"}, 'A -- "t" --- B'),
    ({"label": "t", "labelForm": "inline", "stroke": "dotted", "length": 2}, 'A -. "t" ..-> B'),
    ({"label": "t", "labelForm": "inline", "stroke": "thick", "bidirectional": True}, 'A <== "t" ==> B'),
    ({"label": "**b**", "labelType": "markdown"}, 'A -->|"`**b**`"| B'),
])
def test_fc_link_text_forms(edge: dict, text: str) -> None:
    assert f"    {text}\n" in render.render(_fc_doc(edges=[{"from": "A", "to": "B", **edge}]))


def test_fc_labels_are_entity_encoded_not_rewritten() -> None:
    source = render.render(_fc_doc(nodes=[{"id": "A", "label": 'say "hi" <b>x</b> #1 fa:fa-car'}, {"id": "B"}]))
    assert 'A["say #quot;hi#quot; #lt;b#gt;x#lt;/b#gt; #35;1 fa#58;fa-car"]' in source


def test_fc_font_awesome_icon_is_explicit() -> None:
    ir = _fc_doc(nodes=[{"id": "A", "form": "round", "faIcon": {"prefix": "fab", "name": "github"}, "label": "Code"},
                    {"id": "B"}])
    assert 'A("fab:fa-github Code")' in render.render(ir)
    ir["nodes"][0]["form"] = None
    del ir["nodes"][0]["form"]
    assert _fc_error_path(ir) == "/nodes/0/faIcon"


@pytest.mark.parametrize("node_id", ["end", "graph", "style", "class", "click", "subgraph", "default", "1a", "a-b", "a b"])
def test_fc_unsafe_node_ids_are_rejected(node_id: str) -> None:
    assert _fc_error_path(_fc_doc(nodes=[{"id": node_id}], edges=[])) == "/nodes/0/id"


def test_fc_end_variants_are_valid_ids() -> None:
    assert "    End\n" in render.render(_fc_doc(nodes=[{"id": "End"}], edges=[]))


def test_fc_undeclared_edge_target_is_rejected() -> None:
    assert _fc_error_path(_fc_doc(edges=[{"from": "A", "to": "Z"}])) == "/edges/0/to"
    assert _fc_error_path(_fc_doc(edges=[{"from": ["A", "Z"], "to": "B"}])) == "/edges/0/from/1"
    assert _fc_error_path(_fc_doc(edges=[{"from": "A", "to": "B", "then": [{"to": "Z"}]}])) == "/edges/0/then/0/to"


@pytest.mark.parametrize("direction", ["DIAGONAL", "td", "UP"])
def test_fc_unknown_direction_is_rejected(direction: str) -> None:
    assert _fc_error_path(_fc_doc(direction=direction)) == "/direction"


def test_fc_subgraph_direction_has_no_td() -> None:
    ir = _fc_doc(subgraphs=[{"id": "S", "direction": "TD"}])
    ir["nodes"][0]["group"] = "S"
    assert _fc_error_path(ir) == "/subgraphs/0/direction"


def test_fc_ids_share_one_namespace() -> None:
    assert _fc_error_path(_fc_doc(nodes=[{"id": "A"}, {"id": "A"}], edges=[])) == "/nodes/1/id"
    assert _fc_error_path(_fc_doc(subgraphs=[{"id": "A"}])) == "/nodes/0/id"
    assert _fc_error_path(_fc_doc(edges=[{"from": "A", "to": "B", "id": "B"}])) == "/edges/0/id"


def test_fc_node_group_must_be_a_declared_subgraph() -> None:
    ir = _fc_doc()
    ir["nodes"][0]["group"] = "nowhere"
    assert _fc_error_path(ir) == "/nodes/0/group"


def test_fc_nested_subgraphs_render_in_place() -> None:
    ir = _fc_doc(subgraphs=[{"id": "Outer", "label": "Outer", "subgraphs": [{"id": "Inner", "direction": "LR"}]}])
    ir["nodes"][1]["group"] = "Inner"
    source = render.render(ir)
    assert '    subgraph Outer ["Outer"]\n        subgraph Inner\n            direction LR\n            B\n        end\n    end\n' in source


def test_fc_only_one_node_look() -> None:
    ir = _fc_doc(nodes=[{"id": "A", "form": "round", "shape": "rect", "label": "x"}, {"id": "B"}])
    assert _fc_error_path(ir) == "/nodes/0/shape"


def test_fc_classic_form_needs_a_label() -> None:
    assert _fc_error_path(_fc_doc(nodes=[{"id": "A", "form": "round"}, {"id": "B"}])) == "/nodes/0/label"


def test_fc_markdown_needs_a_classic_form() -> None:
    ir = _fc_doc(nodes=[{"id": "A", "shape": "rect", "label": "**x**", "labelType": "markdown"}, {"id": "B"}])
    assert _fc_error_path(ir) == "/nodes/0/labelType"


def test_fc_edge_metadata_needs_an_id_and_ids_need_single_endpoints() -> None:
    assert _fc_error_path(_fc_doc(edges=[{"from": "A", "to": "B", "curve": "linear"}])) == "/edges/0/curve"
    assert _fc_error_path(_fc_doc(edges=[{"from": ["A", "B"], "to": "B", "id": "e1"}])) == "/edges/0/id"
    source = render.render(_fc_doc(edges=[{"from": "A", "to": "B", "id": "e1", "animate": True, "curve": "linear"}]))
    assert "    A e1@--> B\n" in source and "    e1@{ animate: true, curve: linear }\n" in source


def test_fc_invisible_and_bidirectional_rules() -> None:
    assert _fc_error_path(_fc_doc(edges=[{"from": "A", "to": "B", "stroke": "invisible", "label": "x"}])) == "/edges/0/label"
    assert _fc_error_path(_fc_doc(edges=[{"from": "A", "to": "B", "head": "none", "bidirectional": True}])) == "/edges/0/bidirectional"
    assert _fc_error_path(_fc_doc(edges=[{"from": "A", "to": "B", "kind": "normal", "stroke": "thick"}])) == "/edges/0/stroke"


def test_fc_link_style_indexes_count_ampersand_links() -> None:
    edges = [{"from": ["A", "B"], "to": ["A", "B"]}]
    assert "linkStyle 3 color:red" in render.render(_fc_doc(edges=edges, linkStyles=[{"links": [3], "style": {"color": "red"}}]))
    assert _fc_error_path(_fc_doc(edges=edges, linkStyles=[{"links": [4], "style": {"color": "red"}}])) == "/linkStyles/0/links/0"


@pytest.mark.parametrize("style, key", [
    ({"fill": "rgb(255, 0, 0)"}, "fill"),
    ({"fill": "#ff"}, "fill"),
    ({"strokeWidth": "4"}, None),
    ({"strokeWidth": "4 px"}, "strokeWidth"),
    ({"strokeDasharray": "5,5"}, "strokeDasharray"),
    ({"fontWeight": "heavy"}, "fontWeight"),
    ({"stroke": "#333;color:red"}, "stroke"),
])
def test_fc_typed_styles(style: dict, key: str | None) -> None:
    ir = _fc_doc(styles=[{"id": "A", "style": style}])
    if key is None:
        render.render(ir)
    else:
        assert _fc_error_path(ir) == f"/styles/0/style/{key}"


def test_fc_raw_style_strings_are_rejected() -> None:
    assert _fc_error_path(_fc_doc(styles=[{"id": "A", "style": "fill:#f9f"}])) == "/styles/0/style"


def test_fc_class_references_must_be_declared() -> None:
    defs = [{"names": ["hot"], "style": {"fill": "#f00"}}]
    ir = _fc_doc(classDefs=defs, classes=[{"ids": ["A"], "class": "cold"}])
    assert _fc_error_path(ir) == "/classes/0/class"
    ir = _fc_doc(classDefs=[{"names": ["default"], "style": {"fill": "#f00"}}])
    ir["nodes"][0]["class"] = "default"
    assert _fc_error_path(ir) == "/nodes/0/class"


def test_fc_tooltip_rules() -> None:
    clicks = [{"id": "A", "action": "href", "url": "https://example.com", "tooltip": "a --> b"}]
    assert _fc_error_path(_fc_doc(clicks=clicks)) == "/clicks/0/tooltip"
    clicks[0]["tooltip"] = "<b>x</b>"
    assert _fc_error_path(_fc_doc(clicks=clicks)) == "/clicks/0/tooltip"
    clicks[0]["tooltip"] = 'say "hi"'
    assert 'click A href "https://example.com" "say #quot;hi#quot;"' in render.render(_fc_doc(clicks=clicks))


def test_fc_click_url_and_action_rules() -> None:
    assert _fc_error_path(_fc_doc(clicks=[{"id": "A", "action": "url", "url": "javascript:alert(1)"}])) == "/clicks/0/url"
    assert _fc_error_path(_fc_doc(clicks=[{"id": "A", "action": "call", "function": "f", "target": "_blank"}])) == "/clicks/0/target"
    two = [{"id": "A", "action": "callback", "function": "f"}, {"id": "A", "action": "callback", "function": "g"}]
    assert _fc_error_path(_fc_doc(clicks=two)) == "/clicks/1/id"


def test_fc_html_labels_config_is_not_offered() -> None:
    # With htmlLabels off, entity codes are drawn literally, so the builder cannot carry text safely.
    assert _fc_error_path(_fc_doc(config={"flowchart": {"htmlLabels": False}})) == "/config/flowchart/htmlLabels"


@pytest.mark.parametrize("keyword", ["flowchart", "graph", "flowchart-elk"])
def test_fc_keyword_is_emitted_unchanged(keyword: str) -> None:
    assert render.render(_fc_doc(target=keyword, direction="LR")).startswith(f"{keyword} LR\n")


def test_fc_semicolons_end_node_and_edge_statements() -> None:
    source = render.render(_fc_doc(semicolons=True))
    assert "    A;\n    B;\n    A --> B;\n" in source



# === sequenceDiagram ===========================================================================


def _seq_doc(steps: list, actors: list | None = None, **extra) -> dict:
    return {
        "diagram": "sequence",
        "target": "sequenceDiagram",
        "actors": actors if actors is not None else [{"id": "User"}, {"id": "API"}, {"id": "DB", "kind": "actor"}],
        "steps": steps,
        **extra,
    }


def _seq_msg(src: str, dst: str, label: str = "x", **extra) -> dict:
    return {"type": "message", "from": src, "to": dst, "label": label, **extra}


def _seq_rejects(ir: dict, path: str, fragment: str = "") -> render.IRError:
    with pytest.raises(render.IRError) as info:
        render.render(ir)
    assert info.value.path == path, str(info.value)
    assert info.value.target == "sequenceDiagram"
    assert fragment in info.value.reason, info.value.reason
    return info.value


# --- ported legacy behaviour -------------------------------------------------------------------


def test_seq_message_exchange_renders() -> None:
    source = render.render(_seq_doc([
        _seq_msg("User", "API", "request", arrow="sync"),
        _seq_msg("API", "DB", "query"),
        _seq_msg("DB", "API", "result", arrow="reply"),
    ]))
    assert source.startswith("sequenceDiagram\n")
    assert "    participant User\n" in source
    assert "    actor DB\n" in source
    assert "User->>API: request" in source
    assert "DB-->>API: result" in source


def test_seq_activation_notes_and_control_blocks_render() -> None:
    source = render.render(_seq_doc([
        {"type": "activate", "actor": "API"},
        {"type": "loop", "label": "Every retry", "steps": [_seq_msg("User", "API", "ping", arrow="async")]},
        {"type": "alt", "branches": [
            {"label": "success", "steps": [_seq_msg("API", "User", "ok", arrow="reply")]},
            {"label": "failure", "steps": [_seq_msg("API", "User", "error", arrow="cross")]},
        ]},
        {"type": "note", "position": "right_of", "actors": ["API"], "text": "done"},
        {"type": "deactivate", "actor": "API"},
    ]))
    for line in ("activate API", "loop Every retry", "User-)API: ping", "alt success", "else failure",
                 "API-xUser: error", "Note right of API: done", "deactivate API"):
        assert line in source


def test_seq_par_rect_and_critical_blocks_render() -> None:
    source = render.render(_seq_doc([
        {"type": "rect", "color": "rgb(200, 150, 255)", "steps": [
            {"type": "par", "branches": [
                {"label": "warm cache", "steps": [_seq_msg("User", "API", "warm")]},
                {"label": "log start", "steps": [_seq_msg("User", "DB", "log")]},
            ]},
        ]},
        {"type": "critical", "branches": [
            {"label": "connect to DB", "steps": [_seq_msg("API", "DB", "connect")]},
            {"label": "network timeout", "steps": [_seq_msg("API", "API", "log error")]},
        ]},
    ]))
    for line in ("rect rgb(200, 150, 255)", "par warm cache", "and log start",
                 "critical connect to DB", "option network timeout"):
        assert line in source
    assert [line.strip() for line in source.splitlines()].count("end") == 3


def test_seq_undeclared_actor_is_rejected() -> None:
    _seq_rejects(_seq_doc([_seq_msg("User", "Ghost")]), "/steps/0/to", "undeclared")


def test_seq_unknown_step_type_is_rejected() -> None:
    _seq_rejects(_seq_doc([{"type": "teleport", "actor": "User"}]), "/steps/0/type", "unknown value")


# --- references and ids ------------------------------------------------------------------------


def test_seq_reference_inside_nested_block_is_checked() -> None:
    ir = _seq_doc([{"type": "par", "branches": [{"steps": [{"type": "opt", "steps": [_seq_msg("User", "Nobody")]}]}]}])
    _seq_rejects(ir, "/steps/0/branches/0/steps/0/steps/0/to", "undeclared")


def test_seq_duplicate_participant_id_is_rejected() -> None:
    _seq_rejects(_seq_doc([], actors=[{"id": "A"}, {"kind": "box", "actors": [{"id": "A"}]}]), "/actors/1/actors/0/id", "duplicate")


@pytest.mark.parametrize("word", ["end", "End", "loop", "participant", "note", "box", "autonumber"])
def test_seq_keyword_ids_are_rejected(word: str) -> None:
    _seq_rejects(_seq_doc([], actors=[{"id": word}]), "/actors/0/id", "keyword")


def test_seq_implicit_participant_is_referenced_but_not_declared() -> None:
    source = render.render(_seq_doc([_seq_msg("Late", "User", "hi")], actors=[{"id": "User"}, {"id": "Late", "implicit": True}]))
    assert "participant Late" not in source
    assert "Late->>User: hi" in source


def test_seq_implicit_participant_takes_no_declaration_keys() -> None:
    _seq_rejects(_seq_doc([], actors=[{"id": "Late", "implicit": True, "alias": "x"}]), "/actors/0/alias", "implicit")


# --- lifecycle --------------------------------------------------------------------------------


def test_seq_create_must_be_followed_by_a_message_to_it() -> None:
    created = {"type": "create", "participant": {"id": "Carl"}}
    _seq_rejects(_seq_doc([created, _seq_msg("Carl", "User")]), "/steps/0", "followed directly by a message to")
    _seq_rejects(_seq_doc([created]), "/steps/0", "followed directly")
    source = render.render(_seq_doc([created, _seq_msg("User", "Carl")]))
    assert "create participant Carl\n    User->>Carl: x" in source


def test_seq_create_of_a_declared_participant_is_rejected() -> None:
    _seq_rejects(_seq_doc([{"type": "create", "participant": {"id": "User"}}, _seq_msg("API", "User")]), "/steps/0/participant/id", "duplicate")


def test_seq_created_participant_is_unknown_before_creation() -> None:
    ir = _seq_doc([_seq_msg("User", "Carl"), {"type": "create", "participant": {"id": "Carl"}}, _seq_msg("User", "Carl")])
    _seq_rejects(ir, "/steps/0/to", "undeclared")


def test_seq_destroy_must_be_followed_by_a_message_involving_it() -> None:
    _seq_rejects(_seq_doc([{"type": "destroy", "actor": "API"}, _seq_msg("User", "DB")]), "/steps/0", "followed directly")
    source = render.render(_seq_doc([{"type": "destroy", "actor": "API"}, _seq_msg("API", "User")]))
    assert "destroy API\n    API->>User: x" in source


def test_seq_destroy_twice_is_rejected() -> None:
    ir = _seq_doc([{"type": "destroy", "actor": "API"}, _seq_msg("API", "User"), {"type": "destroy", "actor": "API"}, _seq_msg("User", "API")])
    _seq_rejects(ir, "/steps/2/actor", "already destroyed")


# --- activation -------------------------------------------------------------------------------


def test_seq_deactivating_an_inactive_participant_is_rejected() -> None:
    _seq_rejects(_seq_doc([{"type": "deactivate", "actor": "API"}]), "/steps/0/actor", "not active")
    _seq_rejects(_seq_doc([_seq_msg("API", "User", activation="deactivate")]), "/steps/0/activation", "not active")


def test_seq_unclosed_activation_is_rejected() -> None:
    _seq_rejects(_seq_doc([_seq_msg("User", "API", activation="activate")]), "/steps/0/activation", "never closed")
    _seq_rejects(_seq_doc([{"type": "activate", "actor": "API"}]), "/steps/0", "never closed")


def test_seq_stacked_shorthand_activations_balance() -> None:
    source = render.render(_seq_doc([
        _seq_msg("User", "API", "1", activation="activate"),
        _seq_msg("User", "API", "2", activation="activate"),
        _seq_msg("API", "User", "2", arrow="dotted", activation="deactivate"),
        _seq_msg("API", "User", "1", arrow="dotted", activation="deactivate"),
    ]))
    assert source.count("User->>+API") == 2
    assert source.count("API-->>-User") == 2


def test_seq_reverse_solid_arrow_with_deactivation_is_spaced() -> None:
    source = render.render(_seq_doc([
        _seq_msg("User", "API", activation="activate"),
        _seq_msg("API", "User", arrow="half-solid-reverse-top", activation="deactivate"),
    ]))
    assert "API/|- -User: x" in source


def test_seq_deactivation_before_an_x_id_is_rejected() -> None:
    ir = _seq_doc([_seq_msg("A", "xray", activation="activate"), _seq_msg("xray", "A"), _seq_msg("A", "xray", activation="activate"),
              _seq_msg("xray", "A", activation="deactivate"), _seq_msg("xray", "xray", activation="deactivate")],
             actors=[{"id": "A"}, {"id": "xray"}])
    _seq_rejects(ir, "/steps/4/to", "cross arrow")


def test_seq_activation_and_central_do_not_combine() -> None:
    _seq_rejects(_seq_doc([_seq_msg("User", "API", activation="activate", central="target")]), "/steps/0/central", "do not combine")


def test_seq_central_connections_render() -> None:
    source = render.render(_seq_doc([_seq_msg("User", "API", central="source"), _seq_msg("User", "API", central="both")]))
    assert "User()->>API: x" in source
    assert "User()->>()API: x" in source


# --- notes, boxes, colors, menus --------------------------------------------------------------


def test_seq_side_note_takes_one_participant() -> None:
    _seq_rejects(_seq_doc([{"type": "note", "position": "left_of", "actors": ["User", "API"], "text": "t"}]), "/steps/0/actors", "at most 1")
    source = render.render(_seq_doc([{"type": "note", "position": "over", "actors": ["User", "API"], "text": "t"}]))
    assert "Note over User,API: t" in source


def test_seq_hex_colors_are_rejected() -> None:
    _seq_rejects(_seq_doc([{"type": "rect", "color": "#ff0000", "steps": []}]), "/steps/0/color", "hex")
    _seq_rejects(_seq_doc([], actors=[{"kind": "box", "color": "#f00", "actors": [{"id": "A"}]}]), "/actors/0/color", "hex")


def test_seq_unknown_color_name_is_rejected() -> None:
    _seq_rejects(_seq_doc([], actors=[{"kind": "box", "color": "notacolor", "actors": [{"id": "A"}]}]), "/actors/0/color")


def test_seq_box_without_color_is_transparent_so_the_label_is_kept() -> None:
    source = render.render(_seq_doc([], actors=[{"kind": "box", "label": "Red team", "actors": [{"id": "A"}]}]))
    assert "    box transparent Red team\n        participant A\n    end\n" in source


def test_seq_parenthesis_after_function_color_is_rejected() -> None:
    ir = _seq_doc([], actors=[{"kind": "box", "color": "rgb(1,2,3)", "label": "Order (paid)", "actors": [{"id": "A"}]}])
    _seq_rejects(ir, "/actors/0/label", "part of the color")


def test_seq_boxes_do_not_nest() -> None:
    ir = _seq_doc([], actors=[{"kind": "box", "actors": [{"kind": "box", "actors": [{"id": "A"}]}]}])
    _seq_rejects(ir, "/actors/0/actors/0/kind", "nested")


def test_seq_menu_on_actor_is_rejected() -> None:
    menu = {"form": "link", "items": [{"label": "Docs", "url": "https://example.com"}]}
    _seq_rejects(_seq_doc([], actors=[{"id": "U", "kind": "actor", "menu": menu}]), "/actors/0/menu", "actor")


def test_seq_menu_url_must_be_http() -> None:
    menu = {"form": "links", "items": [{"label": "Docs", "url": "javascript:alert(1)"}]}
    _seq_rejects(_seq_doc([], actors=[{"id": "P", "menu": menu}]), "/actors/0/menu/items/0/url", "URL")


def test_seq_symbol_type_needs_participant_kind() -> None:
    _seq_rejects(_seq_doc([], actors=[{"id": "U", "kind": "actor", "type": "database"}]), "/actors/0/type", "participant")


# --- text -------------------------------------------------------------------------------------


def test_seq_message_text_is_entity_encoded() -> None:
    source = render.render(_seq_doc([_seq_msg("User", "API", 'wrap: a; "b" #1 <i>')]))
    assert "User->>API: wrap#58; a#59; #quot;b#quot; #35;1 #lt;i#gt;" in source


def test_seq_message_newline_becomes_line_break() -> None:
    assert "User->>API: one<br/>two" in render.render(_seq_doc([_seq_msg("User", "API", "one\ntwo")]))


@pytest.mark.parametrize("label", ["a#b", "a;b", "<b>x</b>", "wrap: on", "$$x$$"])
def test_seq_block_label_rejects_what_it_cannot_carry(label: str) -> None:
    _seq_rejects(_seq_doc([{"type": "loop", "label": label, "steps": []}]), "/steps/0/label")


def test_seq_end_word_in_text_is_fine() -> None:
    source = render.render(_seq_doc([{"type": "note", "position": "over", "actors": ["User"], "text": "end"}]))
    assert "Note over User: end" in source


# --- autonumber -------------------------------------------------------------------------------


def test_seq_autonumber_forms() -> None:
    assert "    autonumber\n" in render.render(_seq_doc([], autonumber=True))
    assert "    autonumber 10 5\n" in render.render(_seq_doc([], autonumber={"start": 10, "increment": 5}))
    assert "    autonumber 1.5\n" in render.render(_seq_doc([], autonumber={"start": 1.5}))


def test_seq_autonumber_rejects_what_the_lexer_cannot_read() -> None:
    _seq_rejects(_seq_doc([], autonumber={"start": 1.125}), "/autonumber/start", "2 decimals")
    _seq_rejects(_seq_doc([], autonumber={"start": 1, "increment": 0}), "/autonumber/increment")
    _seq_rejects(_seq_doc([], autonumber={"increment": 2}), "/autonumber/start", "missing")



# === classDiagram ==============================================================================


_cls_MAXIMAL = json.loads((SKILL_DIR / "tests" / "fixtures" / "classDiagram" / "maximal.json").read_text())


def _cls_doc(**extra) -> dict:
    base = {"diagram": "graph", "target": "classDiagram", "nodes": [{"id": "A"}, {"id": "B"}]}
    base.update(extra)
    return base


def _cls_error_path(ir: dict) -> str:
    with pytest.raises(IRError) as info:
        render.render(ir)
    assert info.value.target == "classDiagram"
    assert info.value.reason
    return info.value.path


def test_cls_members_annotations_and_relations_render() -> None:
    source = render.render(_cls_doc(
        nodes=[
            {"id": "Animal", "members": [
                {"kind": "attribute", "visibility": "public", "type": "int", "name": "age"},
                {"kind": "method", "visibility": "public", "name": "isMammal", "return_type": "bool"},
            ]},
            {"id": "Duck", "annotation": {"name": "interface"}, "members": [
                {"kind": "method", "visibility": "public", "name": "swim",
                 "parameters": [{"name": "speed", "type": "int"}], "classifier": "abstract"},
            ]},
            {"id": "Customer"},
            {"id": "Ticket"},
        ],
        edges=[
            {"from": "Animal", "to": "Duck", "kind": "inheritance", "label": "implements"},
            {"from": "Customer", "to": "Ticket", "kind": "association", "from_card": "1", "to_card": "*"},
        ],
    ))
    assert "    class Duck {\n        <<interface>>\n        +swim(int speed)*\n    }" in source
    assert "        +isMammal() bool" in source
    assert "    Animal <|-- Duck : implements" in source
    assert '    Customer "1" --> "*" Ticket' in source


def test_cls_relation_ends_pick_the_arrow_side() -> None:
    edges = [
        {"from": "A", "to": "B", "kind": "inheritance"},
        {"from": "A", "to": "B", "kind": "inheritance", "ends": "to"},
        {"from": "A", "to": "B", "kind": "dependency", "ends": "both"},
        {"from": "A", "to": "B", "kind": "lollipop", "ends": "to"},
    ]
    source = render.render(_cls_doc(edges=edges))
    assert ["A <|-- B", "A --|> B", "A <..> B", "A --() B"] == [line.strip() for line in source.splitlines()[3:]]


def test_cls_generic_types_nest_and_text_is_encoded() -> None:
    source = render.render(_cls_doc(nodes=[{"id": "A", "generic": ["K", "V"], "members": [
        {"kind": "method", "name": "grid", "return_type": {"name": "List", "args": [{"name": "List", "args": ["int"]}]}},
        {"kind": "attribute", "name": "x$", "type": "a~b"},
    ]}]))
    assert "class A~K, V~ {" in source
    assert "grid() List~List~int~~" in source
    assert "a#126;b x#36;" in source


def test_cls_colon_members_and_separate_annotations_stay_outside_namespaces() -> None:
    source = render.render(_cls_doc(
        nodes=[{"id": "A", "member_syntax": "colon", "members": [{"kind": "attribute", "name": "x"}],
                "annotation": {"name": "service", "placement": "separate"}}, {"id": "B"}],
        namespaces=[{"id": "N", "classes": ["A"]}],
    ))
    assert "    namespace N {\n        class A\n    }" in source
    assert "    A : x" in source
    assert "    <<service>> A" in source


def test_cls_render_is_deterministic() -> None:
    assert render.render(copy.deepcopy(_cls_MAXIMAL)) == render.render(copy.deepcopy(_cls_MAXIMAL))


@pytest.mark.parametrize("ir, path", [
    (_cls_doc(edges=[{"from": "A", "to": "B", "kind": "orbits"}]), "/edges/0/kind"),
    (_cls_doc(nodes=[{"id": "A", "annotation": {"name": "widget"}}]), "/nodes/0/annotation/name"),
    (_cls_doc(edges=[{"from": "A", "to": "Z", "kind": "link"}]), "/edges/0/to"),
    (_cls_doc(nodes=[{"id": "A"}, {"id": "A"}]), "/nodes/1/id"),
    (_cls_doc(nodes=[{"id": "A", "members": ["+int age"]}]), "/nodes/0/members/0"),
    (_cls_doc(nodes=[{"id": "A", "members": [{"kind": "attribute", "name": "x", "parameters": []}]}]),
     "/nodes/0/members/0/parameters"),
    (_cls_doc(nodes=[{"id": "A", "style": "fill:#f9f"}]), "/nodes/0/style"),
    (_cls_doc(edges=[{"from": "A", "to": "B", "kind": "link", "ends": "to"}]), "/edges/0/ends"),
    (_cls_doc(edges=[{"from": "A", "to": "B", "kind": "association", "to_card": "many"}]), "/edges/0/to_card"),
])
def test_cls_unrepresentable_values_are_refused(ir: dict, path: str) -> None:
    assert _cls_error_path(ir) == path


def test_cls_implicit_class_needs_a_relation() -> None:
    assert _cls_error_path(_cls_doc(nodes=[{"id": "A", "implicit": True}])) == "/nodes/0/implicit"


def test_cls_implicit_class_cannot_be_declared_in_a_namespace() -> None:
    ir = _cls_doc(nodes=[{"id": "A", "implicit": True}, {"id": "B"}],
             edges=[{"from": "A", "to": "B", "kind": "link"}], namespaces=[{"id": "N", "classes": ["A"]}])
    assert _cls_error_path(ir) == "/namespaces/0/classes/0"


def test_cls_implicit_class_rejects_declaration_only_keys() -> None:
    ir = _cls_doc(nodes=[{"id": "A", "implicit": True, "label": "x"}, {"id": "B"}],
             edges=[{"from": "A", "to": "B", "kind": "link"}])
    assert _cls_error_path(ir) == "/nodes/0/label"


def test_cls_namespace_rules() -> None:
    assert _cls_error_path(_cls_doc(namespaces=[{"id": "N"}])) == "/namespaces/0"
    assert _cls_error_path(_cls_doc(namespaces=[{"id": "A", "classes": ["B"]}])) == "/namespaces/0/id"
    two = _cls_doc(namespaces=[{"id": "N", "classes": ["A"]}, {"id": "M", "classes": ["A"]}])
    assert _cls_error_path(two) == "/namespaces/1/classes/0"
    nested = _cls_doc(namespaces=[{"id": "N", "namespaces": [{"id": "N", "classes": ["A"]}]}])
    assert _cls_error_path(nested) == "/namespaces/0/namespaces/0/id"


def test_cls_combinations_that_do_not_parse_are_refused() -> None:
    inline = _cls_doc(nodes=[{"id": "A", "class": "c", "annotation": {"name": "interface", "placement": "inline"}}],
                 class_defs=[{"names": ["c"], "style": {"fill": "#f96"}}])
    assert _cls_error_path(inline) == "/nodes/0/annotation/placement"
    styled = _cls_doc(nodes=[{"id": "A B", "backtick": True, "style": {"fill": "#f96"}}])
    assert _cls_error_path(styled) == "/nodes/0/style"


@pytest.mark.parametrize("name", ["note", "click", "o", "_blank", "classDef"])
def test_cls_keywords_are_not_names(name: str) -> None:
    assert _cls_error_path(_cls_doc(nodes=[{"id": name}])) == "/nodes/0/id"


def test_cls_backtick_names_are_limited_to_safe_characters() -> None:
    assert "class `Animal Class`" in render.render(_cls_doc(nodes=[{"id": "Animal Class", "backtick": True}]))
    assert _cls_error_path(_cls_doc(nodes=[{"id": "Animal Class!", "backtick": True}])) == "/nodes/0/id"
    assert _cls_error_path(_cls_doc(nodes=[{"id": "Animal Class"}])) == "/nodes/0/id"


def test_cls_multi_argument_generic_only_at_the_outermost_level() -> None:
    nested = {"name": "Set", "args": [{"name": "Map", "args": ["K", "V"]}]}
    ir = _cls_doc(nodes=[{"id": "A", "members": [{"kind": "attribute", "name": "x", "type": nested}]}])
    assert _cls_error_path(ir) == "/nodes/0/members/0/type/args/0/args"


def test_cls_style_and_class_references() -> None:
    styles = [{"names": ["c"], "style": {"fill": "#f96"}}]
    assert _cls_error_path(_cls_doc(nodes=[{"id": "A", "class": "d"}], class_defs=styles)) == "/nodes/0/class"
    default = [{"names": ["default"], "style": {"fill": "#f96"}}]
    assert _cls_error_path(_cls_doc(nodes=[{"id": "A", "class": "default"}], class_defs=default)) == "/nodes/0/class"
    comma = [{"names": ["c"], "style": {"fill": "rgb(1,2,3)"}}]
    assert _cls_error_path(_cls_doc(class_defs=comma)) == "/class_defs/0/style/fill"
    assert _cls_error_path(_cls_doc(class_defs=[{"names": ["c"], "style": {}}])) == "/class_defs/0/style"
    dup = _cls_doc(class_defs=styles + styles)
    assert _cls_error_path(dup) == "/class_defs/1/names/0"


def test_cls_interaction_rules() -> None:
    bad_url = _cls_doc(interactions=[{"node": "A", "action": "href", "url": "javascript:alert(1)"}])
    assert _cls_error_path(bad_url) == "/interactions/0/url"
    markup = _cls_doc(interactions=[{"node": "A", "action": "call", "function": "f", "tooltip": "<b>x</b>"}])
    assert _cls_error_path(markup) == "/interactions/0/tooltip"
    twice = _cls_doc(interactions=[{"node": "A", "action": "call", "function": "f"},
                              {"node": "A", "action": "link", "url": "https://example.com"}])
    assert _cls_error_path(twice) == "/interactions/1/node"
    missing = _cls_doc(interactions=[{"node": "A", "action": "href"}])
    assert _cls_error_path(missing) == "/interactions/0/url"


def test_cls_note_newline_becomes_a_line_break() -> None:
    source = render.render(_cls_doc(notes=[{"for": "A", "text": "line1\nline2"}]))
    assert '    note for A "line1<br>line2"' in source



# === stateDiagram ==============================================================================


def _st_doc(**body) -> dict:
    return {"diagram": "state-machine", "target": "stateDiagram-v2", **body}


def _st_error_path(ir: dict) -> str:
    with pytest.raises(IRError) as info:
        render.render(ir)
    return info.value.path


_st_LIFECYCLE = _st_doc(
    states=[{"id": "Draft"}, {"id": "Approved"}, {"id": "Rejected"}],
    initial="Draft",
    final=["Rejected"],
    transitions=[
        {"from": "Draft", "to": "Approved", "label": "user approves"},
        {"from": "Draft", "to": "Rejected", "label": "user rejects"},
    ],
)

_st_COMPOSITE = _st_doc(
    direction="LR",
    initial="Outer",
    states=[
        {"id": "Outer", "states": [{"id": "Inner"}], "initial": "Inner", "final": ["Inner"], "transitions": []},
        {"id": "choice1", "kind": "choice"},
        {"id": "Done"},
        {"id": "Failed"},
    ],
    transitions=[
        {"from": "Outer", "to": "choice1"},
        {"from": "choice1", "to": "Done", "label": "ok"},
        {"from": "choice1", "to": "Failed", "label": "bad"},
    ],
    notes=[{"state": "Outer", "side": "right", "text": "entry point"}],
)


def test_st_lifecycle_emits_start_and_end() -> None:
    source = render.render(_st_LIFECYCLE)
    assert "[*] --> Draft" in source
    assert "Rejected --> [*]" in source
    assert "Draft --> Approved : user approves" in source


def test_st_composite_choice_and_note() -> None:
    source = render.render(_st_COMPOSITE)
    assert "direction LR" in source
    assert "state Outer {" in source
    assert "state choice1 <<choice>>" in source
    # A note on a state not declared yet crashes the renderer, so notes come after the states.
    assert source.index("note right of Outer : entry point") > source.index("state Outer {")


def test_st_legacy_keyword_is_emitted_unchanged() -> None:
    ir = copy.deepcopy(_st_LIFECYCLE)
    ir["target"] = "stateDiagram"
    assert render.render(ir).splitlines()[0] == "stateDiagram"


@pytest.mark.parametrize("state", [
    {"id": "s1", "kind": "wat"},
    {"id": "Outer", "kind": "wat", "states": [{"id": "Inner"}]},
])
def test_st_unknown_kind_is_rejected(state: dict) -> None:
    assert _st_error_path(_st_doc(states=[state])) == "/states/0/kind"


def test_st_pseudostate_with_nested_body_is_rejected() -> None:
    assert _st_error_path(_st_doc(states=[{"id": "gate", "kind": "choice", "states": [{"id": "Inner"}]}])) == "/states/0/states"


def test_st_pseudostate_takes_no_label() -> None:
    assert _st_error_path(_st_doc(states=[{"id": "gate", "kind": "fork", "label": "x"}])) == "/states/0/label"


def test_st_duplicate_id_across_nesting_is_rejected() -> None:
    ir = _st_doc(states=[{"id": "A", "states": [{"id": "B"}]}, {"id": "B"}])
    assert _st_error_path(ir) == "/states/1/id"


def test_st_transitions_only_reach_sibling_states() -> None:
    ir = _st_doc(states=[{"id": "A", "states": [{"id": "B"}]}, {"id": "C"}], transitions=[{"from": "C", "to": "B"}])
    assert _st_error_path(ir) == "/transitions/0/to"


def test_st_undeclared_note_target_is_rejected() -> None:
    ir = _st_doc(states=[{"id": "A"}], notes=[{"state": "Ghost", "side": "left", "text": "x"}])
    assert _st_error_path(ir) == "/notes/0/state"


def test_st_note_on_pseudostate_is_rejected() -> None:
    ir = _st_doc(states=[{"id": "c", "kind": "choice"}], notes=[{"state": "c", "side": "left", "text": "x"}])
    assert _st_error_path(ir) == "/notes/0/state"


@pytest.mark.parametrize("state_id", ["note", "State", "classDef", "direction", "default", "my-state", "1a"])
def test_st_keyword_and_unsafe_ids_are_rejected(state_id: str) -> None:
    assert _st_error_path(_st_doc(states=[{"id": state_id}])) == "/states/0/id"


def test_st_end_is_a_valid_id() -> None:
    assert "end --> [*]" in render.render(_st_doc(states=[{"id": "end"}], final=["end"]))


def test_st_direction_td_is_rejected() -> None:
    # `direction TD` is not a state-diagram direction: Mermaid draws states named direction and TD.
    assert _st_error_path(_st_doc(direction="TD", states=[{"id": "A"}])) == "/direction"


@pytest.mark.parametrize("pointer,ir", [
    ("/states/0/label", _st_doc(states=[{"id": "A", "label": "go direction LR now"}])),
    ("/transitions/0/label", _st_doc(states=[{"id": "A"}], transitions=[{"from": "A", "to": "A", "label": "Direction tb"}])),
    ("/transitions/0/comment", _st_doc(states=[{"id": "A"}], transitions=[{"from": "A", "to": "A", "comment": "direction RL"}])),
    ("/comment", _st_doc(comment="direction BT", states=[{"id": "A"}])),
    ("/accessibility/title", _st_doc(accessibility={"title": "direction LR"}, states=[{"id": "A"}])),
])
def test_st_direction_text_hazard_is_rejected(pointer: str, ir: dict) -> None:
    # Any line containing `direction <TB|BT|RL|LR>` lexes as a direction statement.
    assert _st_error_path(ir) == pointer


def test_st_class_line_cannot_spell_a_direction() -> None:
    ir = _st_doc(states=[{"id": "my_direction"}], classDefs=[{"name": "LRx", "style": {"fill": "red"}}],
             classes=[{"class": "LRx", "states": ["my_direction"]}])
    assert _st_error_path(ir) == "/classes/0/class"


def test_st_note_line_cannot_end_the_note() -> None:
    ir = _st_doc(states=[{"id": "A"}], notes=[{"state": "A", "side": "right", "lines": ["ok", "End note here"]}])
    assert _st_error_path(ir) == "/notes/0/lines/1"


def test_st_note_needs_exactly_one_of_text_or_lines() -> None:
    both = _st_doc(states=[{"id": "A"}], notes=[{"state": "A", "side": "right", "text": "x", "lines": ["y"]}])
    neither = _st_doc(states=[{"id": "A"}], notes=[{"state": "A", "side": "right"}])
    assert _st_error_path(both) == "/notes/0/lines"
    assert _st_error_path(neither) == "/notes/0"


def test_st_text_is_entity_encoded_not_rewritten() -> None:
    ir = _st_doc(states=[{"id": "A", "label": 'a;b "q" <b>x</b> #1 50% [[fork]]', "labelForm": "as"}])
    assert 'state "a#59;b #quot;q#quot; #lt;b#gt;x#lt;/b#gt; #35;1 50#37; #91;#91;fork#93;#93;" as A' in render.render(ir)


def test_st_class_shorthand_rules() -> None:
    defs = [{"name": "hot", "style": {"fill": "red"}}]
    nested = _st_doc(classDefs=defs, states=[{"id": "C", "states": [{"id": "a"}, {"id": "b"}],
                                          "transitions": [{"from": "a", "to": "b", "toClass": "hot"}]}])
    on_start = _st_doc(classDefs=defs, states=[{"id": "a"}], transitions=[{"from": "[*]", "to": "a", "fromClass": "hot"}])
    on_pseudo = _st_doc(classDefs=defs, states=[{"id": "a"}, {"id": "c", "kind": "choice"}],
                    transitions=[{"from": "a", "to": "c", "toClass": "hot"}])
    undeclared = _st_doc(classDefs=defs, states=[{"id": "a"}, {"id": "b"}], transitions=[{"from": "a", "to": "b", "toClass": "cold"}])
    assert _st_error_path(nested) == "/states/0/transitions/0/toClass"
    assert _st_error_path(on_start) == "/transitions/0/fromClass"
    assert _st_error_path(on_pseudo) == "/transitions/0/toClass"
    assert _st_error_path(undeclared) == "/transitions/0/toClass"


def test_st_class_and_style_target_simple_states_only() -> None:
    defs = [{"name": "hot", "style": {"fill": "red"}}]
    states = [{"id": "C", "states": [{"id": "inner"}]}]
    assert _st_error_path(_st_doc(classDefs=defs, states=states, classes=[{"class": "hot", "states": ["C"]}])) == "/classes/0/states/0"
    assert _st_error_path(_st_doc(states=states, styles=[{"state": "C", "style": {"fill": "red"}}])) == "/styles/0/state"
    # A class statement does reach a simple state inside a composite (checked in the SVG).
    source = render.render(_st_doc(classDefs=defs, states=states, classes=[{"class": "hot", "states": ["inner"]}]))
    assert "class inner hot" in source


@pytest.mark.parametrize("style,pointer", [
    ({"fill": "rgb(255,0,0)"}, "/classDefs/0/style/fill"),
    ({"fill": "red; x"}, "/classDefs/0/style/fill"),
    ({"strokeWidth": "2px;"}, "/classDefs/0/style/strokeWidth"),
    ({"fontWeight": "heavy"}, "/classDefs/0/style/fontWeight"),
    ({"strokeDasharray": "5,5"}, "/classDefs/0/style/strokeDasharray"),
    ({}, "/classDefs/0/style"),
])
def test_st_typed_style_values(style: dict, pointer: str) -> None:
    assert _st_error_path(_st_doc(classDefs=[{"name": "c", "style": style}], states=[{"id": "A"}])) == pointer


def test_st_regions_rules() -> None:
    one = _st_doc(states=[{"id": "C", "regions": [{"states": [{"id": "a"}]}]}])
    mixed = _st_doc(states=[{"id": "C", "states": [{"id": "x"}], "regions": [{"states": [{"id": "a"}]}, {"states": [{"id": "b"}]}]}])
    assert _st_error_path(one) == "/states/0/regions"
    assert _st_error_path(mixed) == "/states/0/regions"
    two = _st_doc(states=[{"id": "C", "regions": [{"states": [{"id": "a"}]}, {"states": [{"id": "b"}]}]}])
    assert "        a\n        --\n        b\n" in render.render(two)


def test_st_body_keys_need_a_composite() -> None:
    assert _st_error_path(_st_doc(states=[{"id": "A", "direction": "LR"}])) == "/states/0/direction"
    assert _st_error_path(_st_doc(states=[{"id": "A", "states": []}])) == "/states/0/states"


def test_st_start_to_end_is_rejected() -> None:
    assert _st_error_path(_st_doc(states=[{"id": "A"}], transitions=[{"from": "[*]", "to": "[*]"}])) == "/transitions/0/to"


@pytest.mark.skipif(not HAVE_CLI, reason="needs Node and the pinned Mermaid 12.0.0 parser")
@pytest.mark.parametrize("ir", [_st_LIFECYCLE, _st_COMPOSITE], ids=["lifecycle", "composite"])
def test_st_rule_documents_render(ir: dict, tmp_path) -> None:
    path = tmp_path / "d.mmd"
    path.write_text(render.render(ir))
    result = subprocess.run([BASH, str(CHECK), str(path)], capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr



# === entityRelationshipDiagram =================================================================


def _er_base(**extra) -> dict:
    doc = {
        "diagram": "graph",
        "target": "erDiagram",
        "nodes": [{"id": "CUSTOMER"}, {"id": "ORDER"}],
        "edges": [
            {"from": "CUSTOMER", "to": "ORDER", "label": "places", "left": "exactly_one", "right": "zero_or_more"}
        ],
    }
    doc.update(extra)
    return doc


def _er_error_path(doc: dict) -> str:
    with pytest.raises(IRError) as info:
        render.render(doc)
    assert info.value.target == "erDiagram"
    return info.value.path


def test_er_entities_attributes_alias_and_cardinality_render() -> None:
    doc = _er_base(
        direction="LR",
        nodes=[
            {"id": "CUSTOMER", "attributes": [
                {"type": "string", "name": "name", "keys": ["PK"]},
                {"type": "string", "name": "sector"},
            ]},
            {"id": "ORDER", "attributes": [
                {"type": "int", "name": "orderNumber", "keys": ["PK"], "comment": "the order number"},
            ]},
            {"id": "p", "label": "Customer Account"},
        ],
        edges=[
            {"from": "CUSTOMER", "to": "ORDER", "label": "places", "left": "exactly_one", "right": "zero_or_more"},
            {"from": "CUSTOMER", "to": "p", "label": "links", "left": "zero_or_more", "right": "zero_or_more",
             "identifying": False},
        ],
    )
    source = render.render(doc)
    assert source.startswith("erDiagram\n")
    assert "    direction LR\n" in source
    assert '    p["Customer Account"]\n' in source
    assert "    CUSTOMER ||--o{ ORDER : places\n" in source
    assert "    CUSTOMER }o..o{ p : links\n" in source
    assert "        string name PK\n" in source
    assert '        int orderNumber PK "the order number"\n' in source


def test_er_attribute_type_parts_keys_and_comment_encoding() -> None:
    doc = _er_base(nodes=[
        {"id": "CUSTOMER", "attributes": [
            {"type": "decimal", "name": "*id", "params": [10, 2], "array": True, "optional": True,
             "keys": ["PK", "FK"], "comment": 'say "hi" #1'},
        ]},
        {"id": "ORDER"},
    ])
    assert '        decimal(10,2)[]? *id PK, FK "say #quot;hi#quot; #35;1"\n' in render.render(doc)


@pytest.mark.parametrize(
    ("left", "left_form", "right", "right_form", "connector_form", "identifying", "relation"),
    [
        ("zero_or_more", "mirrored", "exactly_one", "symbol", "symbol", True, "o{--||"),
        ("zero_or_one", "symbol", "zero_or_one", "mirrored", "symbol", False, "|o..|o"),
        ("exactly_one", "1", "zero_or_more", "zero-or-more", "words", True, "1 to zero or more"),
        ("zero_or_more", "many-0", "one_or_more", "1-plus", "words", False, "many(0) optionally to 1+"),
        ("exactly_one", "one", "zero_or_more", "many", "symbol", True, "one--many"),
    ],
)
def test_er_cardinality_spellings(left, left_form, right, right_form, connector_form, identifying, relation) -> None:
    edge = {"from": "CUSTOMER", "to": "ORDER", "label": "r", "left": left, "right": right, "left_form": left_form,
            "right_form": right_form, "connector_form": connector_form, "identifying": identifying}
    assert f"    CUSTOMER {relation} ORDER : r\n" in render.render(_er_base(edges=[edge]))


def test_er_unknown_cardinality_is_rejected() -> None:
    doc = _er_base()
    doc["edges"][0]["left"] = "lots"
    assert _er_error_path(doc) == "/edges/0/left"


def test_er_form_must_belong_to_its_cardinality() -> None:
    doc = _er_base()
    doc["edges"][0]["right_form"] = "only-one"  # right is zero_or_more
    assert _er_error_path(doc) == "/edges/0/right_form"
    doc["edges"][0]["right_form"] = "mirrored"
    doc["edges"][0]["right"] = "exactly_one"  # `||` has no mirrored spelling
    assert _er_error_path(doc) == "/edges/0/right_form"


def test_er_undeclared_entity_is_rejected() -> None:
    doc = _er_base()
    doc["edges"][0]["to"] = "GHOST"
    assert _er_error_path(doc) == "/edges/0/to"


def test_er_relationship_label_is_required() -> None:
    doc = _er_base()
    del doc["edges"][0]["label"]
    assert _er_error_path(doc) == "/edges/0/label"


def test_er_raw_member_strings_are_not_accepted() -> None:
    doc = _er_base()
    doc["nodes"][0]["members"] = ["string name PK"]
    assert _er_error_path(doc) == "/nodes/0/members"
    doc = _er_base()
    doc["nodes"][0]["attributes"] = ["string name PK"]
    assert _er_error_path(doc) == "/nodes/0/attributes/0"


@pytest.mark.parametrize("bad", ["end", "one", "many-things", "to", "u-turn", "Class", "direction", "2fast", "a b", "x--y"])
def test_er_ids_that_the_lexer_would_misread_are_rejected(bad: str) -> None:
    doc = _er_base()
    doc["nodes"][0]["id"] = bad
    doc["edges"][0]["from"] = bad
    assert _er_error_path(doc) == "/nodes/0/id"


def test_er_reserved_words_are_fine_as_quoted_names_and_labels_are_quoted() -> None:
    doc = _er_base()
    doc["nodes"][0]["name"] = "end"
    doc["edges"][0]["label"] = "one"
    assert '    "end" ||--o{ ORDER : "one"\n' in render.render(doc)


def test_er_duplicate_ids_and_names_are_rejected() -> None:
    doc = _er_base(nodes=[{"id": "CUSTOMER"}, {"id": "CUSTOMER"}])
    assert _er_error_path(doc) == "/nodes/1/id"
    doc = _er_base(nodes=[{"id": "CUSTOMER"}, {"id": "ORDER", "name": "CUSTOMER"}])
    assert _er_error_path(doc) == "/nodes/1/name"
    doc = _er_base(subgraphs=[{"id": "ORDER"}])
    assert _er_error_path(doc) == "/subgraphs/0/id"


@pytest.mark.parametrize("bad", ["TD", "td", "up"])
def test_er_unknown_direction_is_rejected(bad: str) -> None:
    assert _er_error_path(_er_base(direction=bad)) == "/direction"


def test_er_direction_phrase_in_text_is_rejected() -> None:
    doc = _er_base()
    doc["edges"][0]["label"] = "set direction LR now"
    assert _er_error_path(doc) == "/edges/0/label"


@pytest.mark.parametrize("bad", ["PK", "fk", "Uk"])
def test_er_key_words_cannot_be_attribute_names_or_types(bad: str) -> None:
    doc = _er_base()
    doc["nodes"][0]["attributes"] = [{"type": "string", "name": bad}]
    assert _er_error_path(doc) == "/nodes/0/attributes/0/name"
    doc["nodes"][0]["attributes"] = [{"type": bad, "name": "x"}]
    assert _er_error_path(doc) == "/nodes/0/attributes/0/type"


def test_er_attribute_type_must_start_with_a_letter_and_keys_are_unique() -> None:
    doc = _er_base()
    doc["nodes"][0]["attributes"] = [{"type": "2int", "name": "x"}]
    assert _er_error_path(doc) == "/nodes/0/attributes/0/type"
    doc["nodes"][0]["attributes"] = [{"type": "int", "name": "x", "keys": ["PK", "PK"]}]
    assert _er_error_path(doc) == "/nodes/0/attributes/0/keys/1"
    doc["nodes"][0]["attributes"] = [{"type": "int", "name": "x", "params": [1.5]}]
    assert _er_error_path(doc) == "/nodes/0/attributes/0/params/0"


def test_er_entity_belongs_to_at_most_one_subgraph() -> None:
    doc = _er_base(subgraphs=[
        {"id": "g1", "members": ["CUSTOMER"]},
        {"id": "g2", "members": ["ORDER"], "subgraphs": [{"id": "g3", "members": ["CUSTOMER"]}]},
    ])
    assert _er_error_path(doc) == "/subgraphs/1/subgraphs/0/members/0"


def test_er_nested_subgraphs_and_subgraph_endpoints_render() -> None:
    doc = _er_base(subgraphs=[{"id": "dom", "name": "Customer Domain", "title": "Domain", "direction": "TB",
                           "members": ["CUSTOMER"], "subgraphs": [{"id": "inner", "members": ["ORDER"]}]}])
    doc["edges"].append({"from": "dom", "to": "inner", "label": "contains", "left": "exactly_one", "right": "exactly_one"})
    source = render.render(doc)
    assert '    subgraph "Customer Domain" ["Domain"]\n        direction TB\n        CUSTOMER\n' in source
    assert "        subgraph inner\n            ORDER\n        end\n    end\n" in source
    assert '    "Customer Domain" ||--|| inner : contains\n' in source
    doc["edges"][1]["from_classes"] = ["c"]
    doc["class_defs"] = [{"names": ["c"], "style": {"fill": "#fff"}}]
    assert _er_error_path(doc) == "/edges/1/from_classes"


def test_er_styles_are_typed_and_validated() -> None:
    doc = _er_base(styles=[{"nodes": ["CUSTOMER", "ORDER"], "style": {"fill": "#f9f", "strokeWidth": "2px"}}])
    assert "    style CUSTOMER,ORDER fill:#f9f,stroke-width:2px\n" in render.render(doc)
    for key, bad in (("strokeWidth", "1.5px"), ("fill", "rgb(1,2,3)"), ("strokeDasharray", "5 5"), ("fontWeight", "heavy")):
        broken = copy.deepcopy(doc)
        broken["styles"][0]["style"] = {key: bad}
        assert _er_error_path(broken) == f"/styles/0/style/{key}"
    broken = copy.deepcopy(doc)
    broken["styles"][0]["style"] = "fill:#f9f"
    assert _er_error_path(broken) == "/styles/0/style"


def test_er_class_references_must_be_declared() -> None:
    doc = _er_base(class_defs=[{"names": ["hot"], "style": {"fill": "#f00"}}],
               class_assignments=[{"nodes": ["CUSTOMER"], "classes": ["hot"]}])
    doc["nodes"][1]["classes"] = ["hot"]
    source = render.render(doc)
    assert "    ORDER:::hot\n" in source and "    class CUSTOMER hot\n" in source
    doc["nodes"][1]["classes"] = ["cold"]
    assert _er_error_path(doc) == "/nodes/1/classes/0"


def test_er_quoted_name_entities_cannot_be_style_or_class_targets() -> None:
    doc = _er_base(styles=[{"nodes": ["CUSTOMER"], "style": {"fill": "#f9f"}}])
    doc["nodes"][0]["name"] = "The Customer"
    assert _er_error_path(doc) == "/styles/0/nodes/0"


def test_er_multiline_description_uses_the_block_form() -> None:
    doc = _er_base(accessibility={"title": "Orders", "description": "line one\nline two"})
    assert "    accDescr {\n        line one\n        line two\n    }\n" in render.render(doc)


def test_er_config_is_typed() -> None:
    assert _er_error_path(_er_base(config={"er": {"layoutDirection": "TD"}})) == "/config/er/layoutDirection"
    assert _er_error_path(_er_base(config={"er": {"fontSize": True}})) == "/config/er/fontSize"
    source = render.render(_er_base(title="Orders", config={"layout": "elk", "er": {"fontSize": 14}}))
    assert source.startswith('---\ntitle: "Orders"\nconfig:\n  layout: "elk"\n  er:\n    fontSize: 14\n---\nerDiagram\n')
