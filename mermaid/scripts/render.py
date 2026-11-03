#!/usr/bin/env python3
"""Deterministically render a diagram IR (JSON) to Mermaid source.

Same JSON in, same Mermaid text out. This module does not render. Pipe the output
through `scripts/check.sh` before inserting it into Markdown. `--backend` accepts
only `mermaid`. Standard library only; runs offline.

Targets are the keys of BUILDERS (one Builder per catalog type; see
../reference/coverage.md). Hand-author-only targets are the keys of HAND_AUTHOR_ONLY.
Shared IR rules: ../reference/ir.md. Per-type IR keys: ../reference/catalog/<type>.md.

Usage:
    scripts/render.py diagram.json
    scripts/render.py diagram.json --target flowchart -o diagram.mmd
    scripts/render.py diagram.json --backend mermaid
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


class IRError(ValueError):
    """An IR document the builder cannot represent.

    `target` is the IR target keyword, `path` an RFC 6901 JSON Pointer into the input IR
    (`""` is the document itself, shown as `/`), and `reason` says what is wrong.
    `str(err)` is `<target>: <path>: <reason>`.
    """

    def __init__(self, target: str, path: str | None = None, reason: str | None = None) -> None:
        if path is None and reason is None:
            # Legacy single-message form; render() fills in the target.
            target, path, reason = "", "", target
        self.target = target
        self.path = path or ""
        self.reason = reason or ""
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"{self.target}: {self.path or '/'}: {self.reason}"


def ptr(path: str, key: str | int) -> str:
    """Append one reference token to a JSON Pointer (RFC 6901 escaping)."""
    token = str(key).replace("~", "~0").replace("/", "~1")
    return f"{path}/{token}"


# --- text contexts -------------------------------------------------------------------------
#
# A text context is where a free-text IR value lands in the Mermaid source: a quoted node
# label, a message after `:`, a CSV cell, ... Each context lists the characters it encodes
# (as Mermaid entity codes that the type renders back to the original character, so the
# visible text is unchanged) and the characters or patterns it rejects because no safe
# encoding exists there. Contexts are registered once with `text_context(...)`.

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


@dataclass(frozen=True)
class TextContext:
    name: str
    encode: dict[str, str] = field(default_factory=dict)
    reject: str = ""
    reject_patterns: tuple[tuple[str, str], ...] = ()  # (regex, reason)
    allow_newline: bool = False  # a newline must then be in `encode` or be valid as-is
    allow_empty: bool = False
    allow_edge_space: bool = False  # leading or trailing whitespace


TEXT_CONTEXTS: dict[str, TextContext] = {}


def text_context(name: str, **kwargs: Any) -> TextContext:
    if name in TEXT_CONTEXTS:
        raise ValueError(f"text context {name!r} is already registered")
    context = TextContext(name, **kwargs)
    TEXT_CONTEXTS[name] = context
    return context


# Entity codes Mermaid renders back to the original character in labels of most types.
ENTITY = {
    '"': "#quot;",
    "#": "#35;",
    ";": "#59;",
    "<": "#lt;",
    ">": "#gt;",
    "&": "#amp;",
    "|": "#124;",
    "`": "#96;",
    "{": "#123;",
    "}": "#125;",
    "[": "#91;",
    "]": "#93;",
    "(": "#40;",
    ")": "#41;",
    ":": "#58;",
    ",": "#44;",
    "%": "#37;",
    "\\": "#92;",
}

# Shared context for an identifier-like bare word.
text_context("bare.word", reject_patterns=((r"[^A-Za-z0-9_]", "only letters, digits and '_' are allowed"),))


# --- validator -----------------------------------------------------------------------------

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class Validator:
    """Fail-closed reads of one IR document. Every method raises IRError with a pointer."""

    def __init__(self, target: str) -> None:
        self.target = target

    def error(self, path: str, reason: str) -> IRError:
        return IRError(self.target, path, reason)

    def fields(
        self,
        obj: Any,
        path: str,
        required: tuple[str, ...] | list[str] = (),
        optional: tuple[str, ...] | list[str] = (),
    ) -> dict:
        """Require an object with exactly the given keys (plus `diagram`/`target` at the root)."""
        if not isinstance(obj, dict):
            raise self.error(path, f"must be an object, got {type(obj).__name__}")
        allowed = set(required) | set(optional)
        if path == "":
            allowed |= {"diagram", "target"}
        for key in obj:
            if key not in allowed:
                known = ", ".join(sorted(allowed)) or "none"
                raise self.error(ptr(path, key), f"unknown key; allowed keys: {known}")
        for key in required:
            if key not in obj:
                raise self.error(ptr(path, key), "required key is missing")
        return obj

    def array(self, value: Any, path: str, min_items: int = 0) -> list:
        if not isinstance(value, list):
            raise self.error(path, f"must be an array, got {type(value).__name__}")
        if len(value) < min_items:
            raise self.error(path, f"must have at least {min_items} item(s)")
        return value

    def obj_map(self, value: Any, path: str) -> dict:
        """An object used as a map (keys are data, validated by the caller)."""
        if not isinstance(value, dict):
            raise self.error(path, f"must be an object, got {type(value).__name__}")
        return value

    def text(self, value: Any, path: str, context: str) -> str:
        """Return `value` encoded for `context`, or raise when it cannot be represented."""
        ctx = TEXT_CONTEXTS[context]
        if not isinstance(value, str):
            raise self.error(path, f"must be a string, got {type(value).__name__}")
        if not value and not ctx.allow_empty:
            raise self.error(path, "must not be empty")
        if value and not ctx.allow_edge_space and value != value.strip():
            raise self.error(path, "must not start or end with whitespace (Mermaid trims it)")
        if not ctx.allow_newline and ("\n" in value or "\r" in value):
            raise self.error(path, f"must be one line in {context}")
        bad = _CONTROL.search(value)
        if bad:
            raise self.error(path, f"control character {bad.group()!r} cannot be represented")
        for char in value:
            if char in ctx.reject:
                raise self.error(path, f"character {char!r} cannot be represented in {context}")
        for pattern, reason in ctx.reject_patterns:
            if re.search(pattern, value):
                raise self.error(path, f"{reason} ({context})")
        return "".join(ctx.encode.get(char, char) for char in value)

    def ident(self, value: Any, path: str, pattern: re.Pattern[str] | str = _IDENT) -> str:
        regex = re.compile(pattern) if isinstance(pattern, str) else pattern
        if not isinstance(value, str) or not regex.fullmatch(value):
            raise self.error(path, f"must be an identifier matching {regex.pattern}, got {value!r}")
        return value

    def number(
        self,
        value: Any,
        path: str,
        minimum: float | None = None,
        maximum: float | None = None,
        *,
        integer: bool = False,
        exclusive_minimum: bool = False,
    ) -> str:
        """Return the number formatted for Mermaid (no exponent). `bool` is rejected."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise self.error(path, f"must be a number, got {json.dumps(value)}")
        if isinstance(value, float) and not math.isfinite(value):
            raise self.error(path, "must be a finite number")
        if integer and not isinstance(value, int):
            raise self.error(path, f"must be an integer, got {value!r}")
        if minimum is not None and (value < minimum or (exclusive_minimum and value == minimum)):
            op = ">" if exclusive_minimum else ">="
            raise self.error(path, f"must be {op} {minimum}, got {value!r}")
        if maximum is not None and value > maximum:
            raise self.error(path, f"must be <= {maximum}, got {value!r}")
        return format_number(value)

    def boolean(self, value: Any, path: str) -> bool:
        if not isinstance(value, bool):
            raise self.error(path, f"must be true or false, got {json.dumps(value)}")
        return value

    def enum(self, value: Any, path: str, allowed: Any) -> str:
        """`allowed` is a collection of strings; a dict maps each to its Mermaid token."""
        if not isinstance(value, str) or value not in allowed:
            choices = ", ".join(sorted(allowed))
            raise self.error(path, f"unknown value {json.dumps(value)}; use one of: {choices}")
        return allowed[value] if isinstance(allowed, dict) else value

    def ref(self, value: Any, path: str, known: Any) -> str:
        if not isinstance(value, str) or value not in known:
            raise self.error(path, f"references undeclared id {json.dumps(value)}")
        return value

    def unique(self, value: str, path: str, seen: set[str], what: str = "id") -> str:
        if value in seen:
            raise self.error(path, f"duplicate {what} {json.dumps(value)}")
        seen.add(value)
        return value


def format_number(value: int | float) -> str:
    if isinstance(value, int):
        return str(value)
    text = repr(value)
    if "e" in text or "E" in text:
        text = f"{value:.20f}".rstrip("0").rstrip(".")
    return text


# --- shared emitters -----------------------------------------------------------------------

text_context("common.comment", reject_patterns=((r"%%", "'%%' would end the comment early"),))
text_context(
    "common.acc-line",
    reject="{}",
    reject_patterns=((r"%%", "'%%' starts a comment"),),
)
text_context(
    "common.acc-block",
    allow_newline=True,
    reject="{}",
    reject_patterns=((r"%%", "'%%' starts a comment"), (r"\r", "use \\n line breaks")),
)


def emit_comment(v: Validator, ir: dict, path: str = "", indent: str = "    ") -> list[str]:
    """`comment` (one line of text) -> `%% text`."""
    if "comment" not in ir:
        return []
    return [f"{indent}%% {v.text(ir['comment'], ptr(path, 'comment'), 'common.comment')}"]


def emit_accessibility(v: Validator, ir: dict, indent: str = "    ") -> list[str]:
    """`accessibility: {title, description}` -> `accTitle:` and `accDescr:` / `accDescr { }`.

    A description containing a newline uses the multi-line block form.
    """
    if "accessibility" not in ir:
        return []
    path = "/accessibility"
    acc = v.fields(ir["accessibility"], path, optional=("title", "description"))
    lines: list[str] = []
    if "title" in acc:
        lines.append(f"{indent}accTitle: {v.text(acc['title'], ptr(path, 'title'), 'common.acc-line')}")
    if "description" in acc:
        desc = acc["description"]
        if isinstance(desc, str) and "\n" in desc:
            body = v.text(desc, ptr(path, "description"), "common.acc-block")
            lines.append(f"{indent}accDescr {{")
            lines.extend(f"{indent}    {line}" if line else "" for line in body.split("\n"))
            lines.append(f"{indent}}}")
        else:
            lines.append(f"{indent}accDescr: {v.text(desc, ptr(path, 'description'), 'common.acc-line')}")
    return lines


def yaml_scalar(value: Any) -> str:
    """A YAML scalar for frontmatter. JSON scalars are valid YAML 1.2 flow scalars."""
    return json.dumps(value, ensure_ascii=False)


def emit_frontmatter(title: str | None = None, config: dict | None = None) -> list[str]:
    """`---` frontmatter with an optional title and a nested `config` mapping (already validated)."""
    if title is None and not config:
        return []
    lines = ["---"]
    if title is not None:
        lines.append(f"title: {yaml_scalar(title)}")
    if config:
        lines.append("config:")

        def emit(mapping: dict, depth: int) -> None:
            for key, value in mapping.items():
                pad = "  " * depth
                if isinstance(value, dict):
                    lines.append(f"{pad}{yaml_scalar(key) if not _IDENT.fullmatch(key) else key}:")
                    emit(value, depth + 1)
                else:
                    name = key if _IDENT.fullmatch(key) else yaml_scalar(key)
                    lines.append(f"{pad}{name}: {yaml_scalar(value)}")

        emit(config, 1)
    lines.append("---")
    return lines


def validate_config(v: Validator, value: Any, path: str, schema: dict) -> dict:
    """Validate a typed config object against `schema` and return it unchanged.

    Schema values: ("number", min, max) | ("integer", min, max) | ("boolean",) |
    ("enum", (choices...)) | ("string", context) | ("color",) | dict (nested object schema).
    """
    v.fields(value, path, optional=tuple(schema))
    for key, spec in schema.items():
        if key not in value:
            continue
        sub = ptr(path, key)
        item = value[key]
        if isinstance(spec, dict):
            validate_config(v, item, sub, spec)
        elif spec[0] == "number":
            v.number(item, sub, spec[1], spec[2])
        elif spec[0] == "integer":
            v.number(item, sub, spec[1], spec[2], integer=True)
        elif spec[0] == "boolean":
            v.boolean(item, sub)
        elif spec[0] == "enum":
            v.enum(item, sub, spec[1])
        elif spec[0] == "string":
            v.text(item, sub, spec[1])
        elif spec[0] == "color":
            v.text(item, sub, "common.color")
        else:  # pragma: no cover - schema authoring error
            raise ValueError(f"bad config schema entry {key!r}: {spec!r}")
    return value


text_context(
    "common.color",
    reject_patterns=((r"^(?!#[0-9A-Fa-f]{3,8}$|[a-z]+$|(rgb|rgba|hsl|hsla)\([0-9., %]+\)$)", "must be a CSS color: #hex, a name, or rgb()/hsl()"),),
)


# --- builder registry ----------------------------------------------------------------------


@dataclass(frozen=True)
class Builder:
    """One kept or candidate IR builder for a catalog type.

    - `type_id`: catalog file stem, e.g. "flowchart", "c4".
    - `family`: IR `diagram` value, e.g. "graph".
    - `keywords`: IR `target` values, e.g. ("C4Context", ...).
    - `serialize(ir, keyword) -> source`.
    - `text_fields`: JSON Pointer patterns of free-text fields; `*` matches one array index or key.
    - `features`: catalog feature id -> pointer pattern that must match a maximal fixture.
      A pattern may end in `=value` to require that value (strings compare as-is, other
      values as JSON).
    - `probes`: concrete pointers into maximal.json used by the reliability tests:
      "object" (a nested object), "number", "enum", "ref". `None` means the IR has none.
    """

    type_id: str
    family: str
    keywords: tuple[str, ...]
    serialize: Callable[[dict, str], str]
    text_fields: tuple[str, ...] = ()
    features: dict[str, str] = field(default_factory=dict)
    probes: dict[str, str | None] = field(default_factory=dict)

    @property
    def catalog(self) -> str:
        return f"reference/catalog/{self.type_id}.md"


BUILDERS: dict[str, Builder] = {}
HAND_AUTHOR_ONLY: dict[str, str] = {}


def register(builder: Builder) -> Builder:
    for keyword in builder.keywords:
        if keyword in BUILDERS or keyword in HAND_AUTHOR_ONLY:
            raise ValueError(f"target {keyword!r} is registered twice")
        BUILDERS[keyword] = builder
    return builder


def hand_author_only(type_id: str, *keywords: str) -> None:
    for keyword in keywords:
        if keyword in BUILDERS or keyword in HAND_AUTHOR_ONLY:
            raise ValueError(f"target {keyword!r} is registered twice")
        HAND_AUTHOR_ONLY[keyword] = f"reference/catalog/{type_id}.md"


def legacy(fn: Callable[[dict], str]) -> Callable[[dict, str], str]:
    """Adapt a pre-registry serializer `fn(ir)` to the `serialize(ir, keyword)` signature."""

    def serialize(ir: dict, _keyword: str) -> str:
        return fn(ir)

    serialize.__name__ = fn.__name__
    return serialize


# === legacy helpers (used by candidate builders; removed once unused) ===========================

def _require(obj: dict, keys: tuple[str, ...], where: str) -> None:
    missing = [key for key in keys if key not in obj]
    if missing:
        raise IRError(f"{where} missing required field(s): {', '.join(missing)}")


def _safe_id(raw: str, table: dict[str, str]) -> str:
    """Map an arbitrary IR id to a Mermaid-safe bare identifier, memoized in `table`."""
    if raw in table:
        return table[raw]
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", raw):
        safe = raw
    else:
        safe = "n_" + re.sub(r"[^A-Za-z0-9_]", "_", raw)
        if not re.match(r"[A-Za-z_]", safe):
            safe = "n_" + safe
    # Disambiguate collisions created by sanitization (e.g. "1.1" and "1_1").
    base, suffix, candidate = safe, 0, safe
    while candidate in table.values():
        suffix += 1
        candidate = f"{base}_{suffix}"
    table[raw] = candidate
    return candidate


def _quote(text: Any) -> str:
    """Quote a label for Mermaid, escaping embedded quotes and flattening newlines."""
    value = str(text).replace("\r\n", " ").replace("\n", " ").replace('"', "#quot;")
    return f'"{value}"'


def _identifier(raw: str, where: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", raw):
        raise IRError(f"{where} id {raw!r} must be a bare identifier (letters, digits, underscore)")
    return raw


_FLOWCHART_DIRECTIONS = {"TB", "TD", "BT", "LR", "RL"}


_CARDINAL_DIRECTIONS = {"TB", "BT", "LR", "RL"}


def _direction(
    ir: dict, where: str, *, allowed: set[str], default: str | None = None
) -> str | None:
    direction = ir.get("direction", default)
    if direction is not None and direction not in allowed:
        raise IRError(f"{where} has unknown direction {direction!r}; use one of {sorted(allowed)}")
    return direction


def _positive_number(value: Any, where: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise IRError(f"{where} must be a number, got {value!r}")
    return str(value)


def _no_colon(text: str, where: str) -> str:
    if not str(text).strip() or ":" in str(text) or "\n" in str(text):
        raise IRError(f"{where} must be a single line and must not contain ':'")
    return str(text)


# === group 1: core graph: flowchart, sequenceDiagram, classDiagram, stateDiagram, entityRelationshipDiagram ====

# --- flowchart ---
#
# IR (family `graph`; keywords `flowchart`, `graph`, `flowchart-elk`): `nodes` (classic bracket
# `form`, typed `shape`, ISO `kind`, `icon`, or `image`), `edges` (stroke/head/length enums,
# `&` lists, chained `then` segments, edge ids with animation and curve metadata), nested
# `subgraphs` (nodes join one by `group`), typed styles (`classDefs`, `classes`, `styles`,
# `linkStyles`) and `clicks`. Lexer facts checked against Mermaid CLI 12.0.0:
# - Every ENTITY code renders back as the original character in quoted node, typed-shape,
#   icon, subgraph, edge and markdown labels (htmlLabels on), so labels are always quoted
#   and encode all of ENTITY. Encoding `:` also keeps `fa:fa-x` text from becoming an icon.
# - With `htmlLabels: false` entity codes are drawn literally, so `htmlLabels` is not offered.
# - Tooltips land in a `title` attribute and in hover HTML: `<`/`>` are refused, and any
#   tooltip containing `-->` is dropped by the sanitizer, so that is refused too.
# - `rgb()` and other parentheses fail in style values; colors are #hex or a name.
# - `end`, `graph`, `style`, `class`, `call`, `click`, `href`, `subgraph`, `flowchart`,
#   `linkStyle`, `classDef`, `interpolate` and the link targets fail as node ids.

_fc_KEYWORDS = ("flowchart", "graph", "flowchart-elk")
_fc_DIRECTIONS = ("TB", "TD", "BT", "RL", "LR")
_fc_SUB_DIRECTIONS = ("TB", "BT", "RL", "LR")
_fc_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_fc_RESERVED = frozenset({
    "end", "graph", "flowchart", "subgraph", "style", "class", "classDef", "linkStyle", "click",
    "call", "href", "interpolate", "default", "direction", "accTitle", "accDescr",
    "_self", "_blank", "_parent", "_top",
})
# Classic bracket forms: form -> (open, close).
_fc_FORMS = {
    "rect": ("[", "]"),
    "round": ("(", ")"),
    "stadium": ("([", "])"),
    "subroutine": ("[[", "]]"),
    "cylinder": ("[(", ")]"),
    "circle": ("((", "))"),
    "asymmetric": (">", "]"),
    "rhombus": ("{", "}"),
    "hexagon": ("{{", "}}"),
    "parallelogram": ("[/", "/]"),
    "parallelogram-alt": ("[\\", "\\]"),
    "trapezoid": ("[/", "\\]"),
    "trapezoid-alt": ("[\\", "/]"),
    "double-circle": ("(((", ")))"),
}
_fc_SHAPES = (
    "rect", "rounded", "stadium", "subproc", "cyl", "circle", "odd", "diamond", "hex", "lean-r",
    "lean-l", "datastore", "trap-b", "trap-t", "dbl-circ", "text", "notch-rect", "lin-rect",
    "sm-circ", "framed-circle", "fork", "hourglass", "comment", "brace-r", "braces", "bolt", "doc",
    "delay", "das", "lin-cyl", "curv-trap", "div-rect", "tri", "win-pane", "f-circ", "lin-doc",
    "notch-pent", "flip-tri", "sl-rect", "docs", "processes", "flag", "bow-rect", "cross-circ",
    "tag-doc", "tag-rect", "manual-file", "manual-input", "procs", "paper-tape",
)
# ISO 5807 semantic kinds (the legacy IR vocabulary) -> typed shape.
_fc_KINDS = {
    "terminator": "stadium",
    "process": "rect",
    "decision": "diamond",
    "io": "lean-r",
    "subprocess": "subproc",
    "document": "doc",
    "store": "cyl",
    "connector": "circle",
}
_fc_FA_PREFIXES = ("fa", "fab", "fas", "far", "fal", "fad", "fak")
_fc_FA_NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
_fc_ICON_NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*:[a-z0-9]+(-[a-z0-9]+)*")
_fc_CURVES = (
    "basis", "bumpX", "bumpY", "cardinal", "catmullRom", "linear", "monotoneX", "monotoneY",
    "natural", "step", "stepAfter", "stepBefore",
)
_fc_STROKES = ("normal", "thick", "dotted", "invisible")
_fc_HEADS = {"arrow": ">", "none": "", "circle": "o", "cross": "x"}
_fc_TAILS = {"arrow": "<", "circle": "o", "cross": "x"}
# Legacy edge kinds -> (stroke, head).
_fc_EDGE_KINDS = {
    "normal": ("normal", "arrow"),
    "dependency": ("normal", "arrow"),
    "conditional": ("dotted", "arrow"),
    "weak": ("dotted", "arrow"),
    "strong": ("thick", "arrow"),
}
_fc_LINK_KEYS = (
    "kind", "stroke", "head", "bidirectional", "length", "label", "labelType", "labelForm", "id",
    "animate", "animation", "curve",
)
_fc_URL = (
    r"^(?!https?://[A-Za-z0-9._~:/?=&+!$*,'()@-]+$)",
    "must be an http(s) URL without spaces, quotes, '#', '%', ';', '<', '>', brackets or braces",
)

text_context("flowchart.title")
text_context("flowchart.label", encode=ENTITY)
text_context("flowchart.markdown", encode=ENTITY, allow_newline=True)
text_context(
    "flowchart.tooltip",
    encode=ENTITY,
    reject="<>",
    reject_patterns=((r"-->", "a tooltip containing '-->' is dropped by Mermaid's sanitizer"),),
)
text_context("flowchart.url", reject_patterns=(_fc_URL,))
text_context(
    "flowchart.color",
    reject_patterns=((r"^(?!#(?:[0-9A-Fa-f]{3,4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$|[a-z]+$)",
                      "must be #hex or a lowercase CSS color name (parentheses do not parse in flowchart styles)"),),
)

_fc_SIZE = re.compile(r"\d+(\.\d+)?(px|pt|em|rem)?")
_fc_DASH = re.compile(r"\d+(\.\d+)?( \d+(\.\d+)?)*")
_fc_DURATION = re.compile(r"\d+(\.\d+)?m?s")
_fc_FONT_WEIGHTS = ("normal", "bold", "bolder", "lighter", "100", "200", "300", "400", "500", "600",
                    "700", "800", "900")
# IR style key -> CSS property, in emission order.
_fc_STYLE_KEYS = {
    "fill": "fill",
    "stroke": "stroke",
    "strokeWidth": "stroke-width",
    "strokeDasharray": "stroke-dasharray",
    "strokeDashoffset": "stroke-dashoffset",
    "color": "color",
    "fontSize": "font-size",
    "fontWeight": "font-weight",
    "fontStyle": "font-style",
    "animation": "animation",
}

_fc_CONFIG = {
    "theme": ("enum", ("default", "base", "dark", "forest", "neutral", "neo", "neo-dark", "redux",
                       "redux-dark", "redux-color", "redux-dark-color")),
    "look": ("enum", ("classic", "handDrawn", "neo")),
    "layout": ("enum", ("dagre", "elk")),
    "markdownAutoWrap": ("boolean",),
    "flowchart": {
        "curve": ("enum", _fc_CURVES),
        "nodeSpacing": ("number", 0, None),
        "rankSpacing": ("number", 0, None),
        "padding": ("number", 0, None),
        "diagramPadding": ("number", 0, None),
        "wrappingWidth": ("number", 0, None),
        "minNodeWidth": ("number", 0, None),
        "titleTopMargin": ("number", 0, None),
        "subGraphTitleMargin": {"top": ("number", 0, None), "bottom": ("number", 0, None)},
        "inheritDir": ("boolean",),
        "useMaxWidth": ("boolean",),
    },
}


def _fc_ident(v: Validator, value: Any, path: str, what: str = "id") -> str:
    v.ident(value, path, _fc_ID)
    if value in _fc_RESERVED:
        raise v.error(path, f"{value!r} is a flowchart keyword and cannot be a {what}")
    return value


def _fc_style(v: Validator, value: Any, path: str) -> str:
    """Typed style object -> `fill:#f9f,stroke-width:4px` (closed key set, validated values)."""
    style = v.fields(value, path, optional=tuple(_fc_STYLE_KEYS))
    if not style:
        raise v.error(path, "must set at least one style property")
    parts = []
    for key, css in _fc_STYLE_KEYS.items():
        if key not in style:
            continue
        sub, item = ptr(path, key), style[key]
        if key in ("fill", "stroke", "color"):
            text = v.text(item, sub, "flowchart.color")
        elif key in ("strokeWidth", "fontSize"):
            if not isinstance(item, str) or not _fc_SIZE.fullmatch(item):
                raise v.error(sub, f"must be a size such as '4px', got {json.dumps(item)}")
            text = item
        elif key == "strokeDasharray":
            if not isinstance(item, str) or not _fc_DASH.fullmatch(item):
                raise v.error(sub, f"must be space-separated lengths such as '5 5', got {json.dumps(item)}")
            text = item
        elif key == "strokeDashoffset":
            text = v.number(item, sub, 0)
        elif key == "fontWeight":
            text = v.enum(item, sub, _fc_FONT_WEIGHTS)
        elif key == "fontStyle":
            text = v.enum(item, sub, ("normal", "italic", "oblique"))
        else:
            anim = v.fields(item, sub, required=("name", "duration"), optional=("timing", "iterations"))
            words = [
                _fc_ident(v, anim["name"], ptr(sub, "name"), "keyframes name"),
                v.ident(anim["duration"], ptr(sub, "duration"), _fc_DURATION),
            ]
            if "timing" in anim:
                words.append(v.enum(anim["timing"], ptr(sub, "timing"),
                                    ("linear", "ease", "ease-in", "ease-out", "ease-in-out")))
            if "iterations" in anim:
                count = anim["iterations"]
                words.append("infinite" if count == "infinite" else v.number(count, ptr(sub, "iterations"), 1, integer=True))
            text = " ".join(words)
        parts.append(f"{css}:{text}")
    return ",".join(parts)


def _fc_label(v: Validator, obj: dict, path: str, markdown_ok: bool = True) -> str:
    """The quoted label of a node, subgraph or edge: `"text"` or a markdown string."""
    kind = v.enum(obj.get("labelType", "text"), ptr(path, "labelType"), ("text", "markdown"))
    if kind == "markdown":
        if not markdown_ok:
            raise v.error(ptr(path, "labelType"), "a markdown label needs a classic form (or no shape)")
        text = v.text(obj["label"], ptr(path, "label"), "flowchart.markdown")
        return f'"`{text}`"'
    return f'"{v.text(obj["label"], ptr(path, "label"), "flowchart.label")}"'


class _fc_Doc:
    """Ids declared in one document, collected before anything is emitted."""

    def __init__(self) -> None:
        self.nodes: dict[str, str] = {}  # id -> path
        self.subgraphs: dict[str, str] = {}
        self.edges: dict[str, str] = {}
        self.classes: set[str] = set()

    def claim(self, v: Validator, value: str, path: str) -> None:
        if value in self.nodes or value in self.subgraphs or value in self.edges:
            raise v.error(path, f"duplicate id {json.dumps(value)} (node, subgraph and edge ids share one namespace)")


def _fc_node(v: Validator, node: dict, path: str, doc: _fc_Doc) -> list[str]:
    """One node declaration (one or two lines)."""
    nid = node["id"]
    looks = [key for key in ("form", "shape", "kind", "icon", "image") if key in node]
    if len(looks) > 1:
        raise v.error(ptr(path, looks[1]), f"use only one of form, shape, kind, icon, image (got {looks[0]!r} too)")
    look = looks[0] if looks else None
    if "labelType" in node and "label" not in node:
        raise v.error(ptr(path, "labelType"), "labelType needs a label")
    if "faIcon" in node and look != "form":
        raise v.error(ptr(path, "faIcon"), "a Font Awesome label icon needs a classic `form`")
    cls = None
    if "class" in node:
        cls = v.ref(node["class"], ptr(path, "class"), doc.classes)
    lines: list[str] = []
    if look is None or look == "form":
        form = v.enum(node.get("form", "rect"), ptr(path, "form"), _fc_FORMS) if look else ("[", "]")
        if "label" not in node and "faIcon" not in node:
            if look:
                raise v.error(ptr(path, "label"), "a classic form needs a label (or a faIcon)")
            head = nid
        else:
            if "faIcon" in node:
                fpath = ptr(path, "faIcon")
                icon = v.fields(node["faIcon"], fpath, required=("prefix", "name"))
                prefix = v.enum(icon["prefix"], ptr(fpath, "prefix"), _fc_FA_PREFIXES)
                name = v.ident(icon["name"], ptr(fpath, "name"), _fc_FA_NAME)
                if v.enum(node.get("labelType", "text"), ptr(path, "labelType"), ("text", "markdown")) == "markdown":
                    raise v.error(ptr(path, "labelType"), "a markdown label cannot carry a Font Awesome icon")
                text = f"{prefix}:fa-{name}"
                if "label" in node:
                    text += " " + v.text(node["label"], ptr(path, "label"), "flowchart.label")
                label = f'"{text}"'
            else:
                label = _fc_label(v, node, path)
            head = f"{nid}{form[0]}{label}{form[1]}"
        if cls:
            head += f":::{cls}"
        return [head]
    props: list[str] = []
    if look in ("shape", "kind"):
        if look == "shape":
            shape = v.enum(node["shape"], ptr(path, "shape"), _fc_SHAPES)
        else:
            shape = v.enum(node["kind"], ptr(path, "kind"), _fc_KINDS)
        props.append(f"shape: {shape}")
        if "label" in node:
            props.append(f"label: {_fc_label(v, node, path, markdown_ok=False)}")
    elif look == "icon":
        ipath = ptr(path, "icon")
        icon = v.fields(node["icon"], ipath, required=("name",), optional=("form", "pos", "h"))
        props.append(f'icon: "{v.ident(icon["name"], ptr(ipath, "name"), _fc_ICON_NAME)}"')
        if "form" in icon:
            props.append(f'form: "{v.enum(icon["form"], ptr(ipath, "form"), ("square", "circle", "rounded"))}"')
        if "label" in node:
            props.append(f"label: {_fc_label(v, node, path, markdown_ok=False)}")
        if "pos" in icon:
            props.append(f'pos: "{v.enum(icon["pos"], ptr(ipath, "pos"), ("t", "b"))}"')
        if "h" in icon:
            props.append(f"h: {v.number(icon['h'], ptr(ipath, 'h'), 48)}")
    else:
        ipath = ptr(path, "image")
        image = v.fields(node["image"], ipath, required=("url",), optional=("pos", "w", "h", "constraint"))
        props.append(f'img: "{v.text(image["url"], ptr(ipath, "url"), "flowchart.url")}"')
        if "label" in node:
            props.append(f"label: {_fc_label(v, node, path, markdown_ok=False)}")
        if "pos" in image:
            props.append(f'pos: "{v.enum(image["pos"], ptr(ipath, "pos"), ("t", "b"))}"')
        for key in ("w", "h"):
            if key in image:
                props.append(f"{key}: {v.number(image[key], ptr(ipath, key), 1)}")
        if "constraint" in image:
            props.append(f'constraint: "{v.enum(image["constraint"], ptr(ipath, "constraint"), ("on", "off"))}"')
    lines.append(f"{nid}@{{ {', '.join(props)} }}")
    if cls:
        lines.append(f"{nid}:::{cls}")
    return lines


def _fc_endpoints(v: Validator, value: Any, path: str, doc: _fc_Doc) -> list[str]:
    """`from`/`to`: an id, an `{id, class}` object, or a list of them (`A & B`)."""
    items = value if isinstance(value, list) else [value]
    if isinstance(value, list):
        v.array(value, path, min_items=2)
    known = set(doc.nodes) | set(doc.subgraphs)
    out = []
    for i, item in enumerate(items):
        ipath = ptr(path, i) if isinstance(value, list) else path
        if isinstance(item, dict):
            v.fields(item, ipath, required=("id", "class"))
            ref = v.ref(item["id"], ptr(ipath, "id"), known)
            if ref in doc.subgraphs:
                raise v.error(ptr(ipath, "class"), "':::' applies to nodes, not subgraphs")
            out.append(f"{ref}:::{v.ref(item['class'], ptr(ipath, 'class'), doc.classes)}")
        else:
            out.append(v.ref(item, ipath, known))
    return out


def _fc_link(v: Validator, link: dict, path: str, single: bool, doc: _fc_Doc, meta: list[str]) -> str:
    """The link token between two endpoint groups, with its id and text."""
    if "kind" in link:
        for key in ("stroke", "head"):
            if key in link:
                raise v.error(ptr(path, key), "use either the legacy `kind` or stroke/head")
        stroke, head = v.enum(link["kind"], ptr(path, "kind"), _fc_EDGE_KINDS)
    else:
        stroke = v.enum(link.get("stroke", "normal"), ptr(path, "stroke"), _fc_STROKES)
        head = v.enum(link.get("head", "none" if stroke == "invisible" else "arrow"), ptr(path, "head"), tuple(_fc_HEADS))
    both = v.boolean(link.get("bidirectional", False), ptr(path, "bidirectional"))
    length = int(v.number(link.get("length", 1), ptr(path, "length"), 1, 8, integer=True))
    if stroke == "invisible":
        for key in ("head", "bidirectional", "length", "label"):
            if key in link and (key != "head" or head != "none"):
                raise v.error(ptr(path, key), "an invisible link (~~~) takes no arrowhead, length or label")
    if both and head == "none":
        raise v.error(ptr(path, "bidirectional"), "a link without an arrowhead cannot be bidirectional")
    tail = _fc_TAILS[head] if both else ""
    mark = _fc_HEADS[head]
    form = v.enum(link.get("labelForm", "pipe"), ptr(path, "labelForm"), ("pipe", "inline"))
    if "labelForm" in link and "label" not in link:
        raise v.error(ptr(path, "labelForm"), "labelForm needs a label")
    if "labelType" in link and "label" not in link:
        raise v.error(ptr(path, "labelType"), "labelType needs a label")
    label = _fc_label(v, link, path) if "label" in link else None

    def line(n: int) -> str:
        if stroke == "normal":
            return "-" * (n + 1) + (mark or "-")
        if stroke == "thick":
            return "=" * (n + 1) + (mark or "=")
        return "-" + "." * n + "-" + mark

    if stroke == "invisible":
        token = "~~~"
    elif label is not None and form == "inline":
        opener = {"normal": "--", "thick": "==", "dotted": "-."}[stroke]
        if stroke == "dotted":
            closer = "." * length + "-" + mark
        else:
            closer = line(length)
        token = f"{tail}{opener} {label} {closer}"
        label = None
    else:
        token = tail + line(length)
    if label is not None:
        token += f"|{label}|"
    prefix = ""
    if "id" in link:
        ipath = ptr(path, "id")
        if not single:
            raise v.error(ipath, "an edge id names one link; it cannot be used with `&` lists")
        eid = _fc_ident(v, link["id"], ipath, "edge id")
        doc.claim(v, eid, ipath)
        doc.edges[eid] = ipath
        prefix = f"{eid}@"
        props = []
        if "animate" in link:
            props.append(f"animate: {'true' if v.boolean(link['animate'], ptr(path, 'animate')) else 'false'}")
        if "animation" in link:
            props.append(f"animation: {v.enum(link['animation'], ptr(path, 'animation'), ('fast', 'slow'))}")
        if "curve" in link:
            props.append(f"curve: {v.enum(link['curve'], ptr(path, 'curve'), _fc_CURVES)}")
        if props:
            meta.append(f"{eid}@{{ {', '.join(props)} }}")
    else:
        for key in ("animate", "animation", "curve"):
            if key in link:
                raise v.error(ptr(path, key), "edge metadata needs an edge `id`")
    return prefix + token


def _fc_serialize(ir: dict, keyword: str) -> str:
    v = Validator(keyword)
    v.fields(
        ir, "", required=("nodes",),
        optional=("title", "config", "accessibility", "comment", "direction", "semicolons", "edges",
                  "subgraphs", "groups", "classDefs", "classes", "styles", "linkStyles", "clicks"),
    )
    title = v.text(ir["title"], "/title", "flowchart.title") if "title" in ir else None
    config = validate_config(v, ir["config"], "/config", _fc_CONFIG) if "config" in ir else None
    direction = v.enum(ir.get("direction", "TD"), "/direction", _fc_DIRECTIONS)
    semi = ";" if v.boolean(ir.get("semicolons", False), "/semicolons") else ""
    doc = _fc_Doc()

    # Class definitions first: `:::` and `class` statements reference them.
    def_lines: list[str] = []
    for i, cdef in enumerate(v.array(ir.get("classDefs", []), "/classDefs")):
        cpath = ptr("/classDefs", i)
        v.fields(cdef, cpath, required=("names", "style"))
        names = []
        for j, name in enumerate(v.array(cdef["names"], ptr(cpath, "names"), min_items=1)):
            npath = ptr(ptr(cpath, "names"), j)
            if name != "default":
                _fc_ident(v, name, npath, "class name")
            names.append(v.unique(name, npath, doc.classes, "class name"))
        def_lines.append(f"    classDef {','.join(names)} {_fc_style(v, cdef['style'], ptr(cpath, 'style'))}")
    doc.classes.discard("default")

    # Subgraphs (`groups` is the legacy name of a flat list), then nodes.
    if "subgraphs" in ir and "groups" in ir:
        raise v.error("/groups", "use either subgraphs or the legacy groups, not both")
    sub_key = "groups" if "groups" in ir else "subgraphs"
    subgraph_list = v.array(ir.get(sub_key, []), f"/{sub_key}")

    def collect(groups: list, path: str) -> None:
        for i, group in enumerate(groups):
            gpath = ptr(path, i)
            optional = ("label", "labelType", "direction", "view") + (("subgraphs",) if sub_key == "subgraphs" else ())
            v.fields(group, gpath, required=("id",), optional=optional)
            gid = _fc_ident(v, group["id"], ptr(gpath, "id"), "subgraph id")
            doc.claim(v, gid, ptr(gpath, "id"))
            doc.subgraphs[gid] = gpath
            collect(v.array(group.get("subgraphs", []), ptr(gpath, "subgraphs")), ptr(gpath, "subgraphs"))

    collect(subgraph_list, f"/{sub_key}")

    nodes = v.array(ir["nodes"], "/nodes", min_items=1)
    members: dict[str | None, list[tuple[dict, str]]] = {}
    for i, node in enumerate(nodes):
        npath = ptr("/nodes", i)
        v.fields(node, npath, required=("id",),
                 optional=("label", "labelType", "form", "shape", "kind", "icon", "image", "faIcon", "class", "group"))
        nid = _fc_ident(v, node["id"], ptr(npath, "id"), "node id")
        doc.claim(v, nid, ptr(npath, "id"))
        doc.nodes[nid] = npath
        group = v.ref(node["group"], ptr(npath, "group"), doc.subgraphs) if "group" in node else None
        members.setdefault(group, []).append((node, npath))

    body: list[str] = []
    meta: list[str] = []

    def emit_groups(groups: list, path: str, indent: str) -> None:
        for i, group in enumerate(groups):
            gpath = ptr(path, i)
            head = f"{indent}subgraph {group['id']}"
            if "label" in group:
                head += f" [{_fc_label(v, group, gpath)}]"
            elif "labelType" in group:
                raise v.error(ptr(gpath, "labelType"), "labelType needs a label")
            body.append(head)
            inner = indent + "    "
            if "direction" in group:
                body.append(f"{inner}direction {v.enum(group['direction'], ptr(gpath, 'direction'), _fc_SUB_DIRECTIONS)}")
            for node, npath in members.get(group["id"], []):
                body.extend(f"{inner}{line}{semi}" for line in _fc_node(v, node, npath, doc))
            emit_groups(group.get("subgraphs", []), ptr(gpath, "subgraphs"), inner)
            body.append(f"{indent}end")
            if "view" in group:
                meta.append(f"{group['id']}@{{ view: {v.enum(group['view'], ptr(gpath, 'view'), ('collapsed', 'expanded'))} }}")

    emit_groups(subgraph_list, f"/{sub_key}", "    ")
    for node, npath in members.get(None, []):
        body.extend(f"    {line}{semi}" for line in _fc_node(v, node, npath, doc))

    # Edges: `from link to [link to ...]`; each `&` list multiplies the link count.
    link_count = 0
    for i, edge in enumerate(v.array(ir.get("edges", []), "/edges")):
        epath = ptr("/edges", i)
        v.fields(edge, epath, required=("from", "to"), optional=_fc_LINK_KEYS + ("then",))
        left = _fc_endpoints(v, edge["from"], ptr(epath, "from"), doc)
        right = _fc_endpoints(v, edge["to"], ptr(epath, "to"), doc)
        parts = [" & ".join(left), _fc_link(v, edge, epath, len(left) == len(right) == 1, doc, meta), " & ".join(right)]
        link_count += len(left) * len(right)
        for j, step in enumerate(v.array(edge.get("then", []), ptr(epath, "then"))):
            spath = ptr(ptr(epath, "then"), j)
            v.fields(step, spath, required=("to",), optional=_fc_LINK_KEYS)
            nxt = _fc_endpoints(v, step["to"], ptr(spath, "to"), doc)
            parts += [_fc_link(v, step, spath, len(right) == len(nxt) == 1, doc, meta), " & ".join(nxt)]
            link_count += len(right) * len(nxt)
            right = nxt
        body.append(f"    {' '.join(parts)}{semi}")

    tail: list[str] = list(def_lines)
    targets = set(doc.nodes) | set(doc.subgraphs) | set(doc.edges)
    for i, assign in enumerate(v.array(ir.get("classes", []), "/classes")):
        apath = ptr("/classes", i)
        v.fields(assign, apath, required=("ids", "class"))
        seen: set[str] = set()
        ids = [v.unique(v.ref(item, ptr(ptr(apath, "ids"), j), targets), ptr(ptr(apath, "ids"), j), seen)
               for j, item in enumerate(v.array(assign["ids"], ptr(apath, "ids"), min_items=1))]
        tail.append(f"    class {','.join(ids)} {v.ref(assign['class'], ptr(apath, 'class'), doc.classes)}")
    for i, item in enumerate(v.array(ir.get("styles", []), "/styles")):
        spath = ptr("/styles", i)
        v.fields(item, spath, required=("id", "style"))
        sid = v.ref(item["id"], ptr(spath, "id"), set(doc.nodes) | set(doc.subgraphs))
        tail.append(f"    style {sid} {_fc_style(v, item['style'], ptr(spath, 'style'))}")
    for i, item in enumerate(v.array(ir.get("linkStyles", []), "/linkStyles")):
        lpath = ptr("/linkStyles", i)
        v.fields(item, lpath, required=("links", "style"))
        if item["links"] == "default":
            which = "default"
        else:
            seen_links: set[str] = set()
            indexes = []
            for j, index in enumerate(v.array(item["links"], ptr(lpath, "links"), min_items=1)):
                ipath = ptr(ptr(lpath, "links"), j)
                text = v.number(index, ipath, 0, integer=True)
                if index >= link_count:
                    raise v.error(ipath, f"link {index} does not exist; the diagram has {link_count} link(s), counted from 0")
                indexes.append(v.unique(text, ipath, seen_links, "link index"))
            which = ",".join(indexes)
        tail.append(f"    linkStyle {which} {_fc_style(v, item['style'], ptr(lpath, 'style'))}")
    clicked: set[str] = set()
    for i, item in enumerate(v.array(ir.get("clicks", []), "/clicks")):
        cpath = ptr("/clicks", i)
        if not isinstance(item, dict):
            raise v.error(cpath, f"must be an object, got {type(item).__name__}")
        action = v.enum(item.get("action"), ptr(cpath, "action"), ("callback", "call", "url", "href"))
        if action in ("callback", "call"):
            v.fields(item, cpath, required=("id", "action", "function"), optional=("tooltip",))
        else:
            v.fields(item, cpath, required=("id", "action", "url"), optional=("tooltip", "target"))
        nid = v.ref(item["id"], ptr(cpath, "id"), doc.nodes)
        v.unique(nid, ptr(cpath, "id"), clicked, "click target")
        if action == "callback":
            line = f"click {nid} {_fc_ident(v, item['function'], ptr(cpath, 'function'), 'function name')}"
        elif action == "call":
            line = f"click {nid} call {_fc_ident(v, item['function'], ptr(cpath, 'function'), 'function name')}()"
        else:
            url = v.text(item["url"], ptr(cpath, "url"), "flowchart.url")
            line = f'click {nid} {"href " if action == "href" else ""}"{url}"'
        if "tooltip" in item:
            line += f' "{v.text(item["tooltip"], ptr(cpath, "tooltip"), "flowchart.tooltip")}"'
        if "target" in item:
            line += " " + v.enum(item["target"], ptr(cpath, "target"), ("_self", "_blank", "_parent", "_top"))
        tail.append(f"    {line}")

    lines = emit_frontmatter(title, config) + [f"{keyword} {direction}"]
    lines += emit_accessibility(v, ir)
    lines += emit_comment(v, ir)
    lines += body + [f"    {line}" for line in meta] + tail
    return "\n".join(lines) + "\n"


_fc_FEATURES = {
    "flowchart.keyword-flowchart": "/target=flowchart",
    "flowchart.keyword-graph": "/target=graph",
    "flowchart.keyword-flowchart-elk": "/target=flowchart-elk",
    "flowchart.direction-tb": "/direction=TB",
    "flowchart.direction-td": "/direction=TD",
    "flowchart.direction-bt": "/direction=BT",
    "flowchart.direction-rl": "/direction=RL",
    "flowchart.direction-lr": "/direction=LR",
    "flowchart.node-id": "/nodes/*/id=bare",
    "flowchart.node-text": "/nodes/*/form=rect",
    "flowchart.node-unicode-text": "/nodes/*/label=This ❤ Unicode",
    "flowchart.node-quoted-special-chars": "/nodes/*/label=The (text) in the box",
    "flowchart.entity-codes": '/nodes/*/label=A double quote:"',
    "flowchart.node-round": "/nodes/*/form=round",
    "flowchart.node-stadium": "/nodes/*/form=stadium",
    "flowchart.node-subroutine": "/nodes/*/form=subroutine",
    "flowchart.node-cylinder": "/nodes/*/form=cylinder",
    "flowchart.node-circle": "/nodes/*/form=circle",
    "flowchart.node-asymmetric": "/nodes/*/form=asymmetric",
    "flowchart.node-rhombus": "/nodes/*/form=rhombus",
    "flowchart.node-hexagon": "/nodes/*/form=hexagon",
    "flowchart.node-parallelogram": "/nodes/*/form=parallelogram",
    "flowchart.node-parallelogram-alt": "/nodes/*/form=parallelogram-alt",
    "flowchart.node-trapezoid": "/nodes/*/form=trapezoid",
    "flowchart.node-trapezoid-alt": "/nodes/*/form=trapezoid-alt",
    "flowchart.node-double-circle": "/nodes/*/form=double-circle",
    "flowchart.shape-syntax": "/nodes/*/shape",
    **{f"flowchart.shape-{shape}": f"/nodes/*/shape={shape}" for shape in _fc_SHAPES},
    "flowchart.icon-shape": "/nodes/*/icon/name",
    "flowchart.icon-form-square": "/nodes/*/icon/form=square",
    "flowchart.icon-form-circle": "/nodes/*/icon/form=circle",
    "flowchart.icon-form-rounded": "/nodes/*/icon/form=rounded",
    "flowchart.icon-pos-t": "/nodes/*/icon/pos=t",
    "flowchart.icon-pos-b": "/nodes/*/icon/pos=b",
    "flowchart.icon-height": "/nodes/*/icon/h",
    "flowchart.image-shape": "/nodes/*/image/url",
    "flowchart.image-pos-t": "/nodes/*/image/pos=t",
    "flowchart.image-pos-b": "/nodes/*/image/pos=b",
    "flowchart.image-width": "/nodes/*/image/w",
    "flowchart.image-height": "/nodes/*/image/h",
    "flowchart.image-constraint-on": "/nodes/*/image/constraint=on",
    "flowchart.image-constraint-off": "/nodes/*/image/constraint=off",
    "flowchart.link-arrow": "/edges/0/head=arrow",
    "flowchart.link-open": "/edges/1/head=none",
    "flowchart.link-open-text-inline": "/edges/2/labelForm=inline",
    "flowchart.link-open-text-pipe": "/edges/3/labelForm=pipe",
    "flowchart.link-arrow-text-pipe": "/edges/4/labelForm=pipe",
    "flowchart.link-arrow-text-inline": "/edges/5/labelForm=inline",
    "flowchart.link-dotted": "/edges/6/stroke=dotted",
    "flowchart.link-dotted-open": "/edges/7/head=none",
    "flowchart.link-dotted-text": "/edges/8/label",
    "flowchart.link-thick": "/edges/9/stroke=thick",
    "flowchart.link-thick-open": "/edges/10/head=none",
    "flowchart.link-thick-text": "/edges/11/label",
    "flowchart.link-invisible": "/edges/*/stroke=invisible",
    "flowchart.link-circle": "/edges/13/head=circle",
    "flowchart.link-cross": "/edges/14/head=cross",
    "flowchart.link-multi-circle": "/edges/15/bidirectional=true",
    "flowchart.link-multi-arrow": "/edges/16/bidirectional=true",
    "flowchart.link-multi-cross": "/edges/17/bidirectional=true",
    "flowchart.link-chaining": "/edges/*/then/*/to",
    "flowchart.link-ampersand": "/edges/*/from/1",
    "flowchart.link-length-normal": "/edges/20/length=2",
    "flowchart.link-length-normal-arrow": "/edges/21/length=2",
    "flowchart.link-length-thick": "/edges/22/length=2",
    "flowchart.link-length-thick-arrow": "/edges/23/length=2",
    "flowchart.link-length-dotted": "/edges/24/length=2",
    "flowchart.link-length-dotted-arrow": "/edges/25/length=2",
    "flowchart.link-length-with-text": "/edges/26/length=3",
    "flowchart.edge-id": "/edges/*/id",
    "flowchart.edge-animate": "/edges/*/animate=true",
    "flowchart.edge-animation-fast": "/edges/*/animation=fast",
    "flowchart.edge-animation-slow": "/edges/*/animation=slow",
    "flowchart.edge-class-animation": "/classes/*/ids/*=a4",
    **{f"flowchart.edge-curve-{curve.lower()}": f"/edges/*/curve={curve}" for curve in _fc_CURVES},
    "flowchart.subgraph": "/subgraphs/*/id=one",
    "flowchart.subgraph-explicit-id": "/subgraphs/*/label=Collapsed group",
    "flowchart.subgraph-edges": "/edges/47/from=one",
    "flowchart.subgraph-direction": "/subgraphs/*/direction",
    "flowchart.subgraph-collapsed": "/subgraphs/*/view=collapsed",
    "flowchart.subgraph-expanded": "/subgraphs/*/view=expanded",
    "flowchart.markdown-node-label": "/nodes/*/labelType=markdown",
    "flowchart.markdown-edge-label": "/edges/*/labelType=markdown",
    "flowchart.markdown-subgraph-label": "/subgraphs/*/labelType=markdown",
    "flowchart.click-callback": "/clicks/*/action=callback",
    "flowchart.click-call": "/clicks/*/action=call",
    "flowchart.click-url": "/clicks/*/action=url",
    "flowchart.click-href": "/clicks/*/action=href",
    "flowchart.click-target-self": "/clicks/*/target=_self",
    "flowchart.click-target-blank": "/clicks/*/target=_blank",
    "flowchart.click-target-parent": "/clicks/*/target=_parent",
    "flowchart.click-target-top": "/clicks/*/target=_top",
    "flowchart.comment": "/comment",
    "flowchart.statement-semicolon": "/semicolons=true",
    "flowchart.linkstyle-index": "/linkStyles/0/links/0",
    "flowchart.linkstyle-list": "/linkStyles/1/links/1",
    "flowchart.linkstyle-default": "/linkStyles/*/links=default",
    "flowchart.style-node": "/styles/*/style",
    "flowchart.classdef": "/classDefs/*/names/0",
    "flowchart.classdef-multi": "/classDefs/*/names/1",
    "flowchart.classdef-default": "/classDefs/*/names/*=default",
    "flowchart.class-apply": "/classes/*/ids/0",
    "flowchart.class-apply-list": "/classes/*/ids/1",
    "flowchart.class-shorthand": "/nodes/*/class",
    "flowchart.class-shorthand-ampersand": "/edges/*/from/*/class",
    **{f"flowchart.fontawesome-{prefix}": f"/nodes/*/faIcon/prefix={prefix}" for prefix in _fc_FA_PREFIXES},
}

register(Builder(
    "flowchart", "graph", _fc_KEYWORDS, _fc_serialize,
    text_fields=(
        "/title",
        "/comment",
        "/accessibility/title",
        "/accessibility/description",
        "/nodes/*/label",  # first match: a classic rect label
        "/nodes/18/label",  # typed shape
        "/nodes/69/label",  # icon
        "/nodes/72/label",  # image
        "/nodes/74/label",  # markdown
        "/nodes/82/label",  # after a Font Awesome icon
        "/subgraphs/*/label",  # first match: markdown subgraph title
        "/subgraphs/2/label",  # plain subgraph title
        "/subgraphs/*/subgraphs/*/label",
        "/edges/*/label",  # first match: inline open link text
        "/edges/3/label",  # pipe text
        "/edges/8/label",  # dotted inline
        "/edges/11/label",  # thick inline
        "/edges/26/label",  # inline with extra length
        "/edges/43/label",  # markdown edge text
        "/edges/*/then/*/label",
        "/clicks/*/tooltip",
    ),
    features=_fc_FEATURES,
    probes={"object": "/nodes/69/icon", "number": "/nodes/69/icon/h", "enum": "/nodes/19/shape",
            "ref": "/edges/0/to"},
))

# --- end flowchart ---

# --- sequenceDiagram ---
#
# IR: participants in `actors` (participants, actors and boxes, in declaration order) and a
# typed nested tree of `steps` (messages, activations, notes, create/destroy, and the control
# blocks loop/opt/break/rect/alt/par/critical). Validation walks the steps in source order,
# the way Mermaid does, so lifecycle and activation errors are caught before any output.

_seq_ARROWS = {
    "solid-open": "->",
    "dotted-open": "-->",
    "solid": "->>",
    "dotted": "-->>",
    "solid-bidirectional": "<<->>",
    "dotted-bidirectional": "<<-->>",
    "solid-cross": "-x",
    "dotted-cross": "--x",
    "solid-async": "-)",
    "dotted-async": "--)",
    "half-solid-top": "-|\\",
    "half-dotted-top": "--|\\",
    "half-solid-bottom": "-|/",
    "half-dotted-bottom": "--|/",
    "half-solid-reverse-top": "/|-",
    "half-dotted-reverse-top": "/|--",
    "half-solid-reverse-bottom": "\\|-",
    "half-dotted-reverse-bottom": "\\|--",
    "stick-solid-top": "-\\\\",
    "stick-dotted-top": "--\\\\",
    "stick-solid-bottom": "-//",
    "stick-dotted-bottom": "--//",
    "stick-solid-reverse-top": "//-",
    "stick-dotted-reverse-top": "//--",
    "stick-solid-reverse-bottom": "\\\\-",
    "stick-dotted-reverse-bottom": "\\\\--",
    # Legacy names kept for backward compatibility.
    "sync": "->>",
    "async": "-)",
    "reply": "-->>",
    "cross": "-x",
}

_seq_SYMBOLS = ("boundary", "control", "entity", "database", "collections", "queue")

# Lexer keywords (case-insensitive, word-bounded) that cannot be participant ids.
_seq_RESERVED = {
    "box", "participant", "actor", "create", "destroy", "as", "loop", "rect", "opt", "alt",
    "else", "par", "par_over", "and", "critical", "option", "break", "end", "left", "right",
    "of", "links", "link", "properties", "details", "over", "note", "activate", "deactivate",
    "title", "acctitle", "accdescr", "sequencediagram", "autonumber", "off", "wrap", "nowrap",
}

_seq_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

# CSS named colors. Mermaid only treats a box's first word as a color when the browser
# supports it, so a box or rect color must be one of these or an rgb()/rgba()/hsl()/hsla().
_seq_COLOR_NAMES = frozenset(
    """aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue
    blueviolet brown burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk
    crimson cyan darkblue darkcyan darkgoldenrod darkgray darkgreen darkgrey darkkhaki
    darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen
    darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue
    dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite
    gold goldenrod gray green greenyellow grey honeydew hotpink indianred indigo ivory khaki
    lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan
    lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen
    lightskyblue lightslategray lightslategrey lightsteelblue lightyellow lime limegreen linen
    magenta maroon mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen
    mediumslateblue mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream
    mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered orchid
    palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru pink plum
    powderblue purple rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown
    seagreen seashell sienna silver skyblue slateblue slategray slategrey snow springgreen
    steelblue tan teal thistle tomato turquoise violet wheat white whitesmoke yellow
    yellowgreen transparent""".split()
)
_seq_COLOR_FN = re.compile(
    r"(rgb|hsl)a?\(\s*\d{1,3}(\.\d+)?%?(\s*,\s*\d{1,3}(\.\d+)?%?){2}(\s*,\s*(0|1|0?\.\d+|1\.0+|\d{1,3}%))?\s*\)"
)

# Characters that end or split a statement (`#` comment, `;` separator, `:` before a
# `wrap:` directive), or that would be read as markup, entities or KaTeX (`$$`), are written
# as entity codes, which Mermaid renders back verbatim.
_seq_TEXT_ENCODE = {char: ENTITY[char] for char in '#;:<>"&%{}\\'}
_seq_TEXT_ENCODE["$"] = "#36;"
_seq_TEXT_ENCODE["\n"] = "<br/>"

text_context("sequenceDiagram.message", encode=_seq_TEXT_ENCODE, allow_newline=True)
text_context("sequenceDiagram.note", encode=_seq_TEXT_ENCODE, allow_newline=True)
# Block and branch labels are always word-wrapped to the block width, and the wrapper can
# split an entity code in half, so they carry raw text only and reject what needs encoding.
text_context(
    "sequenceDiagram.block",
    reject="#;<",
    reject_patterns=(
        (r"\$\$", "'$$' starts KaTeX math"),
        (r"(?i)^:?(no)?wrap:", "a leading 'wrap:' or 'nowrap:' is read as a wrap directive"),
    ),
)
text_context("sequenceDiagram.box", encode=_seq_TEXT_ENCODE)
text_context("sequenceDiagram.alias", encode=_seq_TEXT_ENCODE, allow_newline=True)
text_context("sequenceDiagram.inline-alias", encode=_seq_TEXT_ENCODE, allow_newline=True)
text_context("sequenceDiagram.link-label", encode=_seq_TEXT_ENCODE)
text_context("sequenceDiagram.title")
text_context(
    "sequenceDiagram.url",
    reject_patterns=((r"^(?!https?://[A-Za-z0-9._~:/?=&%+!$*,'()\[\]@-]+$)", "must be an http(s) URL without '#', ';', spaces or quotes"),),
)

_seq_CONFIG = {
    "theme": ("enum", ("default", "base", "dark", "forest", "neutral", "neo", "neo-dark", "redux", "redux-dark", "redux-color", "redux-dark-color", "null")),
    "look": ("enum", ("classic", "handDrawn", "neo")),
    "sequence": {
        "mirrorActors": ("boolean",),
        "bottomMarginAdj": ("number", 0, None),
        "actorFontSize": ("number", 1, None),
        "actorFontWeight": ("integer", 100, 900),
        "noteFontSize": ("number", 1, None),
        "noteFontWeight": ("integer", 100, 900),
        "noteAlign": ("enum", ("left", "center", "right")),
        "messageFontSize": ("number", 1, None),
        "messageFontWeight": ("integer", 100, 900),
        "messageAlign": ("enum", ("left", "center", "right")),
        "showSequenceNumbers": ("boolean",),
        "diagramMarginX": ("number", 0, None),
        "diagramMarginY": ("number", 0, None),
        "boxTextMargin": ("number", 0, None),
        "noteMargin": ("number", 0, None),
        "messageMargin": ("number", 0, None),
        "hideUnusedParticipants": ("boolean",),
        "activationWidth": ("number", 1, None),
        "actorMargin": ("number", 0, None),
        "width": ("number", 1, None),
        "height": ("number", 1, None),
        "boxMargin": ("number", 0, None),
        "forceMenus": ("boolean",),
        "rightAngles": ("boolean",),
        "wrapPadding": ("number", 0, None),
    },
}

_seq_AUTONUMBER = re.compile(r"[0-9]+(\.[0-9]{1,2})?")


def _seq_id(v: Validator, value: Any, path: str) -> str:
    v.ident(value, path, _seq_ID)
    if value.lower() in _seq_RESERVED:
        raise v.error(path, f"{value!r} is a sequenceDiagram keyword and cannot be a participant id")
    return value


def _seq_color(v: Validator, value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise v.error(path, f"must be a string, got {type(value).__name__}")
    if value.lower() in _seq_COLOR_NAMES or _seq_COLOR_FN.fullmatch(value):
        return value
    raise v.error(path, "must be a CSS color name or rgb()/rgba()/hsl()/hsla() (hex starts a comment here)")


class _seq_State:
    """Source-order state: declared ids, open activations, lifecycle."""

    def __init__(self) -> None:
        self.known: set[str] = set()
        self.kinds: dict[str, str] = {}
        self.active: dict[str, list[str]] = {}  # id -> pointers of steps that opened an activation
        self.destroyed: set[str] = set()


def _seq_participant(v: Validator, item: dict, path: str, *, created: bool = False) -> tuple[str, str]:
    """Validate one participant object; return (id, declaration without the keyword prefix)."""
    optional = ("kind", "type", "alias", "inlineAlias")
    if not created:
        optional += ("implicit", "menu")
    v.fields(item, path, required=("id",), optional=optional)
    pid = _seq_id(v, item["id"], ptr(path, "id"))
    kind = v.enum(item.get("kind", "participant"), ptr(path, "kind"), ("participant", "actor"))
    implicit = v.boolean(item.get("implicit", False), ptr(path, "implicit"))
    if implicit:
        for key in ("kind", "type", "alias", "inlineAlias", "menu"):
            if key in item:
                raise v.error(ptr(path, key), "an implicit participant is created by its first message and takes no declaration keys")
    config: list[str] = []
    if "type" in item:
        if kind != "participant":
            raise v.error(ptr(path, "type"), "a symbol type applies to kind 'participant' only")
        config.append(f'"type": "{v.enum(item["type"], ptr(path, "type"), _seq_SYMBOLS)}"')
    if "inlineAlias" in item:
        if kind != "participant":
            raise v.error(ptr(path, "inlineAlias"), "an inline alias applies to kind 'participant' only")
        alias = v.text(item["inlineAlias"], ptr(path, "inlineAlias"), "sequenceDiagram.inline-alias")
        config.append(f'"alias": "{alias}"')
    decl = f"{kind} {pid}"
    if config:
        decl += "@{ " + ", ".join(config) + " }"
    if "alias" in item:
        decl += f" as {v.text(item['alias'], ptr(path, 'alias'), 'sequenceDiagram.alias')}"
    return pid, ("" if implicit else decl)


def _seq_menu(v: Validator, item: dict, path: str, pid: str) -> list[str]:
    if "menu" not in item:
        return []
    mpath = ptr(path, "menu")
    if item.get("kind", "participant") == "actor":
        raise v.error(mpath, "a menu on an actor crashes the renderer in 12.0.0; use a participant")
    menu = v.fields(item["menu"], mpath, required=("form", "items"))
    form = v.enum(menu["form"], ptr(mpath, "form"), ("link", "links"))
    items = v.array(menu["items"], ptr(mpath, "items"), min_items=1)
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for index, entry in enumerate(items):
        epath = ptr(ptr(mpath, "items"), index)
        v.fields(entry, epath, required=("label", "url"))
        label = v.text(entry["label"], ptr(epath, "label"), "sequenceDiagram.link-label")
        if "@" in entry["label"] and form == "link":
            raise v.error(ptr(epath, "label"), "'@' separates the label from the URL in a link statement")
        v.unique(entry["label"], ptr(epath, "label"), seen, "menu label")
        url = v.text(entry["url"], ptr(epath, "url"), "sequenceDiagram.url")
        entries.append((label, url))
    if form == "link":
        return [f"    link {pid}: {label} @ {url}" for label, url in entries]
    body = ", ".join(f'"{label}": "{url}"' for label, url in entries)
    return [f"    links {pid}: {{{body}}}"]


def _seq_actors(v: Validator, ir: dict, state: _seq_State) -> list[str]:
    lines: list[str] = []
    menus: list[str] = []
    items = v.array(ir.get("actors", []), "/actors")

    def declare(item: Any, path: str, indent: str) -> None:
        pid, decl = _seq_participant(v, item, path)
        v.unique(pid, ptr(path, "id"), state.known, "participant id")
        state.kinds[pid] = item.get("kind", "participant")
        if decl:
            lines.append(indent + decl)
        menus.extend(_seq_menu(v, item, path, pid))

    for index, item in enumerate(items):
        path = ptr("/actors", index)
        if isinstance(item, dict) and item.get("kind") == "box":
            v.fields(item, path, required=("kind", "actors"), optional=("label", "color"))
            head = _seq_color(v, item["color"], ptr(path, "color")) if "color" in item else "transparent"
            if "label" in item:
                label = v.text(item["label"], ptr(path, "label"), "sequenceDiagram.box")
                if "color" in item and _seq_COLOR_FN.fullmatch(item["color"]) and ")" in item["label"]:
                    raise v.error(ptr(path, "label"), "')' after an rgb()/hsl() box color is read as part of the color")
                head += f" {label}"
            lines.append(f"    box {head}")
            members = v.array(item["actors"], ptr(path, "actors"), min_items=1)
            for mindex, member in enumerate(members):
                mpath = ptr(ptr(path, "actors"), mindex)
                if isinstance(member, dict) and member.get("kind") == "box":
                    raise v.error(ptr(mpath, "kind"), "boxes cannot be nested")
                if isinstance(member, dict) and member.get("implicit") is True:
                    raise v.error(ptr(mpath, "implicit"), "a box member must be declared, not implicit")
                declare(member, mpath, "        ")
            lines.append("    end")
        else:
            declare(item, path, "    ")
    return lines + menus


def _seq_use(v: Validator, value: Any, path: str, state: _seq_State) -> str:
    return v.ref(value, path, state.known)


def _seq_steps(v: Validator, steps: Any, path: str, state: _seq_State, lines: list[str], indent: str) -> None:
    items = v.array(steps, path)
    for index, step in enumerate(items):
        spath = ptr(path, index)
        if not isinstance(step, dict):
            raise v.error(spath, f"must be an object, got {type(step).__name__}")
        kind = v.enum(step.get("type", "message"), ptr(spath, "type"), tuple(_seq_STEP_KINDS))
        following = items[index + 1] if index + 1 < len(items) else None
        _seq_STEP_KINDS[kind](v, step, spath, state, lines, indent, following)


def _seq_next_message(v: Validator, following: Any, spath: str, pid: str, roles: tuple[str, ...], what: str) -> None:
    ok = (
        isinstance(following, dict)
        and following.get("type", "message") == "message"
        and any(following.get(role) == pid for role in roles)
    )
    if not ok:
        raise v.error(spath, f"{what} must be followed directly by a message {' or '.join(roles)} {pid!r}")


def _seq_message(v, step, spath, state, lines, indent, _following) -> None:
    v.fields(step, spath, required=("from", "to", "label"), optional=("type", "arrow", "activation", "central"))
    src = _seq_use(v, step["from"], ptr(spath, "from"), state)
    dst = _seq_use(v, step["to"], ptr(spath, "to"), state)
    arrow_name = step.get("arrow", "solid")
    arrow = v.enum(arrow_name, ptr(spath, "arrow"), _seq_ARROWS)
    sign = ""
    if "activation" in step:
        activation = v.enum(step["activation"], ptr(spath, "activation"), {"activate": "+", "deactivate": "-"})
        if "central" in step:
            raise v.error(ptr(spath, "central"), "activation shorthand and a central connection do not combine")
        if activation == "+":
            state.active.setdefault(dst, []).append(ptr(spath, "activation"))
        else:
            if not state.active.get(src):
                raise v.error(ptr(spath, "activation"), f"{src!r} is not active; nothing to deactivate")
            state.active[src].pop()
            if dst[0] in "xX":
                raise v.error(ptr(spath, "to"), "'-' before an id starting with 'x' is read as a cross arrow")
        # A reverse solid arrow ends in '-'; '-' right after it would read as the dotted arrow.
        sign = (" " if arrow.endswith("-") and activation == "-" else "") + activation
    left = right = ""
    if "central" in step:
        central = v.enum(step["central"], ptr(spath, "central"), ("source", "target", "both"))
        left = "()" if central in ("source", "both") else ""
        right = "()" if central in ("target", "both") else ""
    label = v.text(step["label"], ptr(spath, "label"), "sequenceDiagram.message")
    lines.append(f"{indent}{src}{left}{arrow}{sign}{right}{dst}: {label}")


def _seq_activation(v, step, spath, state, lines, indent, _following) -> None:
    v.fields(step, spath, required=("type", "actor"))
    pid = _seq_use(v, step["actor"], ptr(spath, "actor"), state)
    if step["type"] == "activate":
        state.active.setdefault(pid, []).append(spath)
    elif not state.active.get(pid):
        raise v.error(ptr(spath, "actor"), f"{pid!r} is not active; nothing to deactivate")
    else:
        state.active[pid].pop()
    lines.append(f"{indent}{step['type']} {pid}")


def _seq_note(v, step, spath, state, lines, indent, _following) -> None:
    v.fields(step, spath, required=("type", "position", "actors", "text"))
    position = v.enum(step["position"], ptr(spath, "position"), {"left_of": "left of", "right_of": "right of", "over": "over"})
    actors = v.array(step["actors"], ptr(spath, "actors"), min_items=1)
    limit = 2 if position == "over" else 1
    if len(actors) > limit:
        raise v.error(ptr(spath, "actors"), f"a note {position} takes at most {limit} participant(s)")
    ids = [_seq_use(v, a, ptr(ptr(spath, "actors"), i), state) for i, a in enumerate(actors)]
    text = v.text(step["text"], ptr(spath, "text"), "sequenceDiagram.note")
    lines.append(f"{indent}Note {position} {','.join(ids)}: {text}")


def _seq_create(v, step, spath, state, lines, indent, following) -> None:
    v.fields(step, spath, required=("type", "participant"))
    ppath = ptr(spath, "participant")
    pid, decl = _seq_participant(v, step["participant"], ppath, created=True)
    v.unique(pid, ptr(ppath, "id"), state.known, "participant id")
    state.kinds[pid] = step["participant"].get("kind", "participant")
    _seq_next_message(v, following, spath, pid, ("to",), "create")
    lines.append(f"{indent}create {decl}")


def _seq_destroy(v, step, spath, state, lines, indent, following) -> None:
    v.fields(step, spath, required=("type", "actor"))
    pid = _seq_use(v, step["actor"], ptr(spath, "actor"), state)
    if pid in state.destroyed:
        raise v.error(ptr(spath, "actor"), f"{pid!r} is already destroyed")
    state.destroyed.add(pid)
    _seq_next_message(v, following, spath, pid, ("from", "to"), "destroy")
    lines.append(f"{indent}destroy {pid}")


def _seq_block(v, step, spath, state, lines, indent, _following) -> None:
    kind = step["type"]
    if kind == "rect":
        v.fields(step, spath, required=("type", "color", "steps"))
        head = f"rect {_seq_color(v, step['color'], ptr(spath, 'color'))}"
    else:
        v.fields(step, spath, required=("type", "steps"), optional=("label",))
        head = kind
        if "label" in step:
            head += " " + v.text(step["label"], ptr(spath, "label"), "sequenceDiagram.block")
    lines.append(indent + head)
    _seq_steps(v, step["steps"], ptr(spath, "steps"), state, lines, indent + "    ")
    lines.append(f"{indent}end")


_seq_BRANCH_WORDS = {"alt": "else", "par": "and", "critical": "option"}


def _seq_branched(v, step, spath, state, lines, indent, _following) -> None:
    v.fields(step, spath, required=("type", "branches"))
    branches = v.array(step["branches"], ptr(spath, "branches"), min_items=1)
    for index, branch in enumerate(branches):
        bpath = ptr(ptr(spath, "branches"), index)
        v.fields(branch, bpath, required=("steps",), optional=("label",))
        head = step["type"] if index == 0 else _seq_BRANCH_WORDS[step["type"]]
        if "label" in branch:
            head += " " + v.text(branch["label"], ptr(bpath, "label"), "sequenceDiagram.block")
        lines.append(indent + head)
        _seq_steps(v, branch["steps"], ptr(bpath, "steps"), state, lines, indent + "    ")
    lines.append(f"{indent}end")


_seq_STEP_KINDS = {
    "message": _seq_message,
    "activate": _seq_activation,
    "deactivate": _seq_activation,
    "note": _seq_note,
    "create": _seq_create,
    "destroy": _seq_destroy,
    "loop": _seq_block,
    "opt": _seq_block,
    "break": _seq_block,
    "rect": _seq_block,
    "alt": _seq_branched,
    "par": _seq_branched,
    "critical": _seq_branched,
}


def _seq_autonumber(v: Validator, ir: dict) -> list[str]:
    if "autonumber" not in ir:
        return []
    path = "/autonumber"
    value = ir["autonumber"]
    if value is True:
        return ["    autonumber"]
    if value is False:
        return []
    v.fields(value, path, required=("start",), optional=("increment",))
    parts = []
    for key in ("start", "increment"):
        if key in value:
            text = v.number(value[key], ptr(path, key), 0, exclusive_minimum=(key == "increment"))
            if not _seq_AUTONUMBER.fullmatch(text):
                raise v.error(ptr(path, key), "must be a non-negative number with at most 2 decimals")
            parts.append(text)
    return ["    autonumber " + " ".join(parts)]


def _seq_serialize(ir: dict, keyword: str) -> str:
    v = Validator(keyword)
    v.fields(
        ir, "", required=("actors", "steps"),
        optional=("title", "config", "accessibility", "comment", "autonumber"),
    )
    title = v.text(ir["title"], "/title", "sequenceDiagram.title") if "title" in ir else None
    config = validate_config(v, ir["config"], "/config", _seq_CONFIG) if "config" in ir else None
    lines = emit_frontmatter(title, config) + [keyword]
    lines += emit_accessibility(v, ir)
    lines += emit_comment(v, ir)
    lines += _seq_autonumber(v, ir)
    state = _seq_State()
    lines += _seq_actors(v, ir, state)
    _seq_steps(v, ir["steps"], "/steps", state, lines, "    ")
    for pid, opened in state.active.items():
        if opened:
            raise v.error(opened[0], f"activation of {pid!r} is never closed (Mermaid would not draw it)")
    return "\n".join(lines) + "\n"


register(Builder(
    "sequenceDiagram", "sequence", ("sequenceDiagram",), _seq_serialize,
    text_fields=(
        "/title",
        "/accessibility/title",
        "/accessibility/description",
        "/comment",
        "/actors/*/alias",
        "/actors/*/actors/*/alias",
        "/actors/*/actors/*/inlineAlias",
        "/actors/*/label",
        "/actors/3/label",
        "/actors/*/menu/items/*/label",
        "/actors/*/actors/*/menu/items/*/label",
        "/steps/*/label",
        "/steps/*/text",
        "/steps/52/label",
        "/steps/*/branches/*/label",
        "/steps/*/participant/alias",
        "/steps/*/participant/inlineAlias",
    ),
    features={
        "sequenceDiagram.keyword": "/target=sequenceDiagram",
        "sequenceDiagram.implicit-participant": "/actors/*/implicit=true",
        "sequenceDiagram.participant": "/actors/*/kind=participant",
        "sequenceDiagram.actor": "/actors/*/actors/*/kind=actor",
        "sequenceDiagram.type-boundary": "/actors/*/actors/*/type=boundary",
        "sequenceDiagram.type-control": "/actors/*/actors/*/type=control",
        "sequenceDiagram.type-entity": "/actors/*/actors/*/type=entity",
        "sequenceDiagram.type-database": "/actors/*/actors/*/type=database",
        "sequenceDiagram.type-collections": "/actors/*/actors/*/type=collections",
        "sequenceDiagram.type-queue": "/actors/*/actors/*/type=queue",
        "sequenceDiagram.alias-as": "/actors/*/actors/*/alias=Portal",
        "sequenceDiagram.alias-type-as": "/actors/6/actors/0/alias=Public API",
        "sequenceDiagram.alias-inline": "/actors/*/actors/*/inlineAlias=Auth Service",
        "sequenceDiagram.alias-precedence": "/actors/6/actors/2/alias=External",
        "sequenceDiagram.alias-line-break": "/actors/*/alias=Alice\nJohnson",
        "sequenceDiagram.create-participant": "/steps/*/participant/kind=participant",
        "sequenceDiagram.create-actor": "/steps/*/participant/kind=actor",
        "sequenceDiagram.destroy": "/steps/*/type=destroy",
        "sequenceDiagram.box-color-description": "/actors/0/label=Front end",
        "sequenceDiagram.box-description-only": "/actors/1/label=Group without description",
        "sequenceDiagram.box-rgb": "/actors/*/color=rgb(33,66,99)",
        "sequenceDiagram.box-rgba": "/actors/*/color=rgba(33,66,99,0.5)",
        "sequenceDiagram.box-hsl": "/actors/*/color=hsl(10, 40%, 90%)",
        "sequenceDiagram.box-hsla": "/actors/*/color=hsla(10, 40%, 90%, 0.5)",
        "sequenceDiagram.box-transparent": "/actors/*/color=transparent",
        "sequenceDiagram.arrow-solid-open": "/steps/*/arrow=solid-open",
        "sequenceDiagram.arrow-dotted-open": "/steps/*/arrow=dotted-open",
        "sequenceDiagram.arrow-solid": "/steps/*/arrow=solid",
        "sequenceDiagram.arrow-dotted": "/steps/*/arrow=dotted",
        "sequenceDiagram.arrow-solid-bidirectional": "/steps/*/arrow=solid-bidirectional",
        "sequenceDiagram.arrow-dotted-bidirectional": "/steps/*/arrow=dotted-bidirectional",
        "sequenceDiagram.arrow-solid-cross": "/steps/*/arrow=solid-cross",
        "sequenceDiagram.arrow-dotted-cross": "/steps/*/arrow=dotted-cross",
        "sequenceDiagram.arrow-solid-async": "/steps/*/arrow=solid-async",
        "sequenceDiagram.arrow-dotted-async": "/steps/*/arrow=dotted-async",
        "sequenceDiagram.half-solid-top": "/steps/*/arrow=half-solid-top",
        "sequenceDiagram.half-dotted-top": "/steps/*/arrow=half-dotted-top",
        "sequenceDiagram.half-solid-bottom": "/steps/*/arrow=half-solid-bottom",
        "sequenceDiagram.half-dotted-bottom": "/steps/*/arrow=half-dotted-bottom",
        "sequenceDiagram.half-solid-reverse-top": "/steps/*/arrow=half-solid-reverse-top",
        "sequenceDiagram.half-dotted-reverse-top": "/steps/*/arrow=half-dotted-reverse-top",
        "sequenceDiagram.half-solid-reverse-bottom": "/steps/*/arrow=half-solid-reverse-bottom",
        "sequenceDiagram.half-dotted-reverse-bottom": "/steps/*/arrow=half-dotted-reverse-bottom",
        "sequenceDiagram.stick-solid-top": "/steps/*/arrow=stick-solid-top",
        "sequenceDiagram.stick-dotted-top": "/steps/*/arrow=stick-dotted-top",
        "sequenceDiagram.stick-solid-bottom": "/steps/*/arrow=stick-solid-bottom",
        "sequenceDiagram.stick-dotted-bottom": "/steps/*/arrow=stick-dotted-bottom",
        "sequenceDiagram.stick-solid-reverse-top": "/steps/*/arrow=stick-solid-reverse-top",
        "sequenceDiagram.stick-dotted-reverse-top": "/steps/*/arrow=stick-dotted-reverse-top",
        "sequenceDiagram.stick-solid-reverse-bottom": "/steps/*/arrow=stick-solid-reverse-bottom",
        "sequenceDiagram.stick-dotted-reverse-bottom": "/steps/*/arrow=stick-dotted-reverse-bottom",
        "sequenceDiagram.central-target": "/steps/*/central=target",
        "sequenceDiagram.central-source": "/steps/*/central=source",
        "sequenceDiagram.central-both": "/steps/*/central=both",
        "sequenceDiagram.activate": "/steps/*/type=activate",
        "sequenceDiagram.deactivate": "/steps/*/type=deactivate",
        "sequenceDiagram.activation-shorthand": "/steps/*/activation=deactivate",
        "sequenceDiagram.activation-stacked": "/steps/43/activation=activate",
        "sequenceDiagram.note-right": "/steps/*/position=right_of",
        "sequenceDiagram.note-left": "/steps/*/position=left_of",
        "sequenceDiagram.note-over": "/steps/*/position=over",
        "sequenceDiagram.note-over-span": "/steps/*/actors/1",
        "sequenceDiagram.line-break": "/steps/*/label=Hello,\ntwo lines",
        "sequenceDiagram.loop": "/steps/*/type=loop",
        "sequenceDiagram.alt-else": "/steps/*/type=alt",
        "sequenceDiagram.opt": "/steps/*/type=opt",
        "sequenceDiagram.par-and": "/steps/*/type=par",
        "sequenceDiagram.par-nested": "/steps/*/branches/*/steps/*/type=par",
        "sequenceDiagram.critical-option": "/steps/56/branches/1/label",
        "sequenceDiagram.critical-no-option": "/steps/57/type=critical",
        "sequenceDiagram.break": "/steps/*/type=break",
        "sequenceDiagram.rect-rgb": "/steps/*/color=rgb(191, 223, 255)",
        "sequenceDiagram.rect-rgba": "/steps/*/steps/*/color=rgba(0, 0, 255, .1)",
        "sequenceDiagram.rect-nested": "/steps/*/steps/*/type=rect",
        "sequenceDiagram.comment": "/comment",
        "sequenceDiagram.entity-codes": "/steps/*/label=I ♥ you ∞ #1 \"really\"",
        "sequenceDiagram.entity-semicolon": "/steps/*/label=a; b",
        "sequenceDiagram.autonumber": "/autonumber=true",
        "sequenceDiagram.autonumber-start-increment": "/autonumber/increment",
        "sequenceDiagram.link": "/actors/*/menu/form=link",
        "sequenceDiagram.links-json": "/actors/*/actors/*/menu/form=links",
        "sequenceDiagram.end-word-enclosed": "/steps/*/text=(end)",
    },
    probes={
        "object": "/steps/0",
        "number": "/autonumber/start",
        "enum": "/steps/1/arrow",
        "ref": "/steps/0/to",
    },
))

# --- end sequenceDiagram ---

# --- classDiagram ---
#
# Typed IR for `classDiagram`. Members are objects (kind, visibility, name, type,
# parameters, return_type, classifier); types are a name or {name, args} for generics;
# styles are typed property maps. Probed against Mermaid CLI 12.0.0: every encoded
# character below renders back as the original character in that context.

_cls_LABEL_ENCODE = {**ENTITY, "~": "#126;"}
# Member text also encodes the characters the member parser reads as syntax: `~` (generic),
# trailing `$` / `*` (classifiers) and leading `+` / `-` (visibility).
_cls_MEMBER_ENCODE = {**_cls_LABEL_ENCODE, "$": "#36;", "*": "#42;", "+": "#43;", "-": "#45;"}

# Frontmatter title is a JSON-quoted YAML scalar; entity codes would show literally there.
text_context("classDiagram.title")
text_context("classDiagram.class-label", encode=_cls_LABEL_ENCODE)
text_context("classDiagram.namespace-label", encode=_cls_LABEL_ENCODE)
text_context("classDiagram.member", encode=_cls_MEMBER_ENCODE)
text_context("classDiagram.generic", encode=_cls_MEMBER_ENCODE)
text_context("classDiagram.edge-label", encode=_cls_LABEL_ENCODE)
text_context("classDiagram.note", encode={**_cls_LABEL_ENCODE, "\n": "<br>"}, allow_newline=True)
# The tooltip becomes an SVG `title` attribute (entity codes decode there) and hover HTML,
# so markup characters are refused; `-->` would also make Mermaid drop the tooltip.
text_context("classDiagram.tooltip", encode=ENTITY, reject="<>")
text_context(
    "classDiagram.url",
    reject_patterns=(
        (r"^(?!(https?://|mailto:)[A-Za-z0-9\-._~:/?#@!$&'()*+,=%]+$)",
         "must be an http(s):// or mailto: URL without spaces, quotes, ';', '<', '>', brackets or braces"),
        (r"%%", "'%%' starts a comment"),
    ),
)
text_context(
    "classDiagram.color",
    reject_patterns=((r"^(?!#[0-9A-Fa-f]{3,8}$|[a-z]+$|(rgb|rgba|hsl|hsla)\([0-9. %/]+\)$)",
                      "must be a CSS color: #hex, a name, or rgb()/hsl() with space-separated values (a ',' splits the style)"),),
)
text_context("classDiagram.size", reject_patterns=((r"^(?!\d+(\.\d+)?(px|pt|em|rem)?$)", "must be a size such as 4px, 12pt or 1.5em"),))
text_context("classDiagram.dasharray", reject_patterns=((r"^(?!\d+(\.\d+)?( \d+(\.\d+)?)*$)", "must be space-separated numbers such as '5 5'"),))

_cls_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Backtick names: words joined by single spaces, dots or dashes. Characters such as `!` crash
# the renderer once `classDef default` is present, so they are not accepted.
_cls_BACKTICK_ID = re.compile(r"[A-Za-z0-9_]+(?:[ .-][A-Za-z0-9_]+)*")
_cls_NAMESPACE_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
# Words the 12.0.0 lexer reads as keywords even as a class, namespace or classDef name.
_cls_RESERVED = frozenset({
    "class", "namespace", "note", "style", "click", "link", "callback", "call", "href",
    "classDef", "cssClass", "classDiagram", "o", "_blank", "_self", "_parent", "_top",
})
_cls_DIRECTIONS = ("TB", "BT", "LR", "RL")
_cls_VISIBILITY = {"public": "+", "private": "-", "protected": "#", "package": "~"}
_cls_CLASSIFIER = {"static": "$", "abstract": "*"}
_cls_ANNOTATIONS = ("interface", "abstract", "service", "enumeration")
_cls_PLACEMENTS = ("inline", "separate", "block")
_cls_CARDINALITIES = ("1", "0..1", "1..*", "*", "n", "0..n", "1..n")
# kind -> {ends: arrow token}; the first entry is the default end.
_cls_RELATIONS: dict[str, dict[str, str]] = {
    "inheritance": {"from": "<|--", "to": "--|>", "both": "<|--|>"},
    "composition": {"from": "*--", "to": "--*", "both": "*--*"},
    "aggregation": {"from": "o--", "to": "--o", "both": "o--o"},
    "association": {"to": "-->", "from": "<--", "both": "<-->"},
    "dependency": {"to": "..>", "from": "<..", "both": "<..>"},
    "realization": {"to": "..|>", "from": "<|..", "both": "<|..|>"},
    "link": {"none": "--"},
    "link_dashed": {"none": ".."},
    "lollipop": {"from": "()--", "to": "--()", "both": "()--()"},
}
_cls_STYLE = {
    "fill": ("color", "fill"),
    "stroke": ("color", "stroke"),
    "color": ("color", "color"),
    "strokeWidth": ("size", "stroke-width"),
    "strokeDasharray": ("dasharray", "stroke-dasharray"),
    "fontSize": ("size", "font-size"),
    "fontWeight": (("normal", "bold", "bolder", "lighter", "100", "200", "300", "400", "500",
                    "600", "700", "800", "900"), "font-weight"),
    "fontStyle": (("normal", "italic", "oblique"), "font-style"),
}
_cls_CONFIG = {
    "theme": ("enum", ("default", "base", "dark", "forest", "neutral", "redux", "redux-color",
                       "redux-dark", "redux-dark-color")),
    "look": ("enum", ("classic", "hand", "neo")),
    "layout": ("enum", ("dagre", "elk")),
    "class": {
        "hideEmptyMembersBox": ("boolean",),
        "hierarchicalNamespaces": ("boolean",),
        "htmlLabels": ("boolean",),
        "titleTopMargin": ("integer", 0, None),
        "dividerMargin": ("number", 0, None),
        "padding": ("number", 0, None),
        "textHeight": ("number", 0, None),
        "arrowMarkerAbsolute": ("boolean",),
        "useMaxWidth": ("boolean",),
    },
}
_cls_ROOT_KEYS = ("title", "config", "accessibility", "comment", "direction", "nodes", "namespaces",
                  "edges", "notes", "interactions", "class_defs", "css_classes")
_cls_NODE_KEYS = ("id", "backtick", "implicit", "label", "generic", "annotation", "members",
                  "member_syntax", "class", "style")
_cls_IMPLICIT_KEYS = ("id", "backtick", "implicit", "annotation", "members", "member_syntax", "style")


def _cls_name(v: Validator, value: Any, path: str, pattern: re.Pattern[str]) -> str:
    v.ident(value, path, pattern)
    for word in re.split(r"[ .-]", value):
        if word in _cls_RESERVED:
            raise v.error(path, f"{word!r} is a classDiagram keyword and cannot be used as a name")
    return value


def _cls_style(v: Validator, value: Any, path: str) -> str:
    style = v.fields(value, path, optional=tuple(_cls_STYLE))
    if not style:
        raise v.error(path, "a style needs at least one property")
    parts = []
    for key, item in style.items():
        kind, css = _cls_STYLE[key]
        sub = ptr(path, key)
        if isinstance(kind, tuple):
            parts.append(f"{css}:{v.enum(item, sub, kind)}")
        else:
            parts.append(f"{css}:{v.text(item, sub, f'classDiagram.{kind}')}")
    return ",".join(parts)


def _cls_type(v: Validator, value: Any, path: str, outer: bool = True) -> str:
    """A type: a name, or {name, args} for a generic (`List~int~`)."""
    if isinstance(value, str):
        return v.text(value, path, "classDiagram.member")
    ref = v.fields(value, path, required=("name", "args"))
    name = v.text(ref["name"], ptr(path, "name"), "classDiagram.member")
    args_path = ptr(path, "args")
    args = v.array(ref["args"], args_path, 1)
    if len(args) > 1:
        if not outer:
            raise v.error(args_path, "a generic with several arguments renders only as the outermost type")
        for i, arg in enumerate(args):
            if not isinstance(arg, str):
                raise v.error(ptr(args_path, i), "arguments of a generic with several arguments must be plain names")
    inner = ", ".join(_cls_type(v, arg, ptr(args_path, i), outer=False) for i, arg in enumerate(args))
    return f"{name}~{inner}~"


def _cls_member(v: Validator, value: Any, path: str) -> str:
    if not isinstance(value, dict):
        raise v.error(path, f"must be an object, got {type(value).__name__}")
    if "kind" not in value:
        raise v.error(ptr(path, "kind"), "required key is missing")
    kind = v.enum(value["kind"], ptr(path, "kind"), ("attribute", "method"))
    common = ("visibility", "classifier")
    if kind == "attribute":
        member = v.fields(value, path, required=("kind", "name"), optional=(*common, "type"))
    else:
        member = v.fields(value, path, required=("kind", "name"), optional=(*common, "parameters", "return_type"))
    vis = v.enum(member["visibility"], ptr(path, "visibility"), _cls_VISIBILITY) if "visibility" in member else ""
    classifier = v.enum(member["classifier"], ptr(path, "classifier"), _cls_CLASSIFIER) if "classifier" in member else ""
    name = v.text(member["name"], ptr(path, "name"), "classDiagram.member")
    if kind == "attribute":
        type_ = f"{_cls_type(v, member['type'], ptr(path, 'type'))} " if "type" in member else ""
        return f"{vis}{type_}{name}{classifier}"
    params = []
    params_path = ptr(path, "parameters")
    for i, param in enumerate(v.array(member.get("parameters", []), params_path)):
        p_path = ptr(params_path, i)
        v.fields(param, p_path, required=("name",), optional=("type",))
        p_type = f"{_cls_type(v, param['type'], ptr(p_path, 'type'))} " if "type" in param else ""
        params.append(f"{p_type}{v.text(param['name'], ptr(p_path, 'name'), 'classDiagram.member')}")
    ret = f" {_cls_type(v, member['return_type'], ptr(path, 'return_type'))}" if "return_type" in member else ""
    return f"{vis}{name}({', '.join(params)}){ret}{classifier}"


def _cls_serialize(ir: dict, keyword: str) -> str:
    v = Validator(keyword)
    v.fields(ir, "", required=("nodes",), optional=_cls_ROOT_KEYS)
    title = v.text(ir["title"], "/title", "classDiagram.title") if "title" in ir else None
    config = validate_config(v, ir["config"], "/config", _cls_CONFIG) if "config" in ir else None
    head = emit_frontmatter(title, config) + ["classDiagram"]
    head += emit_accessibility(v, ir)
    head += emit_comment(v, ir)
    if "direction" in ir:
        head.append(f"    direction {v.enum(ir['direction'], '/direction', _cls_DIRECTIONS)}")

    # classDef names first: `:::` and cssClass reference them.
    class_names: set[str] = set()
    class_def_lines: list[str] = []
    for i, cdef in enumerate(v.array(ir.get("class_defs", []), "/class_defs")):
        path = f"/class_defs/{i}"
        v.fields(cdef, path, required=("names", "style"))
        names = []
        for j, name in enumerate(v.array(cdef["names"], ptr(path, "names"), 1)):
            n_path = ptr(ptr(path, "names"), j)
            if name != "default":
                _cls_name(v, name, n_path, _cls_ID)
            names.append(v.unique(name, n_path, class_names, "classDef name"))
        class_def_lines.append(f"    classDef {','.join(names)} {_cls_style(v, cdef['style'], ptr(path, 'style'))}")
    applicable = class_names - {"default"}

    nodes = v.array(ir["nodes"], "/nodes", 1)
    tokens: dict[str, str] = {}
    implicit: dict[str, str] = {}  # id -> node path
    decls: dict[str, list[str]] = {}
    colon_lines: list[str] = []
    separate_lines: list[str] = []
    style_lines: list[str] = []
    node_paths: dict[str, str] = {}
    for i, node in enumerate(nodes):
        path = f"/nodes/{i}"
        is_implicit = isinstance(node, dict) and node.get("implicit") is True
        v.fields(node, path, required=("id",), optional=_cls_IMPLICIT_KEYS if is_implicit else _cls_NODE_KEYS)
        backtick = v.boolean(node["backtick"], ptr(path, "backtick")) if "backtick" in node else False
        if "implicit" in node:
            v.boolean(node["implicit"], ptr(path, "implicit"))
        node_id = _cls_name(v, node["id"], ptr(path, "id"), _cls_BACKTICK_ID if backtick else _cls_ID)
        v.unique(node_id, ptr(path, "id"), set(tokens), "class id")
        token = f"`{node_id}`" if backtick else node_id
        tokens[node_id] = token
        node_paths[node_id] = path
        if is_implicit:
            implicit[node_id] = path

        syntax_path = ptr(path, "member_syntax")
        syntax = v.enum(node["member_syntax"], syntax_path, ("block", "colon")) if "member_syntax" in node else (
            "colon" if is_implicit else "block")
        if is_implicit and syntax == "block":
            raise v.error(syntax_path, "a class declared only by a relation has no block; use colon members")
        members = [_cls_member(v, m, ptr(ptr(path, "members"), j))
                   for j, m in enumerate(v.array(node.get("members", []), ptr(path, "members")))]

        annotation, placement = None, None
        if "annotation" in node:
            a_path = ptr(path, "annotation")
            ann = v.fields(node["annotation"], a_path, required=("name",), optional=("placement",))
            annotation = v.enum(ann["name"], ptr(a_path, "name"), _cls_ANNOTATIONS)
            placement = v.enum(ann["placement"], ptr(a_path, "placement"), _cls_PLACEMENTS) if "placement" in ann else (
                "separate" if is_implicit else "block")
            if is_implicit and placement != "separate":
                raise v.error(ptr(a_path, "placement"), "a class declared only by a relation takes a separate annotation")
            if placement == "inline" and "class" in node:
                raise v.error(ptr(a_path, "placement"), "an inline annotation cannot follow ':::' (parse error); use block or separate")

        if not is_implicit:
            line = f"class {token}"
            if "generic" in node:
                g_path = ptr(path, "generic")
                args = [v.text(g, ptr(g_path, j), "classDiagram.generic")
                        for j, g in enumerate(v.array(node["generic"], g_path, 1))]
                line += f"~{', '.join(args)}~"
            if "label" in node:
                line += f'["{v.text(node["label"], ptr(path, "label"), "classDiagram.class-label")}"]'
            if "class" in node:
                line += f":::{v.ref(node['class'], ptr(path, 'class'), applicable)}"
            if placement == "inline":
                line += f" <<{annotation}>>"
            body = [f"<<{annotation}>>"] if placement == "block" else []
            if syntax == "block":
                body += members
            decls[node_id] = [line + " {", *(f"    {m}" for m in body), "}"] if body else [line]
        if syntax == "colon":
            colon_lines += [f"    {token} : {m}" for m in members]
        if placement == "separate":
            separate_lines.append(f"    <<{annotation}>> {token}")
        if "style" in node:
            if backtick:
                raise v.error(ptr(path, "style"), "'style' does not parse with a backtick name; use a classDef and 'class'")
            style_lines.append(f"    style {token} {_cls_style(v, node['style'], ptr(path, 'style'))}")

    # Namespaces hold class declarations; colon members and annotations stay outside.
    placed: set[str] = set()
    namespace_ids: set[str] = set()
    namespace_lines: list[str] = []

    def namespace(value: Any, path: str, indent: str) -> None:
        ns = v.fields(value, path, required=("id",), optional=("label", "classes", "namespaces"))
        ns_id = _cls_name(v, ns["id"], ptr(path, "id"), _cls_NAMESPACE_ID)
        if ns_id in tokens:
            raise v.error(ptr(path, "id"), f"namespace id {ns_id!r} is also a class id")
        v.unique(ns_id, ptr(path, "id"), namespace_ids, "namespace id")
        label = ""
        if "label" in ns:
            label = f'["{v.text(ns["label"], ptr(path, "label"), "classDiagram.namespace-label")}"]'
        classes = v.array(ns.get("classes", []), ptr(path, "classes"))
        children = v.array(ns.get("namespaces", []), ptr(path, "namespaces"))
        if not classes and not children:
            raise v.error(path, "an empty namespace does not parse; give it a class or a nested namespace")
        namespace_lines.append(f"{indent}namespace {ns_id}{label} {{")
        for j, class_id in enumerate(classes):
            c_path = ptr(ptr(path, "classes"), j)
            v.ref(class_id, c_path, tokens)
            if class_id in implicit:
                raise v.error(c_path, "a class declared only by a relation cannot be placed in a namespace")
            v.unique(class_id, c_path, placed, "namespace member")
            namespace_lines.extend(f"{indent}    {line}" for line in decls[class_id])
        for j, child in enumerate(children):
            namespace(child, ptr(ptr(path, "namespaces"), j), indent + "    ")
        namespace_lines.append(f"{indent}}}")

    for i, ns in enumerate(v.array(ir.get("namespaces", []), "/namespaces")):
        namespace(ns, f"/namespaces/{i}", "    ")

    edge_lines: list[str] = []
    related: set[str] = set()
    for i, edge in enumerate(v.array(ir.get("edges", []), "/edges")):
        path = f"/edges/{i}"
        v.fields(edge, path, required=("from", "to", "kind"), optional=("ends", "from_card", "to_card", "label"))
        source = v.ref(edge["from"], ptr(path, "from"), tokens)
        target = v.ref(edge["to"], ptr(path, "to"), tokens)
        kind = v.enum(edge["kind"], ptr(path, "kind"), tuple(_cls_RELATIONS))
        arrows = _cls_RELATIONS[kind]
        if "ends" in edge:
            if "none" in arrows:
                raise v.error(ptr(path, "ends"), f"a {kind} has no arrowheads; omit 'ends'")
            arrow = arrows[v.enum(edge["ends"], ptr(path, "ends"), tuple(arrows))]
        else:
            arrow = next(iter(arrows.values()))
        parts = [tokens[source]]
        if "from_card" in edge:
            parts.append(f'"{v.enum(edge["from_card"], ptr(path, "from_card"), _cls_CARDINALITIES)}"')
        parts.append(arrow)
        if "to_card" in edge:
            parts.append(f'"{v.enum(edge["to_card"], ptr(path, "to_card"), _cls_CARDINALITIES)}"')
        parts.append(tokens[target])
        label = f" : {v.text(edge['label'], ptr(path, 'label'), 'classDiagram.edge-label')}" if "label" in edge else ""
        edge_lines.append(f"    {' '.join(parts)}{label}")
        related |= {source, target}
    for node_id, path in implicit.items():
        if node_id not in related:
            raise v.error(ptr(path, "implicit"), "a class declared only by a relation needs at least one edge")

    note_lines: list[str] = []
    for i, note in enumerate(v.array(ir.get("notes", []), "/notes")):
        path = f"/notes/{i}"
        v.fields(note, path, required=("text",), optional=("for",))
        target = f" for {tokens[v.ref(note['for'], ptr(path, 'for'), tokens)]}" if "for" in note else ""
        note_lines.append(f'    note{target} "{v.text(note["text"], ptr(path, "text"), "classDiagram.note")}"')

    interaction_lines: list[str] = []
    clicked: set[str] = set()
    for i, item in enumerate(v.array(ir.get("interactions", []), "/interactions")):
        path = f"/interactions/{i}"
        if not isinstance(item, dict):
            raise v.error(path, f"must be an object, got {type(item).__name__}")
        if "action" not in item:
            raise v.error(ptr(path, "action"), "required key is missing")
        action = v.enum(item["action"], ptr(path, "action"), ("href", "link", "call", "callback"))
        ref_key = "url" if action in ("href", "link") else "function"
        v.fields(item, path, required=("node", "action", ref_key), optional=("tooltip",))
        node_id = v.ref(item["node"], ptr(path, "node"), tokens)
        v.unique(node_id, ptr(path, "node"), clicked, "interaction for class")
        token = tokens[node_id]
        if ref_key == "url":
            ref = v.text(item["url"], ptr(path, "url"), "classDiagram.url")
        else:
            ref = _cls_name(v, item["function"], ptr(path, "function"), _cls_ID)
        line = {
            "href": f'click {token} href "{ref}"',
            "link": f'link {token} "{ref}"',
            "call": f"click {token} call {ref}()",
            "callback": f'callback {token} "{ref}"',
        }[action]
        if "tooltip" in item:
            line += f' "{v.text(item["tooltip"], ptr(path, "tooltip"), "classDiagram.tooltip")}"'
        interaction_lines.append(f"    {line}")

    css_lines: list[str] = []
    for i, item in enumerate(v.array(ir.get("css_classes", []), "/css_classes")):
        path = f"/css_classes/{i}"
        v.fields(item, path, required=("nodes", "class"))
        targets = [tokens[v.ref(n, ptr(ptr(path, "nodes"), j), tokens)]
                   for j, n in enumerate(v.array(item["nodes"], ptr(path, "nodes"), 1))]
        css_lines.append(f'    cssClass "{",".join(targets)}" {v.ref(item["class"], ptr(path, "class"), applicable)}')

    lines = list(head)
    for node_id, decl in decls.items():
        if node_id not in placed:
            lines.extend(f"    {line}" for line in decl)
    lines += namespace_lines + edge_lines + colon_lines + separate_lines + note_lines
    lines += interaction_lines + style_lines + class_def_lines + css_lines
    return "\n".join(lines) + "\n"


_cls_MEMBER_TEXT = ("name", "type", "type/name", "type/args/*", "return_type", "return_type/name",
                    "return_type/args/*", "parameters/*/name", "parameters/*/type")

register(Builder(
    "classDiagram", "graph", ("classDiagram",), _cls_serialize,
    text_fields=(
        "/title", "/accessibility/title", "/accessibility/description", "/comment",
        "/nodes/*/label", "/nodes/*/generic/*",
        *(f"/nodes/*/members/*/{suffix}" for suffix in _cls_MEMBER_TEXT),
        "/nodes/5/members/*/name", "/nodes/5/members/*/type",
        "/nodes/5/members/*/parameters/*/name", "/nodes/5/members/*/return_type",
        "/namespaces/*/label", "/namespaces/*/namespaces/*/label",
        "/edges/*/label", "/notes/*/text", "/interactions/*/tooltip",
    ),
    features={
        "classDiagram.keyword": "/target=classDiagram",
        "classDiagram.class-keyword": "/nodes/*/id",
        "classDiagram.class-via-relation": "/nodes/*/implicit=true",
        "classDiagram.class-label": "/nodes/*/label",
        "classDiagram.class-backtick-name": "/nodes/*/backtick=true",
        "classDiagram.member-colon": "/nodes/*/member_syntax=colon",
        "classDiagram.member-block": "/nodes/*/member_syntax=block",
        "classDiagram.method": "/nodes/*/members/*/kind=method",
        "classDiagram.method-return-type": "/nodes/*/members/*/return_type",
        "classDiagram.generic-class": "/nodes/*/generic/*",
        "classDiagram.generic-member": "/nodes/*/members/*/type/args/*",
        "classDiagram.generic-nested": "/nodes/*/members/*/return_type/args/*/args/*",
        "classDiagram.visibility-public": "/nodes/*/members/*/visibility=public",
        "classDiagram.visibility-private": "/nodes/*/members/*/visibility=private",
        "classDiagram.visibility-protected": "/nodes/*/members/*/visibility=protected",
        "classDiagram.visibility-package": "/nodes/*/members/*/visibility=package",
        "classDiagram.classifier-abstract": "/nodes/*/members/*/classifier=abstract",
        "classDiagram.classifier-static-method": "/nodes/6/members/5/classifier=static",
        "classDiagram.classifier-static-field": "/nodes/6/members/6/classifier=static",
        "classDiagram.rel-inheritance": "/edges/*/kind=inheritance",
        "classDiagram.rel-composition": "/edges/*/kind=composition",
        "classDiagram.rel-aggregation": "/edges/*/kind=aggregation",
        "classDiagram.rel-association": "/edges/*/kind=association",
        "classDiagram.rel-link-solid": "/edges/*/kind=link",
        "classDiagram.rel-dependency": "/edges/*/kind=dependency",
        "classDiagram.rel-realization": "/edges/*/kind=realization",
        "classDiagram.rel-link-dashed": "/edges/*/kind=link_dashed",
        "classDiagram.rel-reversed": "/edges/10/ends=to",
        "classDiagram.rel-label": "/edges/*/label",
        "classDiagram.two-way-inheritance": "/edges/11/ends=both",
        "classDiagram.two-way-composition": "/edges/12/ends=both",
        "classDiagram.two-way-aggregation": "/edges/13/ends=both",
        "classDiagram.two-way-association": "/edges/14/ends=both",
        "classDiagram.two-way-realization": "/edges/15/ends=both",
        "classDiagram.two-way-dashed": "/edges/16/ends=both",
        "classDiagram.lollipop-left": "/edges/17/ends=from",
        "classDiagram.lollipop-right": "/edges/18/ends=to",
        "classDiagram.namespace": "/namespaces/*/classes/*",
        "classDiagram.namespace-label": "/namespaces/*/label",
        "classDiagram.namespace-dot-notation": "/namespaces/*/id=Company.Engineering.Backend",
        "classDiagram.namespace-nested": "/namespaces/*/namespaces/*/id",
        "classDiagram.cardinality-1": "/edges/*/from_card=1",
        "classDiagram.cardinality-0-1": "/edges/*/from_card=0..1",
        "classDiagram.cardinality-1-many": "/edges/*/to_card=1..*",
        "classDiagram.cardinality-many": "/edges/*/to_card=*",
        "classDiagram.cardinality-n": "/edges/*/from_card=n",
        "classDiagram.cardinality-0-n": "/edges/*/to_card=0..n",
        "classDiagram.cardinality-1-n": "/edges/*/to_card=1..n",
        "classDiagram.annotation-inline": "/nodes/*/annotation/placement=inline",
        "classDiagram.annotation-separate": "/nodes/*/annotation/placement=separate",
        "classDiagram.annotation-nested": "/nodes/*/annotation/placement=block",
        "classDiagram.comment": "/comment",
        "classDiagram.direction": "/direction",
        "classDiagram.click-href": "/interactions/*/action=href",
        "classDiagram.click-call": "/interactions/*/action=call",
        "classDiagram.link": "/interactions/*/action=link",
        "classDiagram.callback": "/interactions/*/action=callback",
        "classDiagram.note": "/notes/0/text",
        "classDiagram.note-for": "/notes/*/for",
        "classDiagram.style": "/nodes/*/style",
        "classDiagram.classdef": "/class_defs/*/names/*",
        "classDiagram.classdef-multi": "/class_defs/*/names/1",
        "classDiagram.classdef-default": "/class_defs/*/names/*=default",
        "classDiagram.cssclass": "/css_classes/*/class",
        "classDiagram.cssclass-list": "/css_classes/*/nodes/1",
        "classDiagram.class-shorthand": "/nodes/*/class",
        "classDiagram.class-shorthand-block": "/nodes/59/class",
    },
    probes={
        "object": "/nodes/6/members/1/type",
        "number": "/config/class/padding",
        "enum": "/edges/0/kind",
        "ref": "/edges/0/from",
    },
))

# --- end classDiagram ---

# --- stateDiagram ---
#
# IR family `state-machine`, keywords `stateDiagram-v2` and `stateDiagram` (legacy; same
# statements). Lexer facts checked against Mermaid CLI 12.0.0 that shape the rules below:
# - A line containing `direction <TB|BT|RL|LR>` anywhere (case-insensitive) lexes as a
#   direction statement and the rest of the line is lost, so that pattern is rejected in
#   every single-line text field, comments and accessibility text included.
# - `;` ends a description and `:` ends an inline note; `[[fork]]`-style and `<<fork>>`
#   text in `state "..." as id` turns the state into a pseudo-state; `<b>` is drawn as
#   markup. `#;<>"&:%[]` are therefore written as entity codes, which render back verbatim.
# - A line starting with `end note` ends a multi-line note.
# - `direction TD` is not a direction in state diagrams (it becomes two states).
# - `:::` on a transition inside a composite is ignored, and a comma inside a color splits
#   the style list, so both are rejected.

_ST_DIRECTION_HAZARD = (
    r"(?i)direction\s+(TB|BT|RL|LR)",
    "'direction' followed by TB/BT/RL/LR turns the whole line into a direction statement",
)
_ST_ENCODE = {char: ENTITY[char] for char in '#;<>"&:%[]'}

text_context("stateDiagram.title")
text_context("stateDiagram.comment", reject_patterns=((r"%%", "'%%' would end the comment early"), _ST_DIRECTION_HAZARD))
text_context("stateDiagram.trailing-comment", reject_patterns=(_ST_DIRECTION_HAZARD,))
text_context("stateDiagram.accessibility", allow_newline=True, reject_patterns=(_ST_DIRECTION_HAZARD,))
text_context("stateDiagram.label-colon", encode=_ST_ENCODE, reject_patterns=(_ST_DIRECTION_HAZARD,))
text_context("stateDiagram.label-as", encode=_ST_ENCODE, reject_patterns=(_ST_DIRECTION_HAZARD,))
text_context("stateDiagram.transition-label", encode=_ST_ENCODE, reject_patterns=(_ST_DIRECTION_HAZARD,))
text_context("stateDiagram.note-inline", encode=_ST_ENCODE, reject_patterns=(_ST_DIRECTION_HAZARD,))
text_context(
    "stateDiagram.note-line",
    encode=_ST_ENCODE,
    reject_patterns=((r"(?i)^end\s+note\b", "a line starting with 'end note' ends the note"),),
)

_ST_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Case-insensitive words the 12.0.0 lexer reads as keywords where an id is expected.
_ST_RESERVED = {"state", "note", "class", "classdef", "style", "as", "default", "scale", "click", "href",
                "statediagram", "direction"}
_ST_DIRECTIONS = ("TB", "BT", "LR", "RL")
_ST_PSEUDO = ("choice", "fork", "join")
_ST_START_END = "[*]"
_ST_BODY_KEYS = ("states", "initial", "transitions", "final", "notes")
_ST_STATE_KEYS = ("id", "label", "labelForm", "kind", "direction", "regions") + _ST_BODY_KEYS
_ST_SIZE = re.compile(r"\d+(\.\d+)?(px|pt|em|rem|%)?")
_ST_DASH = re.compile(r"\d+(\.\d+)?(px)?( \d+(\.\d+)?(px)?)*")
_ST_FONT_WEIGHTS = ("normal", "bold", "bolder", "lighter", "100", "200", "300", "400", "500", "600", "700",
                    "800", "900")
_ST_FONT_STYLES = ("normal", "italic", "oblique")
# IR style key -> CSS property, in emission order.
_ST_STYLE_KEYS = {
    "fill": "fill",
    "stroke": "stroke",
    "strokeWidth": "stroke-width",
    "strokeDasharray": "stroke-dasharray",
    "color": "color",
    "fontSize": "font-size",
    "fontWeight": "font-weight",
    "fontStyle": "font-style",
}
_ST_CONFIG = {
    "theme": ("enum", ("default", "base", "dark", "forest", "neutral", "neo", "neo-dark", "redux",
                       "redux-dark", "redux-color", "redux-dark-color", "null")),
    "look": ("enum", ("classic", "handDrawn", "neo")),
    "layout": ("enum", ("dagre", "elk")),
    "state": {
        "wrappingWidth": ("number", 0, None),
        "minNodeWidth": ("number", 0, None),
        "titleTopMargin": ("number", 0, None),
        "padding": ("number", 0, None),
        "dividerMargin": ("number", 0, None),
        "noteMargin": ("number", 0, None),
        "forkWidth": ("number", 0, None),
        "forkHeight": ("number", 0, None),
        "radius": ("number", 0, None),
        "useMaxWidth": ("boolean",),
    },
}


def _st_ident(v: Validator, value: Any, path: str) -> str:
    v.ident(value, path, _ST_ID)
    if value.lower() in _ST_RESERVED:
        raise v.error(path, f"{value!r} is a stateDiagram keyword and cannot be an id or class name")
    return value


def _st_style(v: Validator, value: Any, path: str) -> str:
    """Typed style object -> `fill:#f00,stroke-width:2px` (closed key set, validated values)."""
    style = v.fields(value, path, optional=tuple(_ST_STYLE_KEYS))
    if not style:
        raise v.error(path, "must set at least one style property")
    parts = []
    for key, css in _ST_STYLE_KEYS.items():
        if key not in style:
            continue
        sub = ptr(path, key)
        item = style[key]
        if key in ("fill", "stroke", "color"):
            v.text(item, sub, "common.color")
            if "," in item:
                raise v.error(sub, "a comma splits the style list; write rgb()/hsl() with spaces")
        elif key in ("strokeWidth", "fontSize"):
            if not isinstance(item, str) or not _ST_SIZE.fullmatch(item):
                raise v.error(sub, f"must be a size such as '2px', got {json.dumps(item)}")
        elif key == "strokeDasharray":
            if not isinstance(item, str) or not _ST_DASH.fullmatch(item):
                raise v.error(sub, f"must be space-separated lengths such as '5 5', got {json.dumps(item)}")
        elif key == "fontWeight":
            v.enum(item, sub, _ST_FONT_WEIGHTS)
        else:
            v.enum(item, sub, _ST_FONT_STYLES)
        parts.append(f"{css}:{item}")
    return ",".join(parts)


class _StScope:
    """Ids and kinds collected over the whole document before anything is emitted."""

    def __init__(self) -> None:
        self.kinds: dict[str, str] = {}  # id -> "simple" | "composite" | "choice" | "fork" | "join"
        self.paths: dict[str, str] = {}


def _st_collect(v: Validator, body: dict, path: str, scope: _StScope, seen: set[str]) -> list[str]:
    """Validate the state declarations of one body; return the ids declared directly in it."""
    local: list[str] = []
    for i, state in enumerate(v.array(body.get("states", []), ptr(path, "states"))):
        spath = ptr(ptr(path, "states"), i)
        v.fields(state, spath, required=("id",), optional=_ST_STATE_KEYS)
        sid = _st_ident(v, state["id"], ptr(spath, "id"))
        v.unique(sid, ptr(spath, "id"), seen, "state id")
        local.append(sid)
        scope.paths[sid] = spath
        if "kind" in state:
            kind = v.enum(state["kind"], ptr(spath, "kind"), _ST_PSEUDO)
            for key in state:
                if key not in ("id", "kind"):
                    raise v.error(ptr(spath, key), f"a <<{kind}>> pseudo-state takes only id and kind")
            scope.kinds[sid] = kind
            continue
        if "labelForm" in state:
            v.enum(state["labelForm"], ptr(spath, "labelForm"), ("colon", "as"))
            if "label" not in state:
                raise v.error(ptr(spath, "labelForm"), "labelForm needs a label")
        if "states" in state and "regions" in state:
            raise v.error(ptr(spath, "regions"), "use either states or regions, not both")
        if "regions" in state:
            for key in _ST_BODY_KEYS:
                if key in state:
                    raise v.error(ptr(spath, key), "with regions, put states, transitions and notes in each region")
            regions = v.array(state["regions"], ptr(spath, "regions"), min_items=2)
            for r, region in enumerate(regions):
                rpath = ptr(ptr(spath, "regions"), r)
                v.fields(region, rpath, required=("states",), optional=_ST_BODY_KEYS)
                v.array(region["states"], ptr(rpath, "states"), min_items=1)
                _st_collect(v, region, rpath, scope, seen)
            scope.kinds[sid] = "composite"
        elif "states" in state:
            v.array(state["states"], ptr(spath, "states"), min_items=1)
            _st_collect(v, state, spath, scope, seen)
            scope.kinds[sid] = "composite"
        else:
            for key in ("direction",) + _ST_BODY_KEYS:
                if key in state:
                    raise v.error(ptr(spath, key), "only a composite state (with states or regions) takes this key")
            scope.kinds[sid] = "simple"
    return local


def _st_label(v: Validator, state: dict, path: str, form: str) -> str:
    context = "stateDiagram.label-as" if form == "as" else "stateDiagram.label-colon"
    return v.text(state["label"], ptr(path, "label"), context)


def _st_body(v: Validator, body: dict, path: str, scope: _StScope, classes: set[str], top: bool,
             lines: list[str], indent: str) -> None:
    """Emit one body (top level, composite, or region): states, initial, transitions, final, notes."""
    states = body.get("states", [])
    local = {state["id"] for state in states}
    for i, state in enumerate(states):
        spath = ptr(ptr(path, "states"), i)
        sid = state["id"]
        kind = scope.kinds[sid]
        if kind in _ST_PSEUDO:
            lines.append(f"{indent}state {sid} <<{kind}>>")
            continue
        form = state.get("labelForm", "colon")
        label = _st_label(v, state, spath, form) if "label" in state else None
        if kind == "simple":
            if label is None:
                lines.append(f"{indent}{sid}")
            elif form == "as":
                lines.append(f'{indent}state "{label}" as {sid}')
            else:
                lines.append(f"{indent}{sid} : {label}")
            continue
        if label is not None and form == "colon":
            lines.append(f"{indent}{sid} : {label}")
            lines.append(f"{indent}state {sid} {{")
        elif label is not None:
            lines.append(f'{indent}state "{label}" as {sid} {{')
        else:
            lines.append(f"{indent}state {sid} {{")
        inner = indent + "    "
        if "direction" in state:
            lines.append(f"{inner}direction {v.enum(state['direction'], ptr(spath, 'direction'), _ST_DIRECTIONS)}")
        if "regions" in state:
            for r, region in enumerate(state["regions"]):
                if r:
                    lines.append(f"{inner}--")
                _st_body(v, region, ptr(ptr(spath, "regions"), r), scope, classes, False, lines, inner)
        else:
            _st_body(v, state, spath, scope, classes, False, lines, inner)
        lines.append(f"{indent}}}")

    def sibling(value: Any, at: str) -> str:
        return v.ref(value, at, local)

    if "initial" in body:
        lines.append(f"{indent}{_ST_START_END} --> {sibling(body['initial'], ptr(path, 'initial'))}")
    for i, tr in enumerate(v.array(body.get("transitions", []), ptr(path, "transitions"))):
        tpath = ptr(ptr(path, "transitions"), i)
        v.fields(tr, tpath, required=("from", "to"), optional=("label", "comment", "fromClass", "toClass"))
        ends = []
        for end in ("from", "to"):
            value = tr[end]
            if value == _ST_START_END:
                if f"{end}Class" in tr:
                    raise v.error(ptr(tpath, f"{end}Class"), "':::' on [*] is not drawn")
                ends.append(value)
                continue
            token = sibling(value, ptr(tpath, end))
            if f"{end}Class" in tr:
                cpath = ptr(tpath, f"{end}Class")
                if not top:
                    raise v.error(cpath, "':::' is ignored inside a composite; use classes instead")
                if scope.kinds[token] != "simple":
                    raise v.error(cpath, "':::' styles only a simple state")
                token += ":::" + v.ref(tr[f"{end}Class"], cpath, classes)
            ends.append(token)
        if tr["from"] == _ST_START_END and tr["to"] == _ST_START_END:
            raise v.error(ptr(tpath, "to"), "a transition cannot go from [*] to [*]")
        line = f"{indent}{ends[0]} --> {ends[1]}"
        if "label" in tr:
            line += f" : {v.text(tr['label'], ptr(tpath, 'label'), 'stateDiagram.transition-label')}"
        if "comment" in tr:
            line += f" %% {v.text(tr['comment'], ptr(tpath, 'comment'), 'stateDiagram.trailing-comment')}"
        lines.append(line)
    for i, final in enumerate(v.array(body.get("final", []), ptr(path, "final"))):
        lines.append(f"{indent}{sibling(final, ptr(ptr(path, 'final'), i))} --> {_ST_START_END}")
    for i, note in enumerate(v.array(body.get("notes", []), ptr(path, "notes"))):
        npath = ptr(ptr(path, "notes"), i)
        v.fields(note, npath, required=("state", "side"), optional=("text", "lines"))
        target = sibling(note["state"], ptr(npath, "state"))
        if scope.kinds[target] in _ST_PSEUDO:
            raise v.error(ptr(npath, "state"), "a note cannot attach to a pseudo-state")
        side = v.enum(note["side"], ptr(npath, "side"), ("left", "right"))
        if ("text" in note) == ("lines" in note):
            raise v.error(npath if "text" not in note else ptr(npath, "lines"),
                          "give exactly one of text (one line) or lines (multi-line note)")
        if "text" in note:
            text = v.text(note["text"], ptr(npath, "text"), "stateDiagram.note-inline")
            lines.append(f"{indent}note {side} of {target} : {text}")
        else:
            lines.append(f"{indent}note {side} of {target}")
            for j, item in enumerate(v.array(note["lines"], ptr(npath, "lines"), min_items=1)):
                lines.append(f"{indent}    {v.text(item, ptr(ptr(npath, 'lines'), j), 'stateDiagram.note-line')}")
            lines.append(f"{indent}end note")


def _st_serialize(ir: dict, keyword: str) -> str:
    v = Validator(keyword)
    v.fields(ir, "", optional=("title", "config", "accessibility", "comment", "direction", "classDefs",
                               "classes", "styles") + _ST_BODY_KEYS)
    title = v.text(ir["title"], "/title", "stateDiagram.title") if "title" in ir else None
    config = validate_config(v, ir["config"], "/config", _ST_CONFIG) if "config" in ir else None
    if "accessibility" in ir:
        acc = v.fields(ir["accessibility"], "/accessibility", optional=("title", "description"))
        for key in acc:
            v.text(acc[key], ptr("/accessibility", key), "stateDiagram.accessibility")
    if "comment" in ir:
        v.text(ir["comment"], "/comment", "stateDiagram.comment")

    lines = emit_frontmatter(title, config) + [keyword]
    lines += emit_accessibility(v, ir)
    lines += emit_comment(v, ir)
    if "direction" in ir:
        lines.append(f"    direction {v.enum(ir['direction'], '/direction', _ST_DIRECTIONS)}")

    classes: set[str] = set()
    for i, cdef in enumerate(v.array(ir.get("classDefs", []), "/classDefs")):
        cpath = ptr("/classDefs", i)
        v.fields(cdef, cpath, required=("name", "style"))
        name = v.unique(_st_ident(v, cdef["name"], ptr(cpath, "name")), ptr(cpath, "name"), classes, "class name")
        lines.append(f"    classDef {name} {_st_style(v, cdef['style'], ptr(cpath, 'style'))}")

    scope = _StScope()
    _st_collect(v, ir, "", scope, set())
    _st_body(v, ir, "", scope, classes, True, lines, "    ")

    def simple_state(value: Any, at: str) -> str:
        sid = v.ref(value, at, scope.kinds)
        if scope.kinds[sid] != "simple":
            raise v.error(at, f"only a simple state can be styled; {sid!r} is a {scope.kinds[sid]} state")
        return sid

    for i, assign in enumerate(v.array(ir.get("classes", []), "/classes")):
        apath = ptr("/classes", i)
        v.fields(assign, apath, required=("class", "states"))
        targets = v.array(assign["states"], ptr(apath, "states"), min_items=1)
        ids = [simple_state(sid, ptr(ptr(apath, "states"), j)) for j, sid in enumerate(targets)]
        name = v.ref(assign["class"], ptr(apath, "class"), classes)
        line = f"    class {', '.join(ids)} {name}"
        if re.search(_ST_DIRECTION_HAZARD[0], line):
            raise v.error(ptr(apath, "class"), _ST_DIRECTION_HAZARD[1])
        lines.append(line)
    for i, item in enumerate(v.array(ir.get("styles", []), "/styles")):
        spath = ptr("/styles", i)
        v.fields(item, spath, required=("state", "style"))
        sid = simple_state(item["state"], ptr(spath, "state"))
        lines.append(f"    style {sid} {_st_style(v, item['style'], ptr(spath, 'style'))}")
    return "\n".join(lines) + "\n"


register(Builder(
    "stateDiagram",
    "state-machine",
    ("stateDiagram-v2", "stateDiagram"),
    _st_serialize,
    text_fields=(
        "/title",
        "/comment",
        "/accessibility/title",
        "/accessibility/description",
        "/states/*/label",  # first match: colon form
        "/states/1/label",  # `state "..." as id`
        "/states/*/states/*/label",
        "/states/*/regions/*/states/*/label",
        "/transitions/*/label",
        "/transitions/*/comment",
        "/states/*/transitions/*/label",
        "/notes/*/text",
        "/notes/*/lines/*",
        "/states/*/regions/*/notes/*/text",
    ),
    features={
        "stateDiagram.keyword-v2": "/target=stateDiagram-v2",
        "stateDiagram.keyword-legacy": "/target=stateDiagram",
        "stateDiagram.state-id": "/states/*/id",
        "stateDiagram.state-description-as": "/states/*/labelForm=as",
        "stateDiagram.state-description-colon": "/states/*/labelForm=colon",
        "stateDiagram.transition": "/transitions/*/to",
        "stateDiagram.transition-label": "/transitions/*/label",
        "stateDiagram.start": "/initial",
        "stateDiagram.end": "/transitions/*/to=[*]",
        "stateDiagram.composite": "/states/*/states/*/id",
        "stateDiagram.composite-named": "/states/13/label",
        "stateDiagram.composite-nested": "/states/*/states/*/states/*/id",
        "stateDiagram.composite-transition": "/transitions/*/from=First",
        "stateDiagram.choice": "/states/*/kind=choice",
        "stateDiagram.fork": "/states/*/kind=fork",
        "stateDiagram.join": "/states/*/kind=join",
        "stateDiagram.note-right-block": "/notes/*/lines",
        "stateDiagram.note-left-inline": "/notes/*/text",
        "stateDiagram.concurrency": "/states/*/regions/1/states",
        "stateDiagram.direction": "/direction",
        "stateDiagram.direction-composite": "/states/*/direction",
        "stateDiagram.comment": "/comment",
        "stateDiagram.comment-trailing": "/transitions/*/comment",
        "stateDiagram.classdef": "/classDefs/*/style",
        "stateDiagram.class-apply": "/classes/*/states/0",
        "stateDiagram.class-apply-list": "/classes/*/states/1",
        "stateDiagram.class-shorthand": "/transitions/*/fromClass",
        "stateDiagram.accessibility": "/accessibility/title",
        "stateDiagram.spaces-in-names": "/states/*/label=Your state with spaces in it",
    },
    probes={"object": "/states/0", "number": "/config/state/padding", "enum": "/direction",
            "ref": "/transitions/0/to"},
))

# --- end stateDiagram ---

# --- entityRelationshipDiagram ---
#
# IR (family `graph`, keyword `erDiagram`): entities in `nodes` (typed `attributes`), relationships
# in `edges` (cardinality enums per side, with an optional spelling `left_form`/`right_form`),
# nested `subgraphs` with member refs, typed `styles`, `class_defs`, `class_assignments`.
# Lexer facts from Mermaid 12.0.0 (erDiagram jison, all rules case-insensitive):
# - a quoted name is an entity name only without `"`, `%`, `\`; every ENTITY code renders back,
#   so quoted text encodes all of ENTITY (also keeps `#word;` and `%%` from being read).
# - any line containing `direction <TB|BT|RL|LR>` becomes a direction statement, even inside
#   quotes, so that phrase is rejected in text that lands on an ordinary line.
# - bare words starting with a keyword or cardinality word (`end`, `one`, `many`, `to`, `u-`,
#   `class`, `style`, ...) are read as that token, so such ids are rejected.
# - style values are lexed as words, `#`, `:` and `,`: no `rgb()`, no decimals, spaces vanish.

_ER_RESERVED = frozenset({
    "erdiagram", "end", "subgraph", "style", "classdef", "class", "direction", "acctitle",
    "accdescr", "one", "many", "only", "to", "optionally", "zero", "u",
})
_ER_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:-[A-Za-z0-9_]+)*")
_ER_BARE_TEXT = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
_ER_ATTR_TYPE = re.compile(r"[A-Za-z\u00C0-\uFFFF][A-Za-z0-9_\-\u00C0-\uFFFF]*")
_ER_ATTR_NAME = re.compile(r"\*?[A-Za-z_\u00C0-\uFFFF][A-Za-z0-9_\-\u00C0-\uFFFF]*")
_ER_KEYS = ("PK", "FK", "UK")
_ER_DIRECTIONS = ("TB", "BT", "LR", "RL")
_ER_DIRECTION_PHRASE = (r"(?i)direction\s+(TB|BT|RL|LR)", "a line containing 'direction TB|BT|RL|LR' is read as a direction statement")

for _er_name in ("entity-name", "alias", "label", "subgraph-name", "subgraph-title"):
    text_context(f"entityRelationshipDiagram.{_er_name}", encode=ENTITY, reject_patterns=(_ER_DIRECTION_PHRASE,))
text_context("entityRelationshipDiagram.attribute-comment", encode=ENTITY)
text_context("entityRelationshipDiagram.title")  # frontmatter YAML string, rendered literally

# Cardinality -> spelling -> (token on the left side, token on the right side).
_ER_FORMS: dict[str, dict[str, tuple[str, str]]] = {
    "zero_or_one": {
        "symbol": ("|o", "o|"), "mirrored": ("o|", "|o"),
        "one-or-zero": ("one or zero",) * 2, "zero-or-one": ("zero or one",) * 2,
    },
    "exactly_one": {"symbol": ("||", "||"), "only-one": ("only one",) * 2, "one": ("one",) * 2, "1": ("1",) * 2},
    "zero_or_more": {
        "symbol": ("}o", "o{"), "mirrored": ("o{", "}o"), "zero-or-more": ("zero or more",) * 2,
        "zero-or-many": ("zero or many",) * 2, "many-0": ("many(0)",) * 2, "0-plus": ("0+",) * 2,
        "many": ("many",) * 2,
    },
    "one_or_more": {
        "symbol": ("}|", "|{"), "mirrored": ("|{", "}|"), "one-or-more": ("one or more",) * 2,
        "one-or-many": ("one or many",) * 2, "many-1": ("many(1)",) * 2, "1-plus": ("1+",) * 2,
    },
}
_ER_CONNECTORS = {("symbol", True): "--", ("symbol", False): "..", ("words", True): "to", ("words", False): "optionally to"}

_ER_SIZE = r"^\d+(px|pt|em)?$"
_ER_STYLE_PROPS: dict[str, tuple[str, Any]] = {
    # IR key -> (CSS property, check): "color", a regex, or a tuple of allowed values.
    "fill": ("fill", "color"),
    "stroke": ("stroke", "color"),
    "color": ("color", "color"),
    "strokeWidth": ("stroke-width", _ER_SIZE),
    "strokeDasharray": ("stroke-dasharray", r"^\d+(px)?$"),
    "fontSize": ("font-size", _ER_SIZE),
    "fontWeight": ("font-weight", ("normal", "bold", "bolder", "lighter", "100", "200", "300", "400", "500", "600", "700", "800", "900")),
    "fontStyle": ("font-style", ("normal", "italic", "oblique")),
}
text_context("entityRelationshipDiagram.style-color", reject_patterns=((r"^(?!#(?:[0-9A-Fa-f]{3,4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$|[a-z]+$)", "must be #hex or a lowercase CSS color name (the ER style lexer has no rgb()/hsl())"),))

_ER_CONFIG = {
    "theme": ("enum", ("default", "base", "dark", "forest", "neutral", "neo", "neo-dark", "redux", "redux-dark", "redux-color", "redux-dark-color")),
    "look": ("enum", ("classic", "handDrawn", "neo")),
    "layout": ("enum", ("dagre", "elk")),
    "er": {
        "layoutDirection": ("enum", _ER_DIRECTIONS),
        "titleTopMargin": ("number", 0, None),
        "diagramPadding": ("number", 0, None),
        "minEntityWidth": ("number", 0, None),
        "minEntityHeight": ("number", 0, None),
        "entityPadding": ("number", 0, None),
        "nodeSpacing": ("number", 0, None),
        "rankSpacing": ("number", 0, None),
        "fontSize": ("number", 0, None),
        "stroke": ("color",),
        "fill": ("color",),
        "useMaxWidth": ("boolean",),
    },
}


def _er_ident(v: Validator, value: Any, path: str, what: str) -> str:
    """A bare entity/subgraph/class id the ER lexer reads as one word."""
    v.ident(value, path, _ER_ID)
    if value.split("-", 1)[0].lower() in _ER_RESERVED:
        raise v.error(path, f"{what} {value!r} starts with an erDiagram keyword or cardinality word; use another id (or `name` for the displayed text)")
    return value


def _er_quotable(v: Validator, value: Any, path: str, context: str, *, bare_ok: bool) -> str:
    """Encoded text, bare when it is one safe word and `bare_ok`, else in double quotes."""
    text = v.text(value, path, context)
    if bare_ok and _ER_BARE_TEXT.fullmatch(value) and value.lower() not in _ER_RESERVED:
        return text
    return f'"{text}"'


def _er_style(v: Validator, value: Any, path: str) -> str:
    v.fields(value, path, optional=tuple(_ER_STYLE_PROPS))
    if not value:
        raise v.error(path, "must set at least one style property")
    parts = []
    for key, (css, check) in _ER_STYLE_PROPS.items():
        if key not in value:
            continue
        sub, item = ptr(path, key), value[key]
        if check == "color":
            v.text(item, sub, "entityRelationshipDiagram.style-color")
        elif isinstance(check, tuple):
            v.enum(item, sub, check)
        elif not isinstance(item, str) or not re.fullmatch(check, item):
            raise v.error(sub, f"must match {check}, got {json.dumps(item)} (the ER style lexer has no decimals or spaces)")
        parts.append(f"{css}:{item}")
    return ",".join(parts)


def _er_id_list(v: Validator, value: Any, path: str, known: Any, what: str) -> list[str]:
    seen: set[str] = set()
    out = []
    for i, item in enumerate(v.array(value, path, 1)):
        sub = ptr(path, i)
        v.unique(v.ref(item, sub, known), sub, seen, what)
        out.append(item)
    return out


def _er_attribute(v: Validator, attr: Any, path: str) -> str:
    v.fields(attr, path, ("type", "name"), ("params", "array", "optional", "keys", "comment"))
    type_ = v.ident(attr["type"], ptr(path, "type"), _ER_ATTR_TYPE)
    name = v.ident(attr["name"], ptr(path, "name"), _ER_ATTR_NAME)
    for key, word in (("type", type_), ("name", name)):
        if word.lower() in ("pk", "fk", "uk"):
            raise v.error(ptr(path, key), f"{word!r} is read as a key marker; use another {key}")
    if "params" in attr:
        params = v.array(attr["params"], ptr(path, "params"), 1)
        type_ += "(" + ",".join(v.number(n, ptr(ptr(path, "params"), i), 0, integer=True) for i, n in enumerate(params)) + ")"
    if "array" in attr and v.boolean(attr["array"], ptr(path, "array")):
        type_ += "[]"
    if "optional" in attr and v.boolean(attr["optional"], ptr(path, "optional")):
        type_ += "?"
    line = f"{type_} {name}"
    if "keys" in attr:
        seen: set[str] = set()
        keys = [
            v.unique(v.enum(k, ptr(ptr(path, "keys"), i), _ER_KEYS), ptr(ptr(path, "keys"), i), seen, "key")
            for i, k in enumerate(v.array(attr["keys"], ptr(path, "keys"), 1))
        ]
        line += " " + ", ".join(keys)
    if "comment" in attr:
        line += f' "{v.text(attr["comment"], ptr(path, "comment"), "entityRelationshipDiagram.attribute-comment")}"'
    return line


def _er_serialize(ir: dict, keyword: str) -> str:
    v = Validator(keyword)
    v.fields(
        ir, "", ("nodes",),
        ("title", "config", "accessibility", "comment", "direction", "edges", "subgraphs", "styles", "class_defs", "class_assignments"),
    )
    title = None
    if "title" in ir:
        v.text(ir["title"], "/title", "entityRelationshipDiagram.title")
        title = ir["title"]
    config = validate_config(v, ir["config"], "/config", _ER_CONFIG) if "config" in ir else None

    # Mermaid entity names (unquoted) must be unique across entities and subgraphs.
    names: set[str] = set()

    def claim(raw: str, path: str) -> None:
        if raw in names:
            raise v.error(path, f"duplicate entity or subgraph name {json.dumps(raw)}")
        names.add(raw)

    # Pass 1: classes, then entity and subgraph ids (references may point forward).
    class_lines: list[str] = []
    classes: set[str] = set()
    for i, cdef in enumerate(v.array(ir.get("class_defs", []), "/class_defs")):
        path = f"/class_defs/{i}"
        v.fields(cdef, path, ("names", "style"))
        cnames = []
        for j, cname in enumerate(v.array(cdef["names"], ptr(path, "names"), 1)):
            sub = ptr(ptr(path, "names"), j)
            cnames.append(v.unique(_er_ident(v, cname, sub, "class name"), sub, classes, "class name"))
        class_lines.append(f"    classDef {','.join(cnames)} {_er_style(v, cdef['style'], ptr(path, 'style'))}")

    def class_list(value: Any, path: str) -> str:
        return ",".join(_er_id_list(v, value, path, classes, "class"))

    refs: dict[str, str] = {}  # IR id -> Mermaid reference (bare id or quoted name)
    bare_nodes: set[str] = set()
    node_lines: list[str] = []
    nodes = v.array(ir["nodes"], "/nodes", 1)
    for i, node in enumerate(nodes):
        path = f"/nodes/{i}"
        v.fields(node, path, ("id",), ("name", "label", "attributes", "classes"))
        node_id = _er_ident(v, node["id"], ptr(path, "id"), "entity id")
        if node_id in refs:
            raise v.error(ptr(path, "id"), f"duplicate id {json.dumps(node_id)}")
        if "name" in node:
            refs[node_id] = f'"{v.text(node["name"], ptr(path, "name"), "entityRelationshipDiagram.entity-name")}"'
            claim(node["name"], ptr(path, "name"))
        else:
            refs[node_id] = node_id
            bare_nodes.add(node_id)
            claim(node_id, ptr(path, "id"))
    node_ids = set(refs)

    for i, node in enumerate(nodes):
        path = f"/nodes/{i}"
        head = refs[node["id"]]
        if "label" in node:
            head += f"[{_er_quotable(v, node['label'], ptr(path, 'label'), 'entityRelationshipDiagram.alias', bare_ok=True)}]"
        if "classes" in node:
            head += f":::{class_list(node['classes'], ptr(path, 'classes'))}"
        attributes = v.array(node.get("attributes", []), ptr(path, "attributes"))
        if not attributes:
            node_lines.append(f"    {head}")
            continue
        node_lines.append(f"    {head} {{")
        for j, attr in enumerate(attributes):
            node_lines.append(f"        {_er_attribute(v, attr, ptr(ptr(path, 'attributes'), j))}")
        node_lines.append("    }")

    # Subgraphs: collect ids first so edges and members can be checked.
    subgraph_ids: set[str] = set()

    def collect(groups: Any, path: str) -> None:
        for i, group in enumerate(v.array(groups, path)):
            sub = ptr(path, i)
            v.fields(group, sub, ("id",), ("name", "title", "direction", "members", "subgraphs"))
            gid = _er_ident(v, group["id"], ptr(sub, "id"), "subgraph id")
            if gid in node_ids or gid in subgraph_ids:
                raise v.error(ptr(sub, "id"), f"duplicate id {json.dumps(gid)}")
            subgraph_ids.add(gid)
            if "name" in group:
                refs[gid] = f'"{v.text(group["name"], ptr(sub, "name"), "entityRelationshipDiagram.subgraph-name")}"'
                claim(group["name"], ptr(sub, "name"))
            else:
                refs[gid] = gid
                claim(gid, ptr(sub, "id"))
            if "subgraphs" in group:
                collect(group["subgraphs"], ptr(sub, "subgraphs"))

    collect(ir.get("subgraphs", []), "/subgraphs")

    placed: set[str] = set()
    subgraph_lines: list[str] = []

    def emit_groups(groups: list, path: str, indent: str) -> None:
        for i, group in enumerate(groups):
            sub = ptr(path, i)
            header = f"{indent}subgraph {refs[group['id']]}"
            if "title" in group:
                header += f' ["{v.text(group["title"], ptr(sub, "title"), "entityRelationshipDiagram.subgraph-title")}"]'
            subgraph_lines.append(header)
            inner = indent + "    "
            if "direction" in group:
                subgraph_lines.append(f"{inner}direction {v.enum(group['direction'], ptr(sub, 'direction'), _ER_DIRECTIONS)}")
            for j, member in enumerate(v.array(group.get("members", []), ptr(sub, "members"))):
                mpath = ptr(ptr(sub, "members"), j)
                v.ref(member, mpath, node_ids)
                if member in placed:
                    raise v.error(mpath, f"entity {json.dumps(member)} is already in a subgraph")
                placed.add(member)
                subgraph_lines.append(f"{inner}{refs[member]}")
            emit_groups(group.get("subgraphs", []), ptr(sub, "subgraphs"), inner)
            subgraph_lines.append(f"{indent}end")

    emit_groups(ir.get("subgraphs", []), "/subgraphs", "    ")

    endpoints = node_ids | subgraph_ids
    edge_lines: list[str] = []
    for i, edge in enumerate(v.array(ir.get("edges", []), "/edges")):
        path = f"/edges/{i}"
        v.fields(
            edge, path, ("from", "to", "label", "left", "right"),
            ("identifying", "left_form", "right_form", "connector_form", "from_classes", "to_classes"),
        )
        ends = []
        for side in ("from", "to"):
            target = v.ref(edge[side], ptr(path, side), endpoints)
            text = refs[target]
            key = f"{side}_classes"
            if key in edge:
                if target in subgraph_ids:
                    raise v.error(ptr(path, key), "a subgraph endpoint cannot take ':::' classes")
                text += f":::{class_list(edge[key], ptr(path, key))}"
            ends.append(text)
        tokens = []
        for index, side in enumerate(("left", "right")):
            card = v.enum(edge[side], ptr(path, side), tuple(_ER_FORMS))
            form = v.enum(edge.get(f"{side}_form", "symbol"), ptr(path, f"{side}_form"), tuple(_ER_FORMS[card]))
            tokens.append(_ER_FORMS[card][form][index])
        identifying = v.boolean(edge.get("identifying", True), ptr(path, "identifying"))
        connector_form = v.enum(edge.get("connector_form", "symbol"), ptr(path, "connector_form"), ("symbol", "words"))
        connector = _ER_CONNECTORS[(connector_form, identifying)]
        if connector_form == "symbol":
            relation = f"{tokens[0]}{connector}{tokens[1]}"
        else:
            relation = f"{tokens[0]} {connector} {tokens[1]}"
        label = _er_quotable(v, edge["label"], ptr(path, "label"), "entityRelationshipDiagram.label", bare_ok=True)
        edge_lines.append(f"    {ends[0]} {relation} {ends[1]} : {label}")

    def bare_targets(value: Any, path: str) -> str:
        ids = _er_id_list(v, value, path, node_ids, "entity")
        for j, item in enumerate(ids):
            if item not in bare_nodes:
                raise v.error(ptr(path, j), f"entity {json.dumps(item)} has a quoted `name`; style and class statements need a bare id (use the entity's `classes`)")
        return ",".join(ids)

    style_lines = []
    for i, rule in enumerate(v.array(ir.get("styles", []), "/styles")):
        path = f"/styles/{i}"
        v.fields(rule, path, ("nodes", "style"))
        style_lines.append(f"    style {bare_targets(rule['nodes'], ptr(path, 'nodes'))} {_er_style(v, rule['style'], ptr(path, 'style'))}")
    assign_lines = []
    for i, rule in enumerate(v.array(ir.get("class_assignments", []), "/class_assignments")):
        path = f"/class_assignments/{i}"
        v.fields(rule, path, ("nodes", "classes"))
        assign_lines.append(f"    class {bare_targets(rule['nodes'], ptr(path, 'nodes'))} {class_list(rule['classes'], ptr(path, 'classes'))}")

    lines = emit_frontmatter(title, config) + ["erDiagram"]
    lines += emit_accessibility(v, ir)
    lines += emit_comment(v, ir)
    if "direction" in ir:
        lines.append(f"    direction {v.enum(ir['direction'], '/direction', _ER_DIRECTIONS)}")
    lines += node_lines + subgraph_lines + edge_lines + style_lines + class_lines + assign_lines
    return "\n".join(lines) + "\n"


register(Builder(
    "entityRelationshipDiagram", "graph", ("erDiagram",), _er_serialize,
    text_fields=(
        "/title", "/comment", "/accessibility/title", "/accessibility/description",
        "/nodes/*/name", "/nodes/*/label", "/nodes/*/attributes/*/comment", "/edges/*/label",
        "/subgraphs/*/name", "/subgraphs/*/title",
    ),
    features={
        "entityRelationshipDiagram.keyword": "/target=erDiagram",
        "entityRelationshipDiagram.entity-only": "/nodes/*/id=LONELY",
        "entityRelationshipDiagram.relationship": "/edges/*/label=places",
        "entityRelationshipDiagram.label-quoted": "/edges/*/label=appears in",
        "entityRelationshipDiagram.entity-quoted-name": "/nodes/*/name=name with space",
        "entityRelationshipDiagram.entity-unicode": "/nodes/*/name=This ❤ Unicode",
        "entityRelationshipDiagram.entity-markdown": "/nodes/*/name=This **is** _Markdown_",
        "entityRelationshipDiagram.cardinality-zero-or-one-left": "/edges/*/left=zero_or_one",
        "entityRelationshipDiagram.cardinality-zero-or-one-right": "/edges/*/right=zero_or_one",
        "entityRelationshipDiagram.cardinality-exactly-one-left": "/edges/*/left=exactly_one",
        "entityRelationshipDiagram.cardinality-exactly-one-right": "/edges/*/right=exactly_one",
        "entityRelationshipDiagram.cardinality-zero-or-more-left": "/edges/*/left=zero_or_more",
        "entityRelationshipDiagram.cardinality-zero-or-more-right": "/edges/*/right=zero_or_more",
        "entityRelationshipDiagram.cardinality-one-or-more-left": "/edges/*/left=one_or_more",
        "entityRelationshipDiagram.cardinality-one-or-more-right": "/edges/*/right=one_or_more",
        "entityRelationshipDiagram.cardinality-reversed-marker": "/edges/*/left_form=mirrored",
        "entityRelationshipDiagram.alias-one-or-zero": "/edges/*/left_form=one-or-zero",
        "entityRelationshipDiagram.alias-zero-or-one": "/edges/*/left_form=zero-or-one",
        "entityRelationshipDiagram.alias-one-or-more": "/edges/*/left_form=one-or-more",
        "entityRelationshipDiagram.alias-one-or-many": "/edges/*/left_form=one-or-many",
        "entityRelationshipDiagram.alias-many-1": "/edges/*/left_form=many-1",
        "entityRelationshipDiagram.alias-1-plus": "/edges/*/left_form=1-plus",
        "entityRelationshipDiagram.alias-zero-or-more": "/edges/*/left_form=zero-or-more",
        "entityRelationshipDiagram.alias-zero-or-many": "/edges/*/left_form=zero-or-many",
        "entityRelationshipDiagram.alias-many-0": "/edges/*/left_form=many-0",
        "entityRelationshipDiagram.alias-0-plus": "/edges/*/left_form=0-plus",
        "entityRelationshipDiagram.alias-only-one": "/edges/*/left_form=only-one",
        "entityRelationshipDiagram.alias-1": "/edges/*/right_form=1",
        "entityRelationshipDiagram.identifying": "/edges/*/identifying=true",
        "entityRelationshipDiagram.non-identifying": "/edges/*/identifying=false",
        "entityRelationshipDiagram.identifying-alias-to": "/edges/*/connector_form=words",
        "entityRelationshipDiagram.non-identifying-alias-optionally-to": "/edges/21/connector_form=words",
        "entityRelationshipDiagram.attributes": "/nodes/*/attributes/*/type",
        "entityRelationshipDiagram.attribute-type-params": "/nodes/*/attributes/*/params",
        "entityRelationshipDiagram.attribute-type-array": "/nodes/*/attributes/*/array=true",
        "entityRelationshipDiagram.attribute-optional-type": "/nodes/*/attributes/*/optional=true",
        "entityRelationshipDiagram.attribute-name-asterisk": "/nodes/*/attributes/*/name=*id",
        "entityRelationshipDiagram.key-pk": "/nodes/*/attributes/*/keys/*=PK",
        "entityRelationshipDiagram.key-fk": "/nodes/*/attributes/*/keys/*=FK",
        "entityRelationshipDiagram.key-uk": "/nodes/*/attributes/*/keys/*=UK",
        "entityRelationshipDiagram.key-multiple": "/nodes/*/attributes/*/keys/1",
        "entityRelationshipDiagram.attribute-comment": "/nodes/*/attributes/*/comment",
        "entityRelationshipDiagram.entity-alias": "/nodes/*/label=Person",
        "entityRelationshipDiagram.entity-alias-quoted": "/nodes/*/label=Customer Account",
        "entityRelationshipDiagram.direction-tb": "/direction=TB",
        "entityRelationshipDiagram.direction-bt": "/direction=BT",
        "entityRelationshipDiagram.direction-lr": "/direction=LR",
        "entityRelationshipDiagram.direction-rl": "/direction=RL",
        "entityRelationshipDiagram.subgraph": "/subgraphs/*/id=title1",
        "entityRelationshipDiagram.subgraph-quoted": "/subgraphs/*/name=Customer Domain",
        "entityRelationshipDiagram.subgraph-explicit-id": "/subgraphs/*/title",
        "entityRelationshipDiagram.subgraph-nested": "/subgraphs/*/subgraphs/*/id",
        "entityRelationshipDiagram.subgraph-relationship": "/edges/*/from=title1",
        "entityRelationshipDiagram.subgraph-quoted-reference": "/edges/*/from=customer_domain",
        "entityRelationshipDiagram.subgraph-direction": "/subgraphs/*/direction",
        "entityRelationshipDiagram.style": "/styles/*/style/fill",
        "entityRelationshipDiagram.style-list": "/styles/*/nodes/1",
        "entityRelationshipDiagram.classdef": "/class_defs/*/names/0=someclass",
        "entityRelationshipDiagram.classdef-multi": "/class_defs/*/names/1",
        "entityRelationshipDiagram.classdef-default": "/class_defs/*/names/*=default",
        "entityRelationshipDiagram.class-apply": "/class_assignments/*/nodes/0",
        "entityRelationshipDiagram.class-apply-list": "/class_assignments/*/nodes/1",
        "entityRelationshipDiagram.class-apply-multi": "/class_assignments/*/classes/1",
        "entityRelationshipDiagram.class-shorthand": "/nodes/*/classes/0",
        "entityRelationshipDiagram.class-shorthand-relationship": "/edges/*/from_classes/0",
        "entityRelationshipDiagram.class-shorthand-multi": "/nodes/*/classes/1",
    },
    probes={
        "object": "/nodes/1/attributes/0",
        "number": "/nodes/1/attributes/1/params/0",
        "enum": "/edges/0/left",
        "ref": "/edges/0/to",
    },
))

# --- end entityRelationshipDiagram ---


# === end group 1 ===


# === group 2: time and tree: gantt, timeline, userJourney, gitgraph, kanban, mindmap ====

_GANTT_TAGS = {"active", "done", "crit", "milestone"}


def _gantt_tags(bar: dict) -> list[str]:
    tags = bar.get("tags", [])
    unknown = [tag for tag in tags if tag not in _GANTT_TAGS]
    if unknown:
        raise IRError(f"timeline/gantt bar {bar['id']!r} has unknown tag(s) {unknown!r}")
    if len(set(tags)) != len(tags):
        raise IRError(f"timeline/gantt bar {bar['id']!r} repeats a tag: {tags!r}")
    if {"active", "done"}.issubset(tags):
        raise IRError(f"timeline/gantt bar {bar['id']!r} cannot be both active and done")
    if "milestone" in tags and ({"active", "done"} & set(tags)):
        raise IRError(f"timeline/gantt bar {bar['id']!r} cannot combine milestone with active/done")
    return list(tags)


def render_timeline_gantt(ir: dict) -> str:
    _require(ir, ("dateFormat", "sections"), "timeline/gantt")
    lines = ["gantt"]
    if ir.get("title"):
        lines.append(f"    title {ir['title']}")
    lines.append(f"    dateFormat {ir['dateFormat']}")
    if ir.get("axisFormat"):
        lines.append(f"    axisFormat {ir['axisFormat']}")
    for exclude in ir.get("excludes", []):
        lines.append(f"    excludes {exclude}")
    for section in ir["sections"]:
        _require(section, ("name", "bars"), "timeline/gantt section")
        lines.append(f"    section {section['name']}")
        for bar in section["bars"]:
            _require(bar, ("id", "label", "start", "end"), "timeline/gantt bar")
            label = str(bar["label"])
            if not label.strip() or ":" in label:
                raise IRError(
                    f"timeline/gantt bar {bar['id']!r} label must be non-empty and must not contain ':'; "
                    "Mermaid treats the first colon as the start of task metadata "
                    "(a colon in the title crashes the renderer with TypeError)"
                )
            bar_id = _identifier(bar["id"], "timeline/gantt bar")
            fields = _gantt_tags(bar) + [bar_id, bar["start"], bar["end"]]
            lines.append(f"    {label} :{', '.join(fields)}")
    return "\n".join(lines) + "\n"


def render_timeline_events(ir: dict) -> str:
    if not ir.get("sections") and not ir.get("events"):
        raise IRError("timeline/timeline requires 'sections' or 'events'")
    direction = ir.get("direction")
    if direction is not None and direction not in ("LR", "TD"):
        raise IRError(f"timeline/timeline has unknown direction {direction!r}; use LR or TD")
    lines = [f"timeline {direction}" if direction else "timeline"]
    if ir.get("title"):
        lines.append(f"    title {_no_colon(ir['title'], 'timeline/timeline title')}")

    def emit_event(event: dict, indent: str) -> None:
        _require(event, ("period", "text"), "timeline/timeline event")
        period = _no_colon(event["period"], "timeline/timeline period")
        texts = event["text"] if isinstance(event["text"], list) else [event["text"]]
        if not texts:
            raise IRError("timeline/timeline event requires at least one text value")
        rendered = [_no_colon(text, "timeline/timeline event text") for text in texts]
        lines.append(f"{indent}{period} : " + " : ".join(rendered))

    if ir.get("sections"):
        for section in ir["sections"]:
            _require(section, ("name", "events"), "timeline/timeline section")
            lines.append(f"    section {_no_colon(section['name'], 'timeline/timeline section')}")
            for event in section["events"]:
                emit_event(event, "        ")
    else:
        for event in ir["events"]:
            emit_event(event, "    ")
    return "\n".join(lines) + "\n"


def render_journey(ir: dict) -> str:
    _require(ir, ("sections",), "journey/journey")
    lines = ["journey"]
    if ir.get("title"):
        lines.append(f"    title {_no_colon(ir['title'], 'journey/journey title')}")
    for section in ir["sections"]:
        _require(section, ("name", "tasks"), "journey/journey section")
        lines.append(f"    section {_no_colon(section['name'], 'journey/journey section')}")
        for task in section["tasks"]:
            _require(task, ("name", "score", "actors"), "journey/journey task")
            score = task["score"]
            if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
                raise IRError(f"journey/journey task {task['name']!r} score must be an integer from 1 to 5")
            if not task["actors"]:
                raise IRError(f"journey/journey task {task['name']!r} requires actors")
            actors = [_no_colon(actor, "journey actor") for actor in task["actors"]]
            lines.append(
                f"        {_no_colon(task['name'], 'journey task')}: {score}: {', '.join(actors)}"
            )
    return "\n".join(lines) + "\n"


def render_git(ir: dict) -> str:
    _require(ir, ("ops",), "git/gitGraph")
    if not ir["ops"]:
        raise IRError("git/gitGraph requires ops")
    lines: list[str] = []
    if ir.get("title"):
        lines.extend(["---", f"title: {_quote(ir['title'])}", "---"])
    lines.append("gitGraph")
    for op in ir["ops"]:
        _require(op, ("type",), "git/gitGraph op")
        kind = op["type"]
        if kind == "commit":
            parts = ["    commit"]
            if op.get("id"):
                parts.append(f"id: {_quote(_identifier(op['id'], 'git/gitGraph commit'))}")
            if op.get("tag"):
                parts.append(f"tag: {_quote(_no_colon(op['tag'], 'git/gitGraph tag'))}")
            lines.append(" ".join(parts))
        elif kind == "branch":
            _require(op, ("name",), "git/gitGraph branch")
            lines.append(f"    branch {_identifier(op['name'], 'git/gitGraph branch')}")
        elif kind in ("checkout", "switch"):
            _require(op, ("name",), "git/gitGraph checkout")
            lines.append(f"    checkout {_identifier(op['name'], 'git/gitGraph checkout')}")
        elif kind == "merge":
            _require(op, ("name",), "git/gitGraph merge")
            lines.append(f"    merge {_identifier(op['name'], 'git/gitGraph merge')}")
        else:
            raise IRError(f"git/gitGraph op has unknown type {kind!r}")
    return "\n".join(lines) + "\n"


_KANBAN_PRIORITIES = {"Very High", "High", "Low", "Very Low"}


def render_kanban(ir: dict) -> str:
    _require(ir, ("columns",), "board/kanban")
    if not ir["columns"]:
        raise IRError("board/kanban requires columns")
    lines = ["kanban"]
    seen: set[str] = set()
    for column in ir["columns"]:
        _require(column, ("id", "label", "cards"), "board/kanban column")
        column_id = _identifier(column["id"], "board/kanban column")
        if "]" in str(column["label"]):
            raise IRError(f"board/kanban column {column_id!r} label must not contain ']'")
        lines.append(f"    {column_id}[{column['label']}]")
        seen.add(column_id)
        for card in column["cards"]:
            _require(card, ("id", "label"), "board/kanban card")
            card_id = _identifier(card["id"], "board/kanban card")
            if card_id in seen:
                raise IRError(f"board/kanban duplicate id {card_id!r}")
            seen.add(card_id)
            if "]" in str(card["label"]):
                raise IRError(f"board/kanban card {card_id!r} label must not contain ']'")
            meta = []
            for key in ("assigned", "ticket"):
                if card.get(key):
                    meta.append(f"{key}: {_quote(card[key])}")
            if card.get("priority"):
                if card["priority"] not in _KANBAN_PRIORITIES:
                    raise IRError(f"board/kanban card {card_id!r} has unknown priority {card['priority']!r}")
                meta.append(f"priority: {_quote(card['priority'])}")
            suffix = f"@{{ {', '.join(meta)} }}" if meta else ""
            lines.append(f"        {card_id}[{card['label']}]{suffix}")
    return "\n".join(lines) + "\n"


_MINDMAP_SHAPES = {
    "root": ("((", "))"),
    "circle": ("((", "))"),
    "square": ("[", "]"),
    "bang": ("))", "(("),
    "cloud": (")", "("),
}


def render_graph_mindmap(ir: dict) -> str:
    _require(ir, ("nodes", "edges", "root"), "graph/mindmap")
    nodes: dict[str, dict] = {}
    for node in ir["nodes"]:
        _require(node, ("id", "label"), "graph/mindmap node")
        if node["id"] in nodes:
            raise IRError(f"graph/mindmap has duplicate node id {node['id']!r}")
        nodes[node["id"]] = node
    if ir["root"] not in nodes:
        raise IRError(f"graph/mindmap root {ir['root']!r} is not a declared node")
    children: dict[str, list[str]] = {}
    for edge in ir["edges"]:
        _require(edge, ("from", "to"), "graph/mindmap edge")
        if edge["from"] not in nodes or edge["to"] not in nodes:
            raise IRError(f"graph/mindmap edge references undeclared node: {edge}")
        children.setdefault(edge["from"], []).append(edge["to"])

    lines = ["mindmap"]
    visited: set[str] = set()

    def emit(node_id: str, depth: int) -> None:
        if node_id in visited:
            raise IRError(
                f"graph/mindmap node {node_id!r} is reached more than once; mindmap requires a tree"
            )
        visited.add(node_id)
        node = nodes.get(node_id)
        if node is None:
            raise IRError(f"graph/mindmap edge references undeclared node {node_id!r}")
        kind = "root" if node_id == ir["root"] else node.get("kind", "default")
        if kind == "default":
            text = str(node["label"])
        else:
            open_, close = _MINDMAP_SHAPES.get(kind, ("", ""))
            if kind not in _MINDMAP_SHAPES:
                raise IRError(f"graph/mindmap node {node_id!r} has unknown kind {kind!r}")
            text = f'{open_}{node["label"]}{close}'
        lines.append("  " * (depth + 1) + text)
        for child in children.get(node_id, []):
            emit(child, depth + 1)

    emit(ir["root"], 0)
    unreachable = [node_id for node_id in nodes if node_id not in visited]
    if unreachable:
        raise IRError(
            f"graph/mindmap node(s) are not reachable from root {ir['root']!r}: {unreachable}"
        )
    return "\n".join(lines) + "\n"


register(Builder('gantt', 'timeline', ('gantt',), legacy(render_timeline_gantt)))
register(Builder('timeline', 'timeline', ('timeline',), legacy(render_timeline_events)))
register(Builder('userJourney', 'journey', ('journey',), legacy(render_journey)))
register(Builder('gitgraph', 'git', ('gitGraph',), legacy(render_git)))
register(Builder('kanban', 'board', ('kanban',), legacy(render_kanban)))
register(Builder('mindmap', 'graph', ('mindmap',), legacy(render_graph_mindmap)))

# === end group 2 ===


# === group 3: chart: pie, quadrantChart, xyChart, sankey, radar, treemap, venn ========

def render_chart_pie(ir: dict) -> str:
    _require(ir, ("slices",), "chart/pie")
    if not ir["slices"]:
        raise IRError("chart/pie requires at least one slice")
    header = "pie showData" if ir.get("showData") else "pie"
    lines = [header]
    if ir.get("title"):
        lines.append(f"    title {_no_colon(ir['title'], 'chart/pie title')}")
    for slice_ in ir["slices"]:
        _require(slice_, ("label", "value"), "chart/pie slice")
        label = _no_colon(slice_["label"], "chart/pie label")
        value = float(_positive_number(slice_["value"], "chart/pie value"))
        if value <= 0:
            raise IRError(f"chart/pie slice {label!r} value must be greater than 0")
        lines.append(f"    {_quote(label)} : {value}")
    return "\n".join(lines) + "\n"


def render_chart_quadrant(ir: dict) -> str:
    _require(ir, ("xAxis", "yAxis", "quadrants", "points"), "chart/quadrantChart")
    _require(ir["xAxis"], ("left", "right"), "chart/quadrantChart xAxis")
    _require(ir["yAxis"], ("bottom", "top"), "chart/quadrantChart yAxis")
    lines = ["quadrantChart"]
    if ir.get("title"):
        lines.append(f"    title {_no_colon(ir['title'], 'chart/quadrantChart title')}")
    lines.append(
        f"    x-axis {_no_colon(ir['xAxis']['left'], 'quadrant x')} --> {_no_colon(ir['xAxis']['right'], 'quadrant x')}"
    )
    lines.append(
        f"    y-axis {_no_colon(ir['yAxis']['bottom'], 'quadrant y')} --> {_no_colon(ir['yAxis']['top'], 'quadrant y')}"
    )
    for index in ("1", "2", "3", "4"):
        if index not in ir["quadrants"] and int(index) not in ir["quadrants"]:
            raise IRError(f"chart/quadrantChart missing quadrant {index}")
        label = ir["quadrants"].get(index, ir["quadrants"].get(int(index)))
        lines.append(f"    quadrant-{index} {_no_colon(label, 'quadrant label')}")
    for point in ir["points"]:
        _require(point, ("label", "x", "y"), "chart/quadrantChart point")
        x_value = float(_positive_number(point["x"], "quadrant x"))
        y_value = float(_positive_number(point["y"], "quadrant y"))
        if not 0 <= x_value <= 1 or not 0 <= y_value <= 1:
            raise IRError(f"chart/quadrantChart point {point['label']!r} must be inside 0..1")
        lines.append(f"    {_quote(_no_colon(point['label'], 'quadrant point'))}: [{x_value}, {y_value}]")
    return "\n".join(lines) + "\n"


def _xy_token(value: Any, where: str) -> str:
    text = str(value)
    if "," in text or "\n" in text:
        raise IRError(f"{where} must not contain commas or newlines")
    if re.fullmatch(r"[A-Za-z0-9_]+", text):
        return text
    return _quote(text)


def render_chart_xy(ir: dict) -> str:
    _require(ir, ("xAxis",), "chart/xychart")
    if not ir.get("bar") and not ir.get("line"):
        raise IRError("chart/xychart requires 'bar' and/or 'line'")
    orientation = ir.get("orientation", "vertical")
    if orientation not in ("vertical", "horizontal"):
        raise IRError(f"chart/xychart has unknown orientation {orientation!r}")
    header = "xychart horizontal" if orientation == "horizontal" else "xychart"
    lines = [header]
    if ir.get("title"):
        lines.append(f"    title {_quote(ir['title'])}")
    categories = [_xy_token(item, "chart/xychart x category") for item in ir["xAxis"]]
    if not categories:
        raise IRError("chart/xychart xAxis must not be empty")
    lines.append(f"    x-axis [{', '.join(categories)}]")
    y_axis = ir.get("yAxis")
    if y_axis is not None:
        _require(y_axis, ("label", "min", "max"), "chart/xychart yAxis")
        low = float(_positive_number(y_axis["min"], "chart/xychart y min"))
        high = float(_positive_number(y_axis["max"], "chart/xychart y max"))
        if low >= high:
            raise IRError("chart/xychart yAxis min must be less than max")
        lines.append(f"    y-axis {_quote(y_axis['label'])} {low} --> {high}")
    for series_name in ("bar", "line"):
        series = ir.get(series_name)
        if series is None:
            continue
        if len(series) != len(categories):
            raise IRError(f"chart/xychart {series_name} length must match xAxis")
        numbers = [_positive_number(item, f"chart/xychart {series_name}") for item in series]
        lines.append(f"    {series_name} [{', '.join(numbers)}]")
    return "\n".join(lines) + "\n"


def _sankey_cell(value: str) -> str:
    if "," in value or "\n" in value:
        return "'" + value.replace("'", "") + "'"
    return value


def render_chart_sankey(ir: dict) -> str:
    _require(ir, ("links",), "chart/sankey")
    if not ir["links"]:
        raise IRError("chart/sankey requires at least one link")
    lines = ["sankey"]
    for link in ir["links"]:
        _require(link, ("from", "to", "value"), "chart/sankey link")
        amount = float(_positive_number(link["value"], "chart/sankey value"))
        if amount < 0:
            raise IRError("chart/sankey value must not be negative")
        lines.append(f"{_sankey_cell(str(link['from']))},{_sankey_cell(str(link['to']))},{amount}")
    return "\n".join(lines) + "\n"


def render_chart_radar(ir: dict) -> str:
    _require(ir, ("axes", "curves"), "chart/radar-beta")
    if not ir["axes"] or not ir["curves"]:
        raise IRError("chart/radar-beta requires axes and curves")
    lines = ["radar-beta"]
    if ir.get("title"):
        lines.append(f"    title {_quote(ir['title'])}")
    axis_bits = []
    for axis in ir["axes"]:
        _require(axis, ("id", "label"), "chart/radar-beta axis")
        axis_id = _identifier(axis["id"], "chart/radar-beta axis")
        axis_bits.append(f'{axis_id}[{_quote(axis["label"])}]')
    lines.append("    axis " + ", ".join(axis_bits))
    for curve in ir["curves"]:
        _require(curve, ("id", "label", "values"), "chart/radar-beta curve")
        if len(curve["values"]) != len(ir["axes"]):
            raise IRError(f"chart/radar-beta curve {curve['id']!r} value count must match axes")
        curve_id = _identifier(curve["id"], "chart/radar-beta curve")
        numbers = [_positive_number(item, "chart/radar-beta value") for item in curve["values"]]
        lines.append(f"    curve {curve_id}[{_quote(curve['label'])}]{{{', '.join(numbers)}}}")
    if ir.get("max") is not None:
        lines.append(f"    max {_positive_number(ir['max'], 'chart/radar-beta max')}")
    if ir.get("min") is not None:
        lines.append(f"    min {_positive_number(ir['min'], 'chart/radar-beta min')}")
    return "\n".join(lines) + "\n"


def _emit_treemap(node: dict, lines: list[str], depth: int) -> None:
    _require(node, ("label",), "chart/treemap node")
    indent = "    " * (depth + 1)
    children = node.get("children", [])
    if children:
        lines.append(f"{indent}{_quote(node['label'])}")
        for child in children:
            _emit_treemap(child, lines, depth + 1)
        return
    _require(node, ("value",), "chart/treemap leaf")
    value = float(_positive_number(node["value"], "chart/treemap value"))
    if value < 0:
        raise IRError("chart/treemap leaf value must not be negative")
    lines.append(f"{indent}{_quote(node['label'])}: {value}")


def render_chart_treemap(ir: dict) -> str:
    _require(ir, ("nodes",), "chart/treemap")
    if not ir["nodes"]:
        raise IRError("chart/treemap requires nodes")
    lines = ["treemap-beta"]
    for node in ir["nodes"]:
        _emit_treemap(node, lines, 0)
    return "\n".join(lines) + "\n"


def render_chart_venn(ir: dict) -> str:
    _require(ir, ("sets",), "chart/venn")
    lines = ["venn-beta"]
    if ir.get("title"):
        lines.append(f"    title {_quote(ir['title'])}")
    known: set[str] = set()
    for item in ir["sets"]:
        if isinstance(item, str):
            set_id, label = item, None
        else:
            _require(item, ("id",), "chart/venn set")
            set_id, label = item["id"], item.get("label")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(set_id)):
            raise IRError(f"chart/venn set id {set_id!r} must be a bare identifier")
        known.add(str(set_id))
        suffix = f"[{_quote(label)}]" if label else ""
        lines.append(f"    set {set_id}{suffix}")
    for union in ir.get("unions", []):
        _require(union, ("sets", "label"), "chart/venn union")
        if len(union["sets"]) < 2:
            raise IRError("chart/venn union requires at least two sets")
        unknown = [name for name in union["sets"] if name not in known]
        if unknown:
            raise IRError(f"chart/venn union references undeclared set(s): {unknown}")
        lines.append(f"    union {','.join(union['sets'])}[{_quote(union['label'])}]")
    return "\n".join(lines) + "\n"


register(Builder('pie', 'chart', ('pie',), legacy(render_chart_pie)))
register(Builder('quadrantChart', 'chart', ('quadrantChart',), legacy(render_chart_quadrant)))
register(Builder('xyChart', 'chart', ('xychart',), legacy(render_chart_xy)))
register(Builder('sankey', 'chart', ('sankey',), legacy(render_chart_sankey)))
register(Builder('radar', 'chart', ('radar-beta',), legacy(render_chart_radar)))
register(Builder('treemap', 'chart', ('treemap-beta',), legacy(render_chart_treemap)))
register(Builder('venn', 'chart', ('venn-beta',), legacy(render_chart_venn)))

# === end group 3 ===


# === group 4: structure: c4, architecture, block, packet, requirementDiagram ==========

_C4_PERSON_SYSTEM_KINDS = {
    "person": "Person",
    "person_ext": "Person_Ext",
    "system": "System",
    "system_db": "SystemDb",
    "system_queue": "SystemQueue",
    "system_ext": "System_Ext",
    "system_db_ext": "SystemDb_Ext",
    "system_queue_ext": "SystemQueue_Ext",
}


_C4_CONTAINER_KINDS = {
    "container": "Container",
    "container_db": "ContainerDb",
    "container_queue": "ContainerQueue",
    "container_ext": "Container_Ext",
    "container_db_ext": "ContainerDb_Ext",
    "container_queue_ext": "ContainerQueue_Ext",
}


_C4_COMPONENT_KINDS = {
    "component": "Component",
    "component_db": "ComponentDb",
    "component_queue": "ComponentQueue",
    "component_ext": "Component_Ext",
    "component_db_ext": "ComponentDb_Ext",
    "component_queue_ext": "ComponentQueue_Ext",
}


_C4_NODE_KINDS = {**_C4_PERSON_SYSTEM_KINDS, **_C4_CONTAINER_KINDS, **_C4_COMPONENT_KINDS}


_C4_TECH_KINDS = set(_C4_CONTAINER_KINDS) | set(_C4_COMPONENT_KINDS)


_C4_DEPLOYMENT_KINDS = {
    "deployment_node": "Deployment_Node",
    "node": "Node",
    "node_left": "Node_L",
    "node_right": "Node_R",
}


_C4_TARGET_NODE_KINDS = {
    "C4Context": set(_C4_PERSON_SYSTEM_KINDS),
    "C4Container": set(_C4_PERSON_SYSTEM_KINDS) | set(_C4_CONTAINER_KINDS),
    "C4Component": set(_C4_NODE_KINDS),
    "C4Dynamic": set(_C4_NODE_KINDS),
    "C4Deployment": set(_C4_PERSON_SYSTEM_KINDS) | set(_C4_CONTAINER_KINDS),
}


_C4_BOUNDARY_KINDS = {
    "enterprise_boundary": "Enterprise_Boundary",
    "system_boundary": "System_Boundary",
    "container_boundary": "Container_Boundary",
    "boundary": "Boundary",
    **_C4_DEPLOYMENT_KINDS,
}


_C4_TARGET_BOUNDARY_KINDS = {
    "C4Context": {"enterprise_boundary", "system_boundary", "boundary"},
    "C4Container": {"container_boundary", "boundary"},
    "C4Component": {"container_boundary", "boundary"},
    "C4Dynamic": {"container_boundary", "boundary"},
    "C4Deployment": set(_C4_DEPLOYMENT_KINDS),
}


_C4_REL_KINDS = {
    "rel": "Rel",
    "birel": "BiRel",
    "rel_up": "Rel_U",
    "rel_down": "Rel_D",
    "rel_left": "Rel_L",
    "rel_right": "Rel_R",
    "rel_back": "Rel_Back",
    "rel_index": "RelIndex",
}


def render_graph_c4(ir: dict) -> str:
    target = ir.get("target")
    if target not in _C4_TARGET_NODE_KINDS:
        raise IRError(
            f"graph/c4 requires ir['target'] to be one of {sorted(_C4_TARGET_NODE_KINDS)} (got {target!r})"
        )
    _require(ir, ("nodes", "edges"), f"graph/{target}")
    allowed_node_kinds = _C4_TARGET_NODE_KINDS[target]
    allowed_boundary_kinds = _C4_TARGET_BOUNDARY_KINDS[target]
    lines = [target]
    if ir.get("title"):
        lines.append(f"    title {ir['title']}")

    known: set[str] = set()
    by_group: dict[str | None, list[dict]] = {}
    for node in ir["nodes"]:
        _require(node, ("id", "label", "kind"), f"graph/{target} node")
        by_group.setdefault(node.get("group"), []).append(node)

    def emit_node(node: dict, indent: str) -> None:
        kind = node["kind"]
        macro = _C4_NODE_KINDS.get(kind)
        if macro is None or kind not in allowed_node_kinds:
            raise IRError(f"graph/{target} node {node['id']!r} has unknown/unsupported kind {kind!r}")
        node_id = _identifier(node["id"], f"graph/{target} node")
        known.add(node["id"])
        args = [node_id, _quote(node["label"])]
        technology = node.get("technology")
        description = node.get("description")
        if kind in _C4_TECH_KINDS:
            if technology is not None:
                args.append(_quote(technology))
            elif description is not None:
                raise IRError(
                    f"graph/{target} node {node['id']!r} has 'description' but no 'technology'; "
                    "this macro takes technology before description"
                )
        elif technology is not None:
            raise IRError(f"graph/{target} node {node['id']!r} kind {kind!r} does not accept 'technology'")
        if description is not None:
            args.append(_quote(description))
        lines.append(f'{indent}{macro}({", ".join(args)})')

    groups_by_id: dict[str, dict] = {}
    children_by_parent: dict[str | None, list[dict]] = {}
    for group in ir.get("groups", []):
        _require(group, ("id", "label", "kind"), f"graph/{target} group")
        if group["kind"] not in allowed_boundary_kinds:
            raise IRError(f"graph/{target} group {group['id']!r} has unknown/unsupported kind {group['kind']!r}")
        groups_by_id[group["id"]] = group
        children_by_parent.setdefault(group.get("group"), []).append(group)

    def emit_group(group: dict, indent: str) -> None:
        macro = _C4_BOUNDARY_KINDS[group["kind"]]
        group_id = _identifier(group["id"], f"graph/{target} group")
        args = [group_id, _quote(group["label"])]
        if group["kind"] == "boundary":
            if not group.get("boundary_type"):
                raise IRError(f"graph/{target} group {group['id']!r} of kind 'boundary' requires 'boundary_type'")
            args.append(_quote(group["boundary_type"]))
        elif group.get("boundary_type"):
            raise IRError(
                f"graph/{target} group {group['id']!r} kind {group['kind']!r} does not accept 'boundary_type'"
            )
        if group["kind"] in _C4_DEPLOYMENT_KINDS:
            technology = group.get("technology")
            description = group.get("description")
            if technology is not None:
                args.append(_quote(technology))
            elif description is not None:
                raise IRError(
                    f"graph/{target} group {group['id']!r} has 'description' but no 'technology'; "
                    "deployment nodes take type before description"
                )
            if description is not None:
                args.append(_quote(description))
        lines.append(f'{indent}{macro}({", ".join(args)}) {{')
        for node in by_group.pop(group["id"], []):
            emit_node(node, indent + "    ")
        for child in children_by_parent.pop(group["id"], []):
            emit_group(child, indent + "    ")
        lines.append(f"{indent}}}")

    for group in children_by_parent.pop(None, []):
        emit_group(group, "    ")
    leftover_groups = [g for g in children_by_parent if g is not None]
    if leftover_groups:
        raise IRError(f"graph/{target} groups reference undeclared parent group(s): {leftover_groups}")

    for node in by_group.pop(None, []):
        emit_node(node, "    ")
    leftover_nodes = [g for g in by_group if g is not None]
    if leftover_nodes:
        raise IRError(f"graph/{target} nodes reference undeclared group(s): {leftover_nodes}")

    for edge in ir["edges"]:
        _require(edge, ("from", "to", "label"), f"graph/{target} edge")
        kind = edge.get("kind", "rel")
        macro = _C4_REL_KINDS.get(kind)
        if macro is None:
            raise IRError(f"graph/{target} edge has unknown kind {kind!r}")
        if kind == "rel_index" and target != "C4Dynamic":
            raise IRError("graph/c4 edge kind 'rel_index' is only valid on C4Dynamic")
        if edge["from"] not in known or edge["to"] not in known:
            raise IRError(f"graph/{target} edge references undeclared node: {edge}")
        args = [edge["from"], edge["to"], _quote(edge["label"])]
        if kind == "rel_index":
            if edge.get("technology"):
                raise IRError("graph/C4Dynamic rel_index does not take 'technology'")
            index = edge.get("index")
            if isinstance(index, bool) or not isinstance(index, int):
                raise IRError(f"graph/C4Dynamic rel_index edge requires an integer 'index': {edge}")
            args.insert(0, str(index))
        if edge.get("technology"):
            args.append(_quote(edge["technology"]))
        lines.append(f'    {macro}({", ".join(args)})')
    return "\n".join(lines) + "\n"


_ARCH_BASE_ICONS = {"cloud", "database", "disk", "internet", "server"}


_ARCH_SIDES = {"T", "B", "L", "R"}


_ARCH_ARROWS = {
    "none": ("", ""),
    "forward": ("", ">"),
    "backward": ("<", ""),
    "both": ("<", ">"),
}


def _arch_icon(icon: str, where: str) -> str:
    if icon in _ARCH_BASE_ICONS or ":" in icon:
        return icon
    raise IRError(
        f"{where} icon {icon!r} is not a built-in architecture icon {sorted(_ARCH_BASE_ICONS)}; "
        "use 'pack:icon-name' to reference a registered icon pack"
    )


def render_graph_architecture(ir: dict) -> str:
    _require(ir, ("nodes", "edges"), "graph/architecture-beta")
    lines = ["architecture-beta"]
    known: set[str] = set()

    groups_by_id: dict[str, dict] = {}
    children_by_parent: dict[str | None, list[dict]] = {}
    for group in ir.get("groups", []):
        _require(group, ("id", "label"), "graph/architecture-beta group")
        groups_by_id[group["id"]] = group
        children_by_parent.setdefault(group.get("group"), []).append(group)

    def emit_group(group: dict) -> None:
        group_id = _identifier(group["id"], "graph/architecture-beta group")
        parent_id = group.get("group")
        parent = f" in {_identifier(parent_id, 'graph/architecture-beta group')}" if parent_id else ""
        icon = group.get("icon")
        where = f"graph/architecture-beta group {group['id']!r}"
        icon_part = f"({_arch_icon(icon, where)})" if icon else "()"
        lines.append(f'    group {group_id}{icon_part}[{_quote(group["label"])}]{parent}')
        for child in children_by_parent.pop(group["id"], []):
            emit_group(child)

    for group in children_by_parent.pop(None, []):
        emit_group(group)
    leftover_groups = [g for g in children_by_parent if g is not None]
    if leftover_groups:
        raise IRError(f"graph/architecture-beta groups reference undeclared parent group(s): {leftover_groups}")

    for node in ir["nodes"]:
        _require(node, ("id",), "graph/architecture-beta node")
        kind = node.get("kind", "service")
        node_id = _identifier(node["id"], "graph/architecture-beta node")
        group_ref = node.get("group")
        if group_ref is not None and group_ref not in groups_by_id:
            raise IRError(f"graph/architecture-beta node {node['id']!r} references undeclared group {group_ref!r}")
        parent = f" in {_identifier(group_ref, 'graph/architecture-beta node')}" if group_ref else ""
        if kind == "junction":
            if node.get("label") or node.get("icon"):
                raise IRError(f"graph/architecture-beta junction {node['id']!r} cannot have a label or icon")
            lines.append(f"    junction {node_id}{parent}")
        elif kind == "service":
            _require(node, ("label",), "graph/architecture-beta service node")
            icon = node.get("icon")
            where = f"graph/architecture-beta node {node['id']!r}"
            icon_part = f"({_arch_icon(icon, where)})" if icon else "()"
            lines.append(f'    service {node_id}{icon_part}[{_quote(node["label"])}]{parent}')
        else:
            raise IRError(f"graph/architecture-beta node {node['id']!r} has unknown kind {kind!r}")
        known.add(node["id"])

    for edge in ir["edges"]:
        _require(edge, ("from", "to", "from_side", "to_side"), "graph/architecture-beta edge")
        if edge["from"] not in known or edge["to"] not in known:
            raise IRError(f"graph/architecture-beta edge references undeclared node: {edge}")
        if edge["from_side"] not in _ARCH_SIDES or edge["to_side"] not in _ARCH_SIDES:
            raise IRError(f"graph/architecture-beta edge has unknown side(s): {edge}")
        arrow_kind = edge.get("arrow", "none")
        arrow = _ARCH_ARROWS.get(arrow_kind)
        if arrow is None:
            raise IRError(f"graph/architecture-beta edge has unknown arrow kind {arrow_kind!r}")
        left_arrow, right_arrow = arrow
        from_suffix = "{group}" if edge.get("from_group") else ""
        to_suffix = "{group}" if edge.get("to_group") else ""
        lines.append(
            f'    {edge["from"]}{from_suffix}:{edge["from_side"]} {left_arrow}--{right_arrow} '
            f'{edge["to_side"]}:{edge["to"]}{to_suffix}'
        )
    return "\n".join(lines) + "\n"


_BLOCK_SHAPES = {
    "process": ("[", "]"),
    "terminator": ("([", "])"),
    "decision": ("{", "}"),
    "subprocess": ("[[", "]]"),
    "store": ("[(", ")]"),
    "connector": ("((", "))"),
    "io": ("[/", "/]"),
}


def render_graph_block(ir: dict) -> str:
    _require(ir, ("nodes", "edges"), "graph/block")
    ids: dict[str, str] = {}
    lines = ["block"]
    columns = ir.get("columns")
    if columns is not None:
        if not isinstance(columns, int) or isinstance(columns, bool) or columns < 1:
            raise IRError(f"graph/block 'columns' must be a positive integer, got {columns!r}")
        lines.append(f"  columns {columns}")
    by_group: dict[str | None, list[dict]] = {}
    for node in ir["nodes"]:
        _require(node, ("id", "label"), "graph/block node")
        by_group.setdefault(node.get("group"), []).append(node)

    def emit_node(node: dict, indent: str) -> None:
        node_id = _safe_id(node["id"], ids)
        shape = _BLOCK_SHAPES.get(node.get("kind", "process"))
        if shape is None:
            raise IRError(f"graph/block node {node['id']!r} has unknown kind {node.get('kind')!r}")
        open_, close = shape
        lines.append(f"{indent}{node_id}{open_}{_quote(node['label'])}{close}")

    for group in ir.get("groups", []):
        _require(group, ("id", "label"), "graph/block group")
        group_id = _safe_id(group["id"], ids)
        lines.append(f'  block:{group_id}[{_quote(group["label"])}]')
        for node in by_group.pop(group["id"], []):
            emit_node(node, "    ")
        lines.append("  end")
    for node in by_group.pop(None, []):
        emit_node(node, "  ")
    leftover = [group for group in by_group if group is not None]
    if leftover:
        raise IRError(f"graph/block nodes reference undeclared group(s): {leftover}")

    for edge in ir["edges"]:
        _require(edge, ("from", "to"), "graph/block edge")
        kind = edge.get("kind", "normal")
        if kind not in ("normal", "dependency"):
            raise IRError(
                f"graph/block edge has unknown kind {kind!r}; block edges are plain arrows only"
            )
        if edge["from"] not in ids or edge["to"] not in ids:
            raise IRError(f"graph/block edge references undeclared node/group: {edge}")
        if edge.get("label"):
            lines.append(f'  {ids[edge["from"]]}-- {_quote(edge["label"])} -->{ids[edge["to"]]}')
        else:
            lines.append(f'  {ids[edge["from"]]}-->{ids[edge["to"]]}')
    return "\n".join(lines) + "\n"


def render_packet(ir: dict) -> str:
    _require(ir, ("fields",), "packet/packet")
    if not ir["fields"]:
        raise IRError("packet/packet requires fields")
    lines = ["packet"]
    cursor = 0
    for field in ir["fields"]:
        _require(field, ("label",), "packet/packet field")
        label = _quote(field["label"])
        if "bits" in field:
            bits = field["bits"]
            if isinstance(bits, bool) or not isinstance(bits, int) or bits < 1:
                raise IRError(f"packet/packet field {field['label']!r} bits must be a positive integer")
            lines.append(f"    +{bits}: {label}")
            cursor += bits
            continue
        _require(field, ("start", "end"), "packet/packet field")
        start, end = field["start"], field["end"]
        if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int):
            raise IRError(f"packet/packet field {field['label']!r} start and end must be integers")
        if start < 0 or end < start:
            raise IRError(f"packet/packet field {field['label']!r} has an invalid range")
        if start != cursor:
            raise IRError(
                f"packet/packet field {field['label']!r} starts at {start}, expected {cursor} for a contiguous layout"
            )
        lines.append(f"    {start}: {label}" if start == end else f"    {start}-{end}: {label}")
        cursor = end + 1
    return "\n".join(lines) + "\n"


_REQUIREMENT_TYPES = {
    "requirement", "functionalRequirement", "interfaceRequirement",
    "performanceRequirement", "physicalRequirement", "designConstraint",
}


_REQUIREMENT_RISKS = {"low", "medium", "high"}


_REQUIREMENT_METHODS = {"analysis", "inspection", "test", "demonstration"}


_REQUIREMENT_LINK_KINDS = {"contains", "copies", "derives", "satisfies", "verifies", "refines", "traces"}


def render_requirement_links(ir: dict) -> str:
    _require(ir, ("requirements", "elements", "links"), "requirement-links")
    lines = ["requirementDiagram"]
    direction = _direction(ir, "requirement-links", allowed=_CARDINAL_DIRECTIONS)
    if direction:
        lines.append(f"    direction {direction}")
    known = set()
    for requirement in ir["requirements"]:
        _require(requirement, ("id", "text"), "requirement-links requirement")
        rtype = requirement.get("type", "requirement")
        if rtype not in _REQUIREMENT_TYPES:
            raise IRError(f"requirement {requirement['id']!r} has unknown type {rtype!r}")
        risk = requirement.get("risk")
        if risk is not None and risk not in _REQUIREMENT_RISKS:
            raise IRError(f"requirement {requirement['id']!r} has unknown risk {risk!r}")
        method = requirement.get("verify_method")
        if method is not None and method not in _REQUIREMENT_METHODS:
            raise IRError(f"requirement {requirement['id']!r} has unknown verify_method {method!r}")
        req_id = _identifier(requirement["id"], "requirement-links requirement")
        lines.append(f"    {rtype} {req_id} {{")
        lines.append(f"        id: {requirement['id']}")
        lines.append(f"        text: {_quote(requirement['text'])}")
        if risk:
            lines.append(f"        risk: {risk}")
        if method:
            lines.append(f"        verifymethod: {method}")
        lines.append("    }")
        known.add(requirement["id"])
    for element in ir["elements"]:
        _require(element, ("id", "type"), "requirement-links element")
        elem_id = _identifier(element["id"], "requirement-links element")
        lines.append(f"    element {elem_id} {{")
        lines.append(f"        type: {element['type']}")
        if element.get("docref"):
            lines.append(f"        docref: {element['docref']}")
        lines.append("    }")
        known.add(element["id"])
    for link in ir["links"]:
        _require(link, ("from", "to", "kind"), "requirement-links link")
        if link["kind"] not in _REQUIREMENT_LINK_KINDS:
            raise IRError(f"requirement-links link has unknown kind {link['kind']!r}")
        if link["from"] not in known or link["to"] not in known:
            raise IRError(f"requirement-links link references an undeclared requirement/element: {link}")
        lines.append(f'    {link["from"]} - {link["kind"]} -> {link["to"]}')
    return "\n".join(lines) + "\n"


register(Builder('c4', 'graph', ('C4Context', 'C4Container', 'C4Component', 'C4Dynamic', 'C4Deployment'), legacy(render_graph_c4)))
register(Builder('architecture', 'graph', ('architecture-beta',), legacy(render_graph_architecture)))
register(Builder('block', 'graph', ('block',), legacy(render_graph_block)))
register(Builder('packet', 'packet', ('packet',), legacy(render_packet)))
register(Builder('requirementDiagram', 'requirement-links', ('requirementDiagram',), legacy(render_requirement_links)))

# === end group 4 ===


# === group 5: Mermaid 12 and beta: agentflow, usecase, swimlanes, wardley, cynefin, eventmodeling ====

_AGENT_SHAPES = {"task", "tool", "input", "decision", "refdoc", "action"}


_AGENT_ARROWS = {"sequence": "-->", "reference": "-.-", "failure": "--x"}


def render_graph_agentflow(ir: dict) -> str:
    _require(ir, ("nodes", "edges"), "graph/agentflow-beta")
    direction = _direction(ir, "graph/agentflow-beta", allowed=_FLOWCHART_DIRECTIONS, default="TD")
    lines = [f"agentflow-beta {direction}"]
    known: set[str] = set()
    by_group: dict[str | None, list[dict]] = {}
    for node in ir["nodes"]:
        _require(node, ("id", "label"), "graph/agentflow-beta node")
        by_group.setdefault(node.get("group"), []).append(node)
    children: dict[str | None, list[dict]] = {}
    for group in ir.get("groups", []):
        _require(group, ("id", "label"), "graph/agentflow-beta group")
        children.setdefault(group.get("group"), []).append(group)

    def emit_node(node: dict, indent: str) -> None:
        node_id = _identifier(node["id"], "graph/agentflow-beta node")
        kind = node.get("kind")
        shape = ""
        if kind is not None:
            if kind not in _AGENT_SHAPES:
                raise IRError(f"graph/agentflow-beta node {node['id']!r} has unknown kind {kind!r}")
            shape = f"@{{ shape: {kind} }}"
        lines.append(f'{indent}{node_id}[{_quote(node["label"])}]{shape}')
        known.add(node["id"])

    def emit_flow(group: dict, indent: str) -> None:
        group_id = _identifier(group["id"], "graph/agentflow-beta group")
        lines.append(f'{indent}flow {group_id}[{_quote(group["label"])}]')
        known.add(group["id"])
        for node in by_group.pop(group["id"], []):
            emit_node(node, indent + "    ")
        for child in children.pop(group["id"], []):
            emit_flow(child, indent + "    ")
        lines.append(f"{indent}end")

    for group in children.pop(None, []):
        emit_flow(group, "    ")
    leftover_groups = [group for group in children if group is not None]
    if leftover_groups:
        raise IRError(f"graph/agentflow-beta groups reference undeclared parent group(s): {leftover_groups}")
    for node in by_group.pop(None, []):
        emit_node(node, "    ")
    leftover = [group for group in by_group if group is not None]
    if leftover:
        raise IRError(f"graph/agentflow-beta nodes reference undeclared group(s): {leftover}")
    for edge in ir["edges"]:
        _require(edge, ("from", "to"), "graph/agentflow-beta edge")
        if edge["from"] not in known or edge["to"] not in known:
            raise IRError(f"graph/agentflow-beta edge references undeclared node: {edge}")
        arrow = _AGENT_ARROWS.get(edge.get("kind", "sequence"))
        if arrow is None:
            raise IRError(f"graph/agentflow-beta edge has unknown kind {edge.get('kind')!r}")
        label = f'|{_quote(edge["label"])}|' if edge.get("label") else ""
        lines.append(f'    {edge["from"]} {arrow}{label} {edge["to"]}')
    return "\n".join(lines) + "\n"


def _usecase_id(raw: str, where: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", raw):
        raise IRError(f"{where} id {raw!r} must be letters, digits, or underscore")
    return raw


def render_usecase(ir: dict) -> str:
    _require(ir, ("actors", "usecases", "edges"), "usecase/usecase-beta")
    lines = ["usecase-beta"]
    direction = _direction(ir, "usecase/usecase-beta", allowed=_CARDINAL_DIRECTIONS)
    if direction:
        lines.append(f"    direction {direction}")
    actors_by_group: dict[str | None, list[dict]] = {}
    cases_by_group: dict[str | None, list[dict]] = {}
    for actor in ir["actors"]:
        _require(actor, ("id",), "usecase/usecase-beta actor")
        actors_by_group.setdefault(actor.get("group"), []).append(actor)
    for usecase in ir["usecases"]:
        _require(usecase, ("id", "label"), "usecase/usecase-beta usecase")
        cases_by_group.setdefault(usecase.get("group"), []).append(usecase)
    actor_ids: set[str] = set()
    case_ids: set[str] = set()

    def emit_actor(actor: dict, indent: str) -> None:
        actor_id = _usecase_id(actor["id"], "usecase/usecase-beta actor")
        label = f"({_quote(actor['label'])})" if actor.get("label") else ""
        lines.append(f"{indent}actor {actor_id}{label}")
        actor_ids.add(actor_id)

    def emit_case(usecase: dict, indent: str) -> None:
        case_id = _usecase_id(usecase["id"], "usecase/usecase-beta usecase")
        lines.append(f"{indent}{case_id}({_quote(usecase['label'])})")
        case_ids.add(case_id)

    for group in ir.get("groups", []):
        _require(group, ("id", "label"), "usecase/usecase-beta group")
        group_id = _usecase_id(group["id"], "usecase/usecase-beta group")
        lines.append(f"    systemBoundary {group_id}({_quote(group['label'])})")
        for actor in actors_by_group.pop(group["id"], []):
            emit_actor(actor, "        ")
        for usecase in cases_by_group.pop(group["id"], []):
            emit_case(usecase, "        ")
        lines.append("    end")
    for actor in actors_by_group.pop(None, []):
        emit_actor(actor, "    ")
    for usecase in cases_by_group.pop(None, []):
        emit_case(usecase, "    ")
    leftover = [group for group in {**actors_by_group, **cases_by_group} if group is not None]
    if leftover:
        raise IRError(f"usecase/usecase-beta members reference undeclared group(s): {leftover}")
    known = actor_ids | case_ids
    for edge in ir["edges"]:
        _require(edge, ("from", "to"), "usecase/usecase-beta edge")
        if edge["from"] not in known or edge["to"] not in known:
            raise IRError(f"usecase/usecase-beta edge references an undeclared actor or use case: {edge}")
        kind = edge.get("kind", "association")
        if kind == "association":
            if edge.get("label"):
                lines.append(f'    {edge["from"]} -- {_quote(edge["label"])} --> {edge["to"]}')
            else:
                lines.append(f'    {edge["from"]} --> {edge["to"]}')
        elif kind in ("include", "extend"):
            if edge["from"] not in case_ids or edge["to"] not in case_ids:
                raise IRError(f"usecase/usecase-beta {kind} endpoints must both be use cases")
            lines.append(f'    {edge["from"]} ..> : {kind} {edge["to"]}')
        elif kind == "generalization":
            same = (edge["from"] in actor_ids and edge["to"] in actor_ids) or (
                edge["from"] in case_ids and edge["to"] in case_ids
            )
            if not same:
                raise IRError("usecase/usecase-beta generalization must connect two actors or two use cases")
            lines.append(f'    {edge["from"]} --|> {edge["to"]}')
        else:
            raise IRError(f"usecase/usecase-beta edge has unknown kind {kind!r}")
    return "\n".join(lines) + "\n"


_SWIMLANE_SHAPES = {
    "terminator": "stadium",
    "process": "rect",
    "decision": "diamond",
    "io": "lean-r",
    "subprocess": "subproc",
    "document": "doc",
    "store": "cyl",
    "connector": "circle",
}

_SWIMLANE_EDGES = {
    "normal": "-->",
    "dependency": "-->",
    "conditional": "-.->",
    "weak": "-.->",
    "strong": "==>",
}

_SWIMLANE_STATUS_STYLES = {
    "done": "fill:#9f9,stroke:#393,color:#000",
    "ready": "fill:#9cf,stroke:#369,color:#000",
    "blocked": "fill:#f99,stroke:#933,color:#000",
    "pending": "fill:#eee,stroke:#999,color:#000",
}


def _swimlane_flowchart_body(ir: dict) -> str:
    _require(ir, ("nodes", "edges"), "graph/flowchart")
    ids: dict[str, str] = {}
    lines = [f"flowchart {_direction(ir, 'graph/flowchart', allowed=_FLOWCHART_DIRECTIONS, default='TD')}"]
    by_group: dict[str | None, list[dict]] = {}
    for node in ir["nodes"]:
        _require(node, ("id", "label"), "graph/flowchart node")
        by_group.setdefault(node.get("group"), []).append(node)

    used_statuses: list[str] = []
    class_lines: list[str] = []

    def emit_node(node: dict, indent: str) -> None:
        node_id = _safe_id(node["id"], ids)
        shape = _SWIMLANE_SHAPES.get(node.get("kind", "process"))
        if shape is None:
            raise IRError(f"graph/flowchart node {node['id']!r} has unknown kind {node['kind']!r}")
        lines.append(f'{indent}{node_id}@{{ shape: {shape}, label: {_quote(node["label"])} }}')
        status = node.get("status")
        if status is not None:
            if status not in _SWIMLANE_STATUS_STYLES:
                raise IRError(f"graph/flowchart node {node['id']!r} has unknown status {status!r}")
            if status not in used_statuses:
                used_statuses.append(status)
            class_lines.append(f"  class {node_id} {status}")

    for group in ir.get("groups", []):
        _require(group, ("id", "label"), "graph/flowchart group")
        group_id = _safe_id(group["id"], ids)
        lines.append(f'  subgraph {group_id}[{_quote(group["label"])}]')
        for node in by_group.pop(group["id"], []):
            emit_node(node, "    ")
        lines.append("  end")
    for node in by_group.pop(None, []):
        emit_node(node, "  ")
    leftover = [group for group in by_group if group is not None]
    if leftover:
        raise IRError(f"graph/flowchart nodes reference undeclared group(s): {leftover}")

    for edge in ir["edges"]:
        _require(edge, ("from", "to"), "graph/flowchart edge")
        arrow = _SWIMLANE_EDGES.get(edge.get("kind", "normal"))
        if arrow is None:
            raise IRError(f"graph/flowchart edge has unknown kind {edge['kind']!r}")
        if edge["from"] not in ids or edge["to"] not in ids:
            raise IRError(f"graph/flowchart edge references undeclared node: {edge}")
        label = f'|{_quote(edge["label"])}|' if edge.get("label") else ""
        lines.append(f'  {ids[edge["from"]]} {arrow}{label} {ids[edge["to"]]}')

    if used_statuses:
        style_lines = [f"  classDef {status} {_SWIMLANE_STATUS_STYLES[status]}" for status in used_statuses]
        lines[1:1] = style_lines  # after the `flowchart <direction>` line, before any node/subgraph
        lines.extend(class_lines)
    return "\n".join(lines) + "\n"


def render_graph_swimlane(ir: dict) -> str:
    direction = _direction(ir, "graph/swimlane-beta", allowed=_FLOWCHART_DIRECTIONS, default="TD")
    cloned = dict(ir)
    cloned["direction"] = direction
    body = _swimlane_flowchart_body(cloned)
    return f"swimlane-beta {direction}\n" + body.split("\n", 1)[1]


def render_graph_wardley(ir: dict) -> str:
    _require(ir, ("nodes", "edges"), "graph/wardley-beta")
    lines = ["wardley-beta"]
    if ir.get("title"):
        lines.append(f"    title {_no_colon(ir['title'], 'graph/wardley-beta title')}")
    names: dict[str, str] = {}
    for node in ir["nodes"]:
        _require(node, ("id", "kind", "visibility", "evolution"), "graph/wardley-beta node")
        if node["kind"] not in ("anchor", "component"):
            raise IRError(f"graph/wardley-beta node {node['id']!r} has unknown kind {node['kind']!r}")
        visibility = float(_positive_number(node["visibility"], "wardley visibility"))
        evolution = float(_positive_number(node["evolution"], "wardley evolution"))
        if not 0 <= visibility <= 1 or not 0 <= evolution <= 1:
            raise IRError(f"graph/wardley-beta node {node['id']!r} coordinates must be between 0 and 1")
        label = _quote(node["id"]) if not re.fullmatch(r"[A-Za-z0-9_]+", str(node["id"])) else str(node["id"])
        names[node["id"]] = label
        lines.append(f"    {node['kind']} {label} [{visibility}, {evolution}]")
    for edge in ir["edges"]:
        _require(edge, ("from", "to"), "graph/wardley-beta edge")
        if edge["from"] not in names or edge["to"] not in names:
            raise IRError(f"graph/wardley-beta edge references undeclared node: {edge}")
        lines.append(f"    {names[edge['from']]} -> {names[edge['to']]}")
    return "\n".join(lines) + "\n"


_CYNEFIN_DOMAINS = ("clear", "complicated", "complex", "chaotic", "confusion")


def render_cynefin(ir: dict) -> str:
    _require(ir, ("domains",), "cynefin/cynefin-beta")
    lines = ["cynefin-beta"]
    if ir.get("title"):
        lines.append(f"    title {_no_colon(ir['title'], 'cynefin/cynefin-beta title')}")
    domains = ir["domains"]
    for name in domains:
        if name not in _CYNEFIN_DOMAINS:
            raise IRError(f"cynefin/cynefin-beta has unknown domain {name!r}")
    for name in _CYNEFIN_DOMAINS:
        items = domains.get(name)
        if not items:
            continue
        lines.append(f"    {name}")
        for item in items:
            lines.append(f"        {_quote(_no_colon(item, 'cynefin item'))}")
    for transition in ir.get("transitions", []):
        _require(transition, ("from", "to"), "cynefin/cynefin-beta transition")
        if transition["from"] not in _CYNEFIN_DOMAINS or transition["to"] not in _CYNEFIN_DOMAINS:
            raise IRError(f"cynefin/cynefin-beta transition has an unknown domain: {transition}")
        if transition["from"] == transition["to"]:
            raise IRError("cynefin/cynefin-beta ignores self-loops; from and to must differ")
        label = f' : {_quote(transition["label"])}' if transition.get("label") else ""
        lines.append(f"    {transition['from']} --> {transition['to']}{label}")
    return "\n".join(lines) + "\n"


_EVENT_KINDS = {"ui", "cmd", "evt", "rmo", "pcr"}


def render_eventmodeling(ir: dict) -> str:
    _require(ir, ("frames",), "eventmodeling/eventmodeling")
    if not ir["frames"]:
        raise IRError("eventmodeling/eventmodeling requires frames")
    lines = ["eventmodeling"]
    seen: set[str] = set()
    for frame in ir["frames"]:
        _require(frame, ("n", "kind", "name"), "eventmodeling frame")
        number = frame["n"]
        if isinstance(number, bool) or not isinstance(number, int) or number < 0:
            raise IRError(f"eventmodeling frame number must be a non-negative integer, got {number!r}")
        key = f"{number:02d}"
        if key in seen:
            raise IRError(f"eventmodeling duplicate frame number {key}")
        seen.add(key)
        if frame["kind"] not in _EVENT_KINDS:
            raise IRError(f"eventmodeling frame {key} has unknown kind {frame['kind']!r}")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]*", str(frame["name"])):
            raise IRError(f"eventmodeling frame {key} name {frame['name']!r} must be an identifier")
        lines.append(f"    tf {key} {frame['kind']} {frame['name']}")
    return "\n".join(lines) + "\n"


register(Builder('agentflow', 'graph', ('agentflow-beta',), legacy(render_graph_agentflow)))
register(Builder('usecase', 'usecase', ('usecase-beta',), legacy(render_usecase)))
register(Builder('swimlanes', 'graph', ('swimlane-beta',), legacy(render_graph_swimlane)))
register(Builder('wardley', 'graph', ('wardley-beta',), legacy(render_graph_wardley)))
register(Builder('cynefin', 'cynefin', ('cynefin-beta',), legacy(render_cynefin)))
register(Builder('eventmodeling', 'eventmodeling', ('eventmodeling',), legacy(render_eventmodeling)))

# === end group 5 ===


# === group 6: remaining: ishikawa, treeView, railroad, zenuml, info ===================

def _emit_ishikawa(node: dict, lines: list[str], depth: int) -> None:
    _require(node, ("label",), "tree/ishikawa cause")
    lines.append(f"{'    ' * depth}{_no_colon(node['label'], 'tree/ishikawa label')}")
    for child in node.get("children", []):
        _emit_ishikawa(child, lines, depth + 1)


def render_ishikawa(ir: dict) -> str:
    _require(ir, ("effect", "causes"), "tree/ishikawa-beta")
    lines = ["ishikawa-beta", f"    {_no_colon(ir['effect'], 'tree/ishikawa effect')}"]
    for cause in ir["causes"]:
        _emit_ishikawa(cause, lines, 1)
    return "\n".join(lines) + "\n"


def _tree_token(name: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./-]+", name):
        return name
    return _quote(name)


def _emit_treeview(node: dict, lines: list[str], depth: int) -> None:
    _require(node, ("name",), "tree/treeView node")
    children = node.get("children", [])
    name = str(node["name"])
    if children and not name.endswith("/"):
        name += "/"
    lines.append(f"{'    ' * (depth + 1)}{_tree_token(name)}")
    for child in children:
        _emit_treeview(child, lines, depth + 1)


def render_treeview(ir: dict) -> str:
    _require(ir, ("nodes",), "tree/treeView-beta")
    if not ir["nodes"]:
        raise IRError("tree/treeView-beta requires nodes")
    lines = ["treeView-beta"]
    for node in ir["nodes"]:
        _emit_treeview(node, lines, 0)
    return "\n".join(lines) + "\n"


def render_railroad(ir: dict) -> str:
    _require(ir, ("rules",), "grammar/railroad-ebnf-beta")
    if not ir["rules"]:
        raise IRError("grammar/railroad-ebnf-beta requires rules")
    lines = ["railroad-ebnf-beta"]
    if ir.get("title"):
        lines.append(f"    title {_quote(ir['title'])}")
    for rule in ir["rules"]:
        text = str(rule).strip()
        if "\n" in text or "=" not in text or not text.endswith(";"):
            raise IRError(f"grammar/railroad-ebnf-beta rule must be one line containing '=' and ending with ';': {rule!r}")
        lines.append(f"    {text}")
    return "\n".join(lines) + "\n"


def _zenuml_text(value: Any) -> str:
    return str(value).replace("\r\n", "<br/>").replace("\n", "<br/>")


def render_sequence_zenuml(ir: dict) -> str:
    _require(ir, ("actors", "steps"), "sequence/zenuml")
    lines = ["zenuml"]
    if ir.get("title"):
        lines.append(f"    title {_no_colon(ir['title'], 'sequence/zenuml title')}")
    known: set[str] = set()
    for actor in ir["actors"]:
        _require(actor, ("id",), "sequence/zenuml actor")
        if actor.get("label") not in (None, actor["id"]):
            raise IRError("sequence/zenuml has no alias; the id is the displayed name")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", actor["id"]):
            raise IRError(f"sequence/zenuml actor id {actor['id']!r} must be a bare identifier")
        prefix = "@Actor " if actor.get("kind") == "actor" else ""
        if actor.get("kind") not in (None, "actor", "participant"):
            raise IRError(f"sequence/zenuml actor {actor['id']!r} has unknown kind {actor['kind']!r}")
        lines.append(f"    {prefix}{actor['id']}")
        known.add(actor["id"])
    for step in ir["steps"]:
        if step.get("type", "message") != "message":
            raise IRError("sequence/zenuml only emits messages; hand-author if/while/try blocks")
        _require(step, ("from", "to", "label"), "sequence/zenuml message")
        if step["from"] not in known or step["to"] not in known:
            raise IRError(f"sequence/zenuml message references an undeclared participant: {step}")
        lines.append(f'    {step["from"]}->{step["to"]}: {_zenuml_text(step["label"])}')
    return "\n".join(lines) + "\n"


def render_info(_ir: dict) -> str:
    return "info\n"


register(Builder('ishikawa', 'tree', ('ishikawa-beta',), legacy(render_ishikawa)))
register(Builder('treeView', 'tree', ('treeView-beta',), legacy(render_treeview)))
register(Builder('railroad', 'grammar', ('railroad-ebnf-beta',), legacy(render_railroad)))
register(Builder('zenuml', 'sequence', ('zenuml',), legacy(render_sequence_zenuml)))
register(Builder('info', 'info', ('info',), legacy(render_info)))

# === end group 6 ===


# === dispatch ================================================================================

SERIALIZERS: dict[tuple[str, str], Callable[[dict], str]] = {
    (builder.family, keyword): (lambda ir, _b=builder, _k=keyword: _b.serialize(ir, _k))
    for keyword, builder in BUILDERS.items()
}


def render(ir: dict, target: str | None = None, backend: str = "mermaid") -> str:
    resolved = target or (ir.get("target") if isinstance(ir, dict) else None) or ""
    if backend != "mermaid":
        raise IRError(resolved, "", f"unsupported backend {backend!r}; only 'mermaid' is implemented")
    if not isinstance(ir, dict):
        raise IRError(resolved, "", "the IR document must be a JSON object")
    if not resolved:
        raise IRError("", "/target", "no 'target' in the IR and none passed with --target")
    if resolved in HAND_AUTHOR_ONLY:
        raise IRError(resolved, "/target", f"hand-author-only; see {HAND_AUTHOR_ONLY[resolved]}")
    builder = BUILDERS.get(resolved)
    if builder is None:
        known = ", ".join(sorted(BUILDERS))
        raise IRError(resolved, "/target", f"no builder for this target; known targets: {known}")
    if "diagram" not in ir:
        raise IRError(resolved, "/diagram", "required key is missing")
    if ir["diagram"] != builder.family:
        raise IRError(resolved, "/diagram", f"must be {builder.family!r} for target {resolved!r}")
    try:
        return builder.serialize(ir, resolved)
    except IRError as err:
        if not err.target:
            err.target = resolved
            err.args = (str(err),)
        raise


EXIT_OK = 0
EXIT_IR_ERROR = 1  # the IR cannot be represented: fix the reported JSON path
EXIT_BAD_INPUT = 2  # missing or unreadable file, or not valid JSON


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Exit 0 on success, 1 on IRError, 2 on a bad input file.

    The output file is written only after the whole document rendered, so a failed run
    never leaves a partial or stale `-o` file behind.
    """
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ir_file", type=Path, help="Path to the diagram IR JSON file.")
    parser.add_argument("--target", default=None, help="Override the IR's 'target' field.")
    parser.add_argument("--backend", default="mermaid", choices=("mermaid",))
    parser.add_argument("-o", "--output", type=Path, default=None, help="Write source here instead of stdout.")
    args = parser.parse_args(argv)

    try:
        text = args.ir_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"ERROR: file not found: {args.ir_file}", file=sys.stderr)
        return EXIT_BAD_INPUT
    except (OSError, UnicodeDecodeError) as exc:
        print(f"ERROR: cannot read {args.ir_file}: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT
    try:
        ir = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"ERROR: {args.ir_file} is not valid JSON: {exc}", file=sys.stderr)
        return EXIT_BAD_INPUT

    try:
        source = render(ir, target=args.target, backend=args.backend)
    except IRError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_IR_ERROR

    if args.output:
        args.output.write_text(source, encoding="utf-8")
    else:
        print(source, end="")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
