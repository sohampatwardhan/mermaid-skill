"""Type-specific semantic rules for the chart builders (group 3).

The generic reliability bar lives in test_builders.py; these are the rules that bar cannot
see: values Mermaid would silently drop, cross-references, and structural constraints.
"""

from __future__ import annotations

import copy
import json

import pytest

from skill_docs import SKILL_DIR, load_render

render = load_render()
FIXTURES = SKILL_DIR / "tests" / "fixtures"


def fixture(type_id: str, name: str = "maximal.json") -> dict:
    return json.loads((FIXTURES / type_id / name).read_text())


def rejects(ir: dict, path: str, words: str = "") -> None:
    with pytest.raises(render.IRError) as info:
        render.render(ir)
    assert info.value.path == path, str(info.value)
    assert words in info.value.reason, str(info.value)


def chart(target: str, **body) -> dict:
    return {"diagram": "chart", "target": target, **body}


# --- pie -----------------------------------------------------------------------------------


def test_pie_duplicate_label_is_rejected_not_dropped() -> None:
    ir = chart("pie", slices=[{"label": "Dogs", "value": 1}, {"label": "Dogs", "value": 2}])
    rejects(ir, "/slices/1/label", "duplicate")


def test_pie_values_are_non_negative_and_zero_renders() -> None:
    rejects(chart("pie", slices=[{"label": "Dogs", "value": -1}]), "/slices/0/value")
    assert '"Dogs" : 0' in render.render(chart("pie", slices=[{"label": "Dogs", "value": 0}, {"label": "Cats", "value": 1}]))


def test_pie_highlight_slice_must_name_a_plain_slice() -> None:
    ir = chart("pie", slices=[{"label": "a;b", "value": 1}], config={"pie": {"highlightSlice": "Cats"}})
    rejects(ir, "/config/pie/highlightSlice", "undeclared")
    ir["config"]["pie"]["highlightSlice"] = "a;b"
    rejects(ir, "/config/pie/highlightSlice", "entity codes")


def test_pie_title_placement() -> None:
    rejects(chart("pie", titlePlacement="inline", slices=[{"label": "A", "value": 1}]), "/titlePlacement", "title")
    source = render.render(chart("pie", title="T", titlePlacement="inline", showData=True, slices=[{"label": "A", "value": 1}]))
    assert source.splitlines()[0] == "pie showData title T"


def test_pie_config_is_typed_frontmatter() -> None:
    ir = fixture("pie")
    source = render.render(ir)
    assert source.startswith("---\nconfig:\n")
    assert '    legendPosition: "bottom"' in source
    bad = copy.deepcopy(ir)
    bad["config"]["pie"]["donutHole"] = 0.95
    rejects(bad, "/config/pie/donutHole")
    bad = copy.deepcopy(ir)
    bad["config"]["pie"] = {}
    rejects(bad, "/config/pie", "empty")
    bad = copy.deepcopy(ir)
    bad["config"]["themeVariables"]["pie1"] = "red; x"
    rejects(bad, "/config/themeVariables/pie1")


# --- quadrantChart -------------------------------------------------------------------------


def test_quadrant_points_stay_inside_the_unit_square() -> None:
    rejects(chart("quadrantChart", points=[{"label": "A", "x": 1.2, "y": 0.5}]), "/points/0/x")


def test_quadrant_stroke_color_needs_stroke_width() -> None:
    ir = chart("quadrantChart", points=[{"label": "A", "x": 0.5, "y": 0.5, "style": {"strokeColor": "#333"}}])
    rejects(ir, "/points/0/style/strokeColor", "strokeWidth")
    ir["classes"] = {"wide": {"strokeWidth": "2px"}}
    ir["points"][0]["class"] = "wide"
    assert "stroke-color: #333" in render.render(ir)


def test_quadrant_style_values_follow_the_lexer() -> None:
    point = {"label": "A", "x": 0.5, "y": 0.5}
    rejects(chart("quadrantChart", points=[{**point, "style": {"radius": 2.5}}]), "/points/0/style/radius")
    rejects(chart("quadrantChart", points=[{**point, "style": {"color": "red"}}]), "/points/0/style/color")
    rejects(chart("quadrantChart", points=[{**point, "style": {"strokeWidth": "2"}}]), "/points/0/style/strokeWidth")
    rejects(chart("quadrantChart", classes={"c_1": {"radius": 3}}, points=[point]), "/classes/c_1")
    rejects(chart("quadrantChart", points=[{**point, "class": "nope"}]), "/points/0/class", "undeclared")


# --- xyChart -------------------------------------------------------------------------------


def test_xy_series_length_matches_categories() -> None:
    ir = chart("xychart", xAxis={"categories": ["a", "b"]}, series=[{"type": "bar", "values": [1, 2, 3]}])
    rejects(ir, "/series/0/values", "3 values for 2 categories")


def test_xy_point_labels_only_on_line_series() -> None:
    ir = chart("xychart", series=[{"type": "bar", "values": [{"value": 1, "label": "x"}]}])
    rejects(ir, "/series/0/values/0/label", "line")


def test_xy_axis_shapes() -> None:
    series = [{"type": "line", "values": [1, 2]}]
    rejects(chart("xychart", xAxis={"categories": ["a", "b"], "min": 0, "max": 1}, series=series), "/xAxis/categories")
    rejects(chart("xychart", yAxis={"min": 5, "max": 5}, series=series), "/yAxis/max")
    rejects(chart("xychart", yAxis={"min": 5}, series=series), "/yAxis/max")
    rejects(chart("xychart", xAxis={"categories": ["a", "a"]}, series=series), "/xAxis/categories/1", "duplicate")


def test_xy_alias_keyword_is_emitted_unchanged() -> None:
    assert render.render(fixture("xyChart", "maximal.xychart-beta.json")).startswith("xychart-beta horizontal\n")


# --- sankey --------------------------------------------------------------------------------


def test_sankey_is_hand_author_only() -> None:
    for keyword in ("sankey", "sankey-beta"):
        rejects(chart(keyword, links=[{"from": "A", "to": "B", "value": 1}]), "/target", "hand-author-only")


# --- radar ---------------------------------------------------------------------------------


def test_radar_curve_value_count_matches_axes() -> None:
    ir = chart("radar-beta", axes=[{"id": "a"}, {"id": "b"}], curves=[{"id": "c", "values": [1]}])
    rejects(ir, "/curves/0/values", "1 values for 2 axes")


def test_radar_key_value_curve_names_every_axis_once() -> None:
    axes = [{"id": "a"}, {"id": "b"}]
    rejects(chart("radar-beta", axes=axes, curves=[{"id": "c", "entries": [{"axis": "a", "value": 1}]}]),
            "/curves/0/entries", "missing: b")
    twice = [{"axis": "a", "value": 1}, {"axis": "a", "value": 2}]
    rejects(chart("radar-beta", axes=axes, curves=[{"id": "c", "entries": twice}]), "/curves/0/entries/1/axis")
    rejects(chart("radar-beta", axes=axes, curves=[{"id": "c"}]), "/curves/0", "exactly one")


def test_radar_rejects_keywords_as_ids_and_negative_values() -> None:
    rejects(chart("radar-beta", axes=[{"id": "max"}], curves=[{"id": "c", "values": [1]}]), "/axes/0/id", "keyword")
    rejects(chart("radar-beta", axes=[{"id": "a"}], curves=[{"id": "c", "values": [-1]}]), "/curves/0/values/0")
    rejects(chart("radar-beta", axes=[{"id": "a"}], curves=[{"id": "c", "values": [1]}], max=5, min=5), "/min")


def test_radar_emits_curves_on_one_line() -> None:
    source = render.render(fixture("radar"))
    assert "    curve alice[\"Alice\"]{85, 90, 80, 70, 75, 90}, bob[" in source
    assert "cara{ a: 60, g: 65, h: 70, e: 95, s: 60, m: 55 }" in source


# --- treemap -------------------------------------------------------------------------------


def test_treemap_node_is_a_leaf_or_a_section() -> None:
    rejects(chart("treemap-beta", nodes=[{"label": "A", "value": 1, "children": [{"label": "B", "value": 1}]}]),
            "/nodes/0", "exactly one")
    rejects(chart("treemap-beta", nodes=[{"label": "A"}]), "/nodes/0", "exactly one")
    rejects(chart("treemap-beta", nodes=[{"label": "A", "children": []}]), "/nodes/0/children")
    rejects(chart("treemap-beta", nodes=[{"label": "A", "value": -1}]), "/nodes/0/value")


def test_treemap_tabs_and_classes() -> None:
    source = render.render(fixture("treemap", "maximal.treemap.json"))
    assert '\n\t\t"Company C": 0.15\n' in source
    source = render.render(fixture("treemap"))
    assert '"Equipment": 200000:::important' in source
    assert '"Marketing":::highlight' in source
    assert "classDef important fill:#f96,stroke:#333,stroke-width:2px;" in source


# --- venn ----------------------------------------------------------------------------------


def test_venn_union_references_and_duplicates() -> None:
    sets = [{"id": "A"}, {"id": "B"}]
    rejects(chart("venn-beta", sets=sets, unions=[{"sets": ["A", "C"]}]), "/unions/0/sets/1", "undeclared")
    rejects(chart("venn-beta", sets=sets, unions=[{"sets": ["A", "B"]}, {"sets": ["B", "A"]}]), "/unions/1/sets")
    rejects(chart("venn-beta", sets=sets, unions=[{"sets": ["A", "A"]}]), "/unions/0/sets/1", "duplicate")


def test_venn_style_targets() -> None:
    sets = [{"id": "A", "texts": [{"id": "t1"}]}, {"id": "B"}]
    rejects(chart("venn-beta", sets=sets, styles=[{"targets": ["A", "B"], "style": {"fill": "#f00"}}]),
            "/styles/0/targets", "no union")
    rejects(chart("venn-beta", sets=sets, styles=[{"targets": ["Q"], "style": {"fill": "#f00"}}]), "/styles/0/targets/0")
    assert "style t1 color:red" in render.render(chart("venn-beta", sets=sets, styles=[{"targets": ["t1"], "style": {"color": "red"}}]))


def test_venn_ids_are_quoted_when_needed_and_unique() -> None:
    source = render.render(chart("venn-beta", sets=[{"id": "text"}, {"id": "Foo Bar"}, {"id": "Plain"}]))
    assert 'set "text"' in source and 'set "Foo Bar"' in source and "set Plain\n" in source
    rejects(chart("venn-beta", sets=[{"id": "A", "texts": [{"id": "A"}]}]), "/sets/0/texts/0/id", "duplicate")


def test_venn_ports_the_old_branch_example() -> None:
    source = render.render(fixture("venn", "maximal.team-overlap.json"))
    assert '    set A["Frontend"]:20\n        text A1["React"]\n' in source
    assert '    union A,B["Shared"]:3\n        text AB1["OpenAPI"]\n' in source
