"""Unit tests for render.py's IRError, Validator, shared emitters, and the builder registry."""

from __future__ import annotations

import pytest

from skill_docs import load_render

render = load_render()
IRError = render.IRError
V = render.Validator("demo")


def raises_at(path: str, fn, *args, **kwargs) -> IRError:
    with pytest.raises(IRError) as info:
        fn(*args, **kwargs)
    assert info.value.path == path, str(info.value)
    assert info.value.target == "demo"
    return info.value


# --- IRError --------------------------------------------------------------------------------


def test_irerror_format() -> None:
    err = IRError("flowchart", "/nodes/2/label", "bad")
    assert str(err) == "flowchart: /nodes/2/label: bad"
    assert (err.target, err.path, err.reason) == ("flowchart", "/nodes/2/label", "bad")
    assert isinstance(err, ValueError)


def test_irerror_document_path_shows_slash() -> None:
    assert str(IRError("pie", "", "bad")) == "pie: /: bad"


def test_pointer_escaping() -> None:
    assert render.ptr("", "a/b") == "/a~1b"
    assert render.ptr("/x", "m~n") == "/x/m~0n"
    assert render.ptr("/x", 3) == "/x/3"


# --- Validator.fields -----------------------------------------------------------------------


def test_fields_accepts_known_keys_and_root_envelope() -> None:
    obj = {"diagram": "graph", "target": "demo", "nodes": []}
    assert V.fields(obj, "", required=("nodes",)) is obj


def test_fields_rejects_unknown_key_with_pointer() -> None:
    err = raises_at("/nodes/0/colour", V.fields, {"id": "a", "colour": "red"}, "/nodes/0", ("id",), ("label",))
    assert "unknown key" in err.reason


def test_fields_envelope_keys_only_at_root() -> None:
    raises_at("/a/diagram", V.fields, {"diagram": "x"}, "/a")


def test_fields_rejects_missing_required_key() -> None:
    raises_at("/edges/1/to", V.fields, {"from": "a"}, "/edges/1", ("from", "to"))


def test_fields_rejects_non_object() -> None:
    raises_at("/nodes/0", V.fields, ["x"], "/nodes/0")


# --- Validator.text -------------------------------------------------------------------------

render.text_context("test.quoted", encode={'"': "#quot;"}, reject="`", reject_patterns=((r"^end$", "reserved"),))


def test_text_encodes_and_keeps_other_characters() -> None:
    assert V.text('say "hi" Ünï 日本', "/l", "test.quoted") == "say #quot;hi#quot; Ünï 日本"


@pytest.mark.parametrize(
    "value, needle",
    [("a`b", "cannot be represented"), ("end", "reserved"), ("", "empty"), (" x", "whitespace"),
     ("a\nb", "one line"), ("a\x01b", "control character"), (3, "must be a string")],
)
def test_text_rejections(value, needle) -> None:
    err = raises_at("/l", V.text, value, "/l", "test.quoted")
    assert needle in err.reason


def test_text_newline_context() -> None:
    render.text_context("test.multiline", allow_newline=True, encode={"\n": "<br/>"})
    assert V.text("a\nb", "/l", "test.multiline") == "a<br/>b"


def test_text_context_registered_once() -> None:
    with pytest.raises(ValueError):
        render.text_context("test.quoted")


# --- ident, number, boolean, enum, ref, unique, array ----------------------------------------


def test_ident() -> None:
    assert V.ident("node_1", "/id") == "node_1"
    raises_at("/id", V.ident, "1node", "/id")
    raises_at("/id", V.ident, "a-b", "/id")
    assert V.ident("a-b", "/id", r"[a-z-]+") == "a-b"


def test_number_rejects_bool_and_non_numbers() -> None:
    raises_at("/v", V.number, True, "/v")
    raises_at("/v", V.number, "3", "/v")
    raises_at("/v", V.number, float("nan"), "/v")


def test_number_bounds_and_integer() -> None:
    assert V.number(3, "/v", 0, 5) == "3"
    assert V.number(0.5, "/v") == "0.5"
    assert V.number(1e-7, "/v") == "0.0000001"
    raises_at("/v", V.number, -1, "/v", 0)
    raises_at("/v", V.number, 6, "/v", 0, 5)
    raises_at("/v", V.number, 0, "/v", 0, exclusive_minimum=True)
    raises_at("/v", V.number, 1.5, "/v", integer=True)


def test_boolean() -> None:
    assert V.boolean(False, "/b") is False
    raises_at("/b", V.boolean, "true", "/b")


def test_enum() -> None:
    assert V.enum("a", "/k", {"a", "b"}) == "a"
    assert V.enum("sync", "/k", {"sync": "->>"}) == "->>"
    err = raises_at("/k", V.enum, "z", "/k", {"a", "b"})
    assert "a, b" in err.reason


def test_ref() -> None:
    assert V.ref("n1", "/to", {"n1"}) == "n1"
    raises_at("/to", V.ref, "n2", "/to", {"n1"})


def test_unique_and_array() -> None:
    seen: set[str] = set()
    V.unique("a", "/0", seen)
    raises_at("/1", V.unique, "a", "/1", seen)
    raises_at("/xs", V.array, {}, "/xs")
    raises_at("/xs", V.array, [], "/xs", 1)


# --- shared emitters ------------------------------------------------------------------------


def test_accessibility_line_and_block() -> None:
    lines = render.emit_accessibility(V, {"accessibility": {"title": "T", "description": "D"}})
    assert lines == ["    accTitle: T", "    accDescr: D"]
    block = render.emit_accessibility(V, {"accessibility": {"description": "one\ntwo"}})
    assert block == ["    accDescr {", "        one", "        two", "    }"]
    raises_at("/accessibility/extra", render.emit_accessibility, V, {"accessibility": {"extra": 1}})


def test_comment() -> None:
    assert render.emit_comment(V, {"comment": "note"}) == ["    %% note"]
    raises_at("/comment", render.emit_comment, V, {"comment": "a %% b"})


def test_frontmatter_and_config() -> None:
    schema = {"pie": {"donutHole": ("number", 0, 0.9), "legendPosition": ("enum", ("top", "right"))}}
    config = render.validate_config(V, {"pie": {"donutHole": 0.3}}, "/config", schema)
    assert render.emit_frontmatter('a "t"', config) == [
        "---", 'title: "a \\"t\\""', "config:", "  pie:", "    donutHole: 0.3", "---",
    ]
    raises_at("/config/pie/donutHole", render.validate_config, V, {"pie": {"donutHole": 2}}, "/config", schema)
    raises_at("/config/pie/size", render.validate_config, V, {"pie": {"size": 2}}, "/config", schema)


# --- registry and dispatch ------------------------------------------------------------------


def test_every_keyword_maps_to_one_builder() -> None:
    for keyword, builder in render.BUILDERS.items():
        assert keyword in builder.keywords
        assert builder.catalog == f"reference/catalog/{builder.type_id}.md"
    assert set(render.SERIALIZERS) == {(b.family, k) for k, b in render.BUILDERS.items()}


def test_hand_author_only_target_is_rejected(monkeypatch) -> None:
    monkeypatch.setitem(render.HAND_AUTHOR_ONLY, "demo-beta", "reference/catalog/demo.md")
    with pytest.raises(IRError) as info:
        render.render({"diagram": "x", "target": "demo-beta"})
    assert info.value.path == "/target"
    assert str(info.value) == "demo-beta: /target: hand-author-only; see reference/catalog/demo.md"


def test_unknown_target_and_family_mismatch() -> None:
    with pytest.raises(IRError) as info:
        render.render({"diagram": "graph", "target": "nope"})
    assert info.value.path == "/target"
    with pytest.raises(IRError) as info:
        render.render({"diagram": "chart", "target": "flowchart", "nodes": [], "edges": []})
    assert info.value.path == "/diagram"


def test_registry_rejects_duplicates() -> None:
    builder = next(iter(render.BUILDERS.values()))
    with pytest.raises(ValueError):
        render.register(builder)
    with pytest.raises(ValueError):
        render.hand_author_only("x", builder.keywords[0])


def test_family_target_mismatch_is_rejected() -> None:
    with pytest.raises(IRError):
        render.render({"diagram": "graph", "target": "packet", "nodes": [], "edges": []})


def test_unsupported_backend_is_rejected() -> None:
    with pytest.raises(IRError) as info:
        render.render({"diagram": "info", "target": "info"}, backend="tikz")
    assert "unsupported backend" in info.value.reason
