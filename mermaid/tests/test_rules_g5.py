"""Type-specific semantic rules for group 5 (agentflow, usecase, swimlanes, wardley, cynefin,
eventmodeling) that the generic builder bar in test_builders.py does not cover."""

from __future__ import annotations

import copy
import json

import pytest

from skill_docs import SKILL_DIR, load_render

render = load_render()
FIXTURES = SKILL_DIR / "tests" / "fixtures"


def maximal(type_id: str) -> dict:
    return json.loads((FIXTURES / type_id / "maximal.json").read_text())


def error_at(doc: dict, path: str, words: str = "") -> None:
    with pytest.raises(render.IRError) as info:
        render.render(doc)
    assert info.value.path == path, str(info.value)
    assert words in info.value.reason, str(info.value)


# --- cynefin -------------------------------------------------------------------------------


def cynefin(**extra) -> dict:
    return {"diagram": "cynefin", "target": "cynefin-beta",
            "domains": [{"domain": "complex", "items": ["a"]}, {"domain": "clear"}], **extra}


def test_cynefin_self_transition_is_rejected() -> None:
    error_at(cynefin(transitions=[{"from": "clear", "to": "clear"}]), "/transitions/0/to", "self-transition")


def test_cynefin_duplicate_domain_is_rejected() -> None:
    doc = cynefin()
    doc["domains"].append({"domain": "complex"})
    error_at(doc, "/domains/2/domain", "duplicate")


def test_cynefin_keeps_domain_and_transition_order() -> None:
    doc = cynefin(transitions=[{"from": "clear", "to": "complex"}, {"from": "complex", "to": "clear"}])
    lines = render.render(doc).splitlines()
    assert lines.index("  complex") < lines.index("  clear")
    assert lines[-2:] == ["  clear --> complex", "  complex --> clear"]


def test_cynefin_text_is_entity_encoded() -> None:
    source = render.render(cynefin(domains=[{"domain": "complex", "items": ['say "hi" #1']}]))
    assert '"say #quot;hi#quot; #35;1"' in source


def test_cynefin_config_goes_to_frontmatter() -> None:
    source = render.render(cynefin(config={"seed": 7}))
    assert source.startswith("---\nconfig:\n  cynefin:\n    seed: 7\n---\ncynefin-beta\n")
    assert render.render(cynefin(config={})).startswith("cynefin-beta\n")


# --- eventmodeling -------------------------------------------------------------------------


def frames(*items: dict, blocks: list | None = None) -> dict:
    doc = {"diagram": "eventmodeling", "target": "eventmodeling", "timeframes": list(items)}
    if blocks is not None:
        doc["dataBlocks"] = blocks
    return doc


UI = {"number": "01", "type": "ui", "entity": "CartUI"}


def test_eventmodeling_frame_keyword_follows_reset_and_form() -> None:
    doc = frames(
        UI,
        {"number": "02", "type": "cmd", "entity": "A", "reset": True},
        {"number": "03", "type": "cmd", "entity": "B", "form": "relaxed"},
        {"number": "04", "type": "cmd", "entity": "C", "form": "relaxed", "reset": True},
    )
    assert render.render(doc).splitlines()[1:] == [
        "tf 01 ui CartUI", "rf 02 cmd A", "timeframe 03 cmd B", "resetframe 04 cmd C",
    ]


def test_eventmodeling_data_values() -> None:
    doc = frames({**UI, "data": [{"key": "a", "value": "it's"}, {"key": "b", "value": -2.5},
                                 {"key": "c", "value": "string", "raw": True}]})
    assert render.render(doc).splitlines()[1] == "tf 01 ui CartUI { a: 'it's', b: -2.5, c: string }"
    error_at(frames({**UI, "data": [{"key": "a", "value": "two words", "raw": True}]}), "/timeframes/0/data/0/value")
    error_at(frames({**UI, "data": [{"key": "a", "value": False}]}), "/timeframes/0/data/0/value")


def test_eventmodeling_exclusive_attachments() -> None:
    block = [{"id": "D", "fields": [{"key": "a", "value": 1}]}]
    data = [{"key": "a", "value": 1}]
    error_at(frames({**UI, "data": data, "dataRef": "D"}, blocks=block), "/timeframes/0/dataRef", "either")
    error_at(frames(UI, {"number": "02", "type": "rmo", "entity": "R", "data": data, "relations": ["01"]}),
             "/timeframes/1/relations", "cannot follow")
    error_at(frames({**UI, "dataType": "json"}), "/timeframes/0/dataType", "inline data")


def test_eventmodeling_references_and_numbers() -> None:
    error_at(frames(UI, {**UI, "entity": "Other"}), "/timeframes/1/number", "duplicate")
    error_at(frames({**UI, "relations": ["09"]}), "/timeframes/0/relations/0", "undeclared")
    error_at(frames({**UI, "dataRef": "Nope"}), "/timeframes/0/dataRef", "undeclared")
    error_at(frames({**UI, "number": "a1"}), "/timeframes/0/number")


def test_eventmodeling_entity_names() -> None:
    assert "tf 01 ui A.B.C" in render.render(frames({**UI, "entity": "A.B.C"}))
    for bad in ("Cart-UI", "3Cart", "Cart UI", "data", "tf"):
        error_at(frames({**UI, "entity": bad}), "/timeframes/0/entity")


# --- wardley -------------------------------------------------------------------------------


def wardley(**extra) -> dict:
    return {"diagram": "graph", "target": "wardley-beta",
            "components": [{"id": "A", "visibility": 1, "evolution": 0}], **extra}


def test_wardley_coordinates_always_have_a_decimal_point() -> None:
    assert 'component "A" [1.0, 0.0]' in render.render(wardley())
    error_at(wardley(components=[{"id": "A", "visibility": 1.2, "evolution": 0.5}]), "/components/0/visibility")


def test_wardley_dual_label_cannot_have_width() -> None:
    stages = [{"label": "G", "dualLabel": "C", "width": 0.5}, {"label": "P"}]
    error_at(wardley(evolutionStages=stages), "/evolutionStages/0/width", "dualLabel")


def test_wardley_link_labels_only_on_dependency_and_flow() -> None:
    comps = [{"id": "A", "visibility": 0.5, "evolution": 0.5}, {"id": "B", "visibility": 0.4, "evolution": 0.4}]
    error_at(wardley(components=comps, links=[{"from": "A", "to": "B", "kind": "flowReverse", "label": "x"}]),
             "/links/0/label")
    source = render.render(wardley(components=comps, links=[{"from": "A", "to": "B", "kind": "flow", "label": "it's"}]))
    assert "\"A\" +'it#39;s'> \"B\"" in source


def test_wardley_names_are_unique_and_quoted() -> None:
    comps = [{"id": "A", "label": "Same", "visibility": 0.5, "evolution": 0.5},
             {"id": "B", "label": "Same", "visibility": 0.4, "evolution": 0.4}]
    error_at(wardley(components=comps), "/components/1/label", "merge")


def test_wardley_pipeline_and_evolve_need_components() -> None:
    anchors = [{"id": "U", "visibility": 0.9, "evolution": 0.9}]
    error_at(wardley(anchors=anchors, evolve=[{"id": "U", "target": 0.5}]), "/evolve/0/id")
    error_at(wardley(anchors=anchors, pipelines=[{"parent": "U", "stages": [{"label": "x", "evolution": 0.2}]}]),
             "/pipelines/0/parent")


def test_wardley_empty_map_is_rejected() -> None:
    error_at({"diagram": "graph", "target": "wardley-beta", "title": "T"}, "", "at least one")


# --- swimlanes -----------------------------------------------------------------------------


def lanes(**extra) -> dict:
    return {"diagram": "graph", "target": "swimlane-beta", "groups": [{"id": "L"}],
            "nodes": [{"id": "a", "label": "A", "group": "L"}, {"id": "b", "label": "B", "group": "L"}], **extra}


def test_swimlanes_node_label_rules() -> None:
    doc = lanes()
    doc["nodes"][0]["markdown"] = "**A**"
    error_at(doc, "/nodes/0/label", "exactly one")
    doc = lanes()
    doc["nodes"][0].update(kind="round", shape="doc")
    error_at(doc, "/nodes/0/shape", "either")


def test_swimlanes_keyword_ids_are_rejected() -> None:
    doc = lanes()
    doc["nodes"][0]["id"] = "end"
    error_at(doc, "/nodes/0/id", "keyword")


def test_swimlanes_chain_and_default_direction() -> None:
    doc = lanes(nodes=lanes()["nodes"] + [{"id": "c", "label": "C"}],
                edges=[{"from": "a", "to": "b", "then": [{"to": "c", "kind": "thick", "label": "go"}]}])
    source = render.render(doc)
    assert source.startswith("swimlane-beta\n")
    assert '  a --> b ==>|"go"| c' in source


def test_swimlanes_styles_are_typed() -> None:
    for bad in ({"fill": "fill:#fff"}, {"fill": "rgb(1,2,3)"}, {"strokeWidth": "2"}, {}):
        error_at(lanes(classDefs=[{"name": "c", "style": bad}]), "/classDefs/0/style" + (f"/{next(iter(bad))}" if bad else ""))
    doc = lanes()
    doc["nodes"][0]["class"] = "missing"
    error_at(doc, "/nodes/0/class", "undeclared")


# --- agentflow -----------------------------------------------------------------------------


def agent(**extra) -> dict:
    return {"diagram": "graph", "target": "agentflow-beta", "nodes": [{"id": "a", "label": "A"}], **extra}


def test_agentflow_flow_parents_must_not_cycle() -> None:
    flows = [{"id": "f", "label": "F", "parent": "g"}, {"id": "g", "label": "G", "parent": "f"}]
    error_at(agent(flows=flows), "/flows/0/parent", "cycle")


def test_agentflow_node_placement_rules() -> None:
    error_at(agent(flows=[{"id": "f", "label": "F"}], nodes=[{"id": "a", "label": "A", "flow": "f", "global": True}]),
             "/nodes/0/global")
    error_at(agent(nodes=[{"id": "a", "label": "A", "labelType": "markdown"}]), "/nodes/0/labelType")
    error_at(agent(nodes=[{"id": "a", "label": "A", "metaLabel": "B"}]), "/nodes/0/label", "exactly one")


def test_agentflow_edge_metadata_needs_an_id() -> None:
    nodes = [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]
    error_at(agent(nodes=nodes, edges=[{"from": "a", "to": "b", "curve": "linear"}]), "/edges/0/curve", "edge id")
    source = render.render(agent(nodes=nodes, edges=[{"from": "a", "to": "b", "id": "e1", "curve": "linear"}]))
    assert source.endswith("  a e1@--> b\n  e1@{ curve: linear }\n")


def test_agentflow_metadata_values() -> None:
    error_at(agent(nodes=[{"id": "a", "label": "A", "model": 'say "hi"'}]), "/nodes/0/model")
    error_at(agent(nodes=[{"id": "a", "label": "A", "model": "x #35; y"}]), "/nodes/0/model", "entity")
    error_at(agent(nodes=[{"id": "a", "label": "A", "custom": {"shape": "x"}}]), "/nodes/0/custom/shape", "reserved")
    error_at(agent(nodes=[{"id": "a", "label": "A", "custom": {"__proto__": 1}}]), "/nodes/0/custom/__proto__")


def test_agentflow_metadata_block_form() -> None:
    source = render.render(agent(nodes=[{"id": "a", "label": "A", "shape": "tool", "custom": {"retry": 2},
                                         "metadataBlock": True}]))
    assert source.endswith('  a["A"]\n  a@{\n    shape: tool\n    retry: 2\n  }\n')


# --- usecase -------------------------------------------------------------------------------


def uc(**extra) -> dict:
    doc = {"diagram": "usecase", "target": "usecase-beta", "actors": [{"id": "A"}, {"id": "Z"}],
           "usecases": [{"id": "B", "label": "B"}, {"id": "C", "label": "C"}]}
    doc.update(extra)
    return doc


def test_usecase_relationship_endpoints() -> None:
    error_at(uc(edges=[{"from": "A", "to": "B", "kind": "include"}]), "/edges/0/kind", "use cases")
    error_at(uc(edges=[{"from": "A", "to": "B", "kind": "generalization"}]), "/edges/0/kind", "two actors")
    error_at(uc(jsonNodes=[{"id": "J", "data": {"a": 1}}], edges=[{"from": "A", "to": "J", "kind": "circle"}]),
             "/edges/0/kind", "JSON")
    error_at(uc(edges=[{"from": "B", "to": "C", "kind": "include", "label": "x"}]), "/edges/0/label")
    error_at(uc(edges=[{"from": "A", "to": "B", "kind": "cross", "length": 2}]), "/edges/0/length")


def test_usecase_edge_length_adds_dashes() -> None:
    source = render.render(uc(edges=[{"from": "A", "to": "B", "length": 2},
                                     {"from": "A", "to": "C", "label": "x", "length": 1}]))
    assert "A ----> B\n" in source and 'A -- "x" ---> C\n' in source


def test_usecase_implicit_use_case_must_be_an_edge_end() -> None:
    doc = uc()
    doc["usecases"].append({"id": "Later", "implicit": True})
    error_at(copy.deepcopy(doc), "/usecases/2/implicit", "edge")
    doc["edges"] = [{"from": "A", "to": "Later"}]
    source = render.render(doc)
    assert "A --> Later" in source and "Later(" not in source


def test_usecase_quoted_form_derives_the_id() -> None:
    doc = uc(usecases=[{"id": "Reset_password", "label": "Reset password", "form": "quoted"}])
    assert '"Reset password"' in render.render(doc)
    error_at(uc(usecases=[{"id": "Reset", "label": "Reset password", "form": "quoted"}]), "/usecases/0/id", "derives")
    error_at(uc(usecases=[{"id": "R_x", "label": "R (x)", "form": "quoted"}]), "/usecases/0/label")


def test_usecase_keyword_ids_are_rejected() -> None:
    for word in ("end", "note", "include", "Package", "LR", "true"):
        error_at(uc(actors=[{"id": word}]), "/actors/0/id", "keyword")
    assert "actor 3rd" in render.render(uc(actors=[{"id": "3rd"}]))


def test_usecase_actor_and_usecase_metadata_rules() -> None:
    error_at(uc(actors=[{"id": "A", "icon": "fa:user", "type": "hollow"}]), "/actors/0/icon")
    error_at(uc(usecases=[{"id": "B", "label": "B", "shape": "rect", "business": True}]), "/usecases/0/business")
    error_at(uc(actors=[{"id": "A", "icon": "user"}]), "/actors/0/icon")


def test_usecase_json_strings_are_encoded() -> None:
    source = render.render(uc(jsonNodes=[{"id": "J", "data": {"k\"": ["a;b", 1, None, True]}}]))
    assert 'json J@{ "k#quot;": ["a#59;b", 1, null, true] }' in source
