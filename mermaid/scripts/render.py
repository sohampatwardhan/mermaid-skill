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
#
# Every text context below was checked against the 12.0.0 SVG: each encoded character
# renders back as the original character. These types decode Mermaid entity codes before
# lexing, so `#` (comment start in timeline and journey), `;`, `:` (field separators), `%`
# (comment start), quotes and `<`/`>` (HTML) are always encoded, never emitted raw.


def _g2_encode(chars: str, **extra: str) -> dict[str, str]:
    table = {char: ENTITY[char] for char in chars}
    table.update(extra)
    return table


_G2_BASE = '#;:%"<>&'
_G2_ALL = "".join(ENTITY)


def _g2_keyword_start(*words: str) -> tuple[tuple[str, str], ...]:
    """Reject text whose first word the type's lexer reads as a statement keyword."""
    return ((rf"(?i)^({'|'.join(words)})", "starts with a statement keyword the lexer would read instead of the text"),)


def _g2_config(v: Validator, ir: dict, schema: dict) -> dict | None:
    if "config" not in ir:
        return None
    return validate_config(v, ir["config"], "/config", schema)


def _g2_min_one(v: Validator, value: Any, path: str) -> list:
    return v.array(value, path, min_items=1)


_G2_LAYOUT_CONFIG = {
    "useMaxWidth": ("boolean",),
    "diagramMarginX": ("number", 0, 10000),
    "diagramMarginY": ("number", 0, 10000),
    "leftMargin": ("number", 0, 10000),
    "width": ("number", 1, 10000),
    "height": ("number", 1, 10000),
    "boxMargin": ("number", 0, 10000),
    "boxTextMargin": ("number", 0, 10000),
    "taskFontSize": ("number", 1, 200),
    "taskMargin": ("number", 0, 10000),
}

# --- gantt -----------------------------------------------------------------------------------

text_context("gantt.text", encode=_g2_encode(_G2_BASE))
text_context(
    "gantt.task",
    encode=_g2_encode(_G2_BASE),
    reject_patterns=_g2_keyword_start(
        r"gantt\b", r"dateformat\s", r"inclusiveenddates\b", r"topaxis\b", r"axisformat\s",
        r"tickinterval\s", r"includes\s", r"excludes\s", r"todaymarker\s", r"weekday\s", r"weekend\s",
        r"title\s", r"accdescription\s", r"section\s", r"click\s", r"acctitle\s*:", r"accdescr\s*[:{]",
        r"\d{4}-\d\d-\d\d\b",
    ),
)
text_context(
    "gantt.date",
    reject_patterns=(
        (r"[^0-9A-Za-z:./+ -]", "a date may contain only letters, digits, space and : . / + -"),
        (r"^[^0-9A-Za-z]", "a date must start with a letter or digit"),
        (r"(?i)^(after|until)\b", "use 'after' or 'until' instead of writing the keyword"),
        (r"^\d+(\.\d+)?(ms|s|m|h|d|w|M|y)$", "looks like a length; use 'duration'"),
    ),
)
text_context("gantt.format", reject_patterns=((r"[#;]", "'#' and ';' end the statement"),))
text_context("gantt.url", reject_patterns=((r"[\s\"]", "a URL must not contain whitespace or '\"'"),))
text_context("gantt.arg", reject_patterns=((r"[^A-Za-z0-9_ .\-]", "a callback argument may contain only letters, digits, space, _ . -"),))

_GANTT_TAGS = ("active", "done", "crit", "milestone", "vert")
_GANTT_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_GANTT_DURATION = re.compile(r"\d+(\.\d+)?(ms|s|m|h|d|w|M|y)")
_GANTT_TICK = re.compile(r"[1-9][0-9]*(millisecond|second|minute|hour|day|week|month)")
_GANTT_EXCLUDE = re.compile(rf"weekends|{'|'.join(_GANTT_DAYS)}|\d{{4}}-\d\d-\d\d")
_GANTT_CSS_LENGTH = re.compile(r"\d+(\.\d+)?px")
_GANTT_TASK_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_GANTT_CONFIG = {
    "gantt": {
        "useMaxWidth": ("boolean",),
        "titleTopMargin": ("number", 0, 10000),
        "barHeight": ("number", 1, 10000),
        "barGap": ("number", 0, 10000),
        "topPadding": ("number", 0, 10000),
        "leftPadding": ("number", 0, 10000),
        "rightPadding": ("number", 0, 10000),
        "gridLineStartPadding": ("number", 0, 10000),
        "fontSize": ("number", 1, 200),
        "sectionFontSize": ("number", 1, 200),
        "numberSectionStyles": ("integer", 1, 100),
        "topAxis": ("boolean",),
        "displayMode": ("enum", ("", "compact")),
        "weekday": ("enum", _GANTT_DAYS),
    },
}


def _gantt_tags(v: Validator, bar: dict, path: str) -> list[str]:
    if "tags" not in bar:
        return []
    tags_path = ptr(path, "tags")
    tags = v.array(bar["tags"], tags_path)
    seen: set[str] = set()
    for i, tag in enumerate(tags):
        v.enum(tag, ptr(tags_path, i), _GANTT_TAGS)
        v.unique(tag, ptr(tags_path, i), seen, "tag")
    if {"active", "done"} <= seen:
        raise v.error(tags_path, "a task cannot be both active and done")
    if "milestone" in seen and seen & {"active", "done"}:
        raise v.error(tags_path, "milestone cannot be combined with active or done")
    return list(tags)


def _gantt_serialize(ir: dict, keyword: str) -> str:
    v = Validator(keyword)
    v.fields(ir, "", optional=(
        "config", "title", "accessibility", "comment", "dateFormat", "axisFormat", "tickInterval",
        "weekday", "excludes", "weekend", "todayMarker", "bars", "sections",
    ))
    config = _g2_config(v, ir, _GANTT_CONFIG)
    head: list[str] = emit_accessibility(v, ir)
    if "title" in ir:
        head.append(f"    title {v.text(ir['title'], '/title', 'gantt.text')}")
    for key in ("dateFormat", "axisFormat"):
        if key in ir:
            head.append(f"    {key} {v.text(ir[key], ptr('', key), 'gantt.format')}")
    if "tickInterval" in ir:
        head.append(f"    tickInterval {v.ident(ir['tickInterval'], '/tickInterval', _GANTT_TICK)}")
    if "weekday" in ir:
        head.append(f"    weekday {v.enum(ir['weekday'], '/weekday', _GANTT_DAYS)}")
    if "excludes" in ir:
        for i, item in enumerate(_g2_min_one(v, ir["excludes"], "/excludes")):
            head.append(f"    excludes {v.ident(item, ptr('/excludes', i), _GANTT_EXCLUDE)}")
    if "weekend" in ir:
        head.append(f"    weekend {v.enum(ir['weekend'], '/weekend', ('friday', 'saturday'))}")
    if "todayMarker" in ir:
        head.append(f"    todayMarker {_gantt_today_marker(v, ir['todayMarker'])}")
    head += emit_comment(v, ir)

    # Collect every task first so `until` can name a later task and cycles can be checked.
    groups: list[tuple[str | None, str, list]] = []
    if "bars" in ir:
        groups.append((None, "/bars", _g2_min_one(v, ir["bars"], "/bars")))
    if "sections" in ir:
        for s, section in enumerate(_g2_min_one(v, ir["sections"], "/sections")):
            spath = ptr("/sections", s)
            v.fields(section, spath, ("name", "bars"))
            name = v.text(section["name"], ptr(spath, "name"), "gantt.text")
            groups.append((name, ptr(spath, "bars"), _g2_min_one(v, section["bars"], ptr(spath, "bars"))))
    if not groups:
        raise v.error("/sections", "a gantt chart needs 'bars' or 'sections' with at least one task")

    tasks: list[tuple[str, dict]] = []
    for _name, bars_path, bars in groups:
        for i, bar in enumerate(bars):
            path = ptr(bars_path, i)
            v.fields(bar, path, ("label",), ("id", "tags", "start", "after", "end", "duration", "until", "href", "call"))
            tasks.append((path, bar))
    ids: dict[str, int] = {}
    seen_ids: set[str] = set()
    for index, (path, bar) in enumerate(tasks):
        if "id" in bar:
            ids[v.unique(v.ident(bar["id"], ptr(path, "id"), _GANTT_TASK_ID), ptr(path, "id"), seen_ids)] = index

    deps: list[list[tuple[int, str]]] = []
    rendered: list[str] = []
    clicks: list[str] = []
    for index, (path, bar) in enumerate(tasks):
        label = v.text(bar["label"], ptr(path, "label"), "gantt.task")
        meta = _gantt_tags(v, bar, path)
        edges: list[tuple[int, str]] = []
        if "start" in bar and "after" in bar:
            raise v.error(ptr(path, "after"), "use either 'start' or 'after', not both")
        if "start" in bar:
            start = v.text(bar["start"], ptr(path, "start"), "gantt.date")
        elif "after" in bar:
            after_path = ptr(path, "after")
            refs = []
            for j, ref in enumerate(_g2_min_one(v, bar["after"], after_path)):
                ref_path = ptr(after_path, j)
                v.ref(ref, ref_path, ids)
                if ids[ref] >= index:
                    raise v.error(ref_path, f"'after' must name a task declared earlier, got {ref!r}")
                edges.append((ids[ref], ref_path))
                refs.append(ref)
            start = "after " + " ".join(refs)
        else:
            start = None
            if index == 0:
                raise v.error(path, "the first task needs 'start' (there is no preceding task to follow)")
            edges.append((index - 1, path))
        if "id" in bar:
            if start is None:
                raise v.error(ptr(path, "id"), "a task with an id needs 'start' or 'after' (Mermaid reads two items as start, end)")
            meta.append(bar["id"])
        if start is not None:
            meta.append(start)
        ends = [key for key in ("end", "duration", "until") if key in bar]
        if len(ends) != 1:
            where = ptr(path, ends[1]) if ends else ptr(path, "duration")
            raise v.error(where, "a task needs exactly one of 'end', 'duration' or 'until'")
        if "end" in bar:
            meta.append(v.text(bar["end"], ptr(path, "end"), "gantt.date"))
        elif "duration" in bar:
            meta.append(v.ident(bar["duration"], ptr(path, "duration"), _GANTT_DURATION))
        else:
            until_path = ptr(path, "until")
            target = v.ref(bar["until"], until_path, ids)
            if ids[target] == index:
                raise v.error(until_path, "a task cannot end at its own start")
            edges.append((ids[target], until_path))
            meta.append(f"until {target}")
        deps.append(edges)
        rendered.append(f"{label} :{', '.join(meta)}")
        if "href" in bar or "call" in bar:
            if "id" not in bar:
                key = "href" if "href" in bar else "call"
                raise v.error(ptr(path, key), "'click' needs the task to have an 'id'")
            if "href" in bar:
                url = v.text(bar["href"], ptr(path, "href"), "gantt.url")
                clicks.append(f'    click {bar["id"]} href "{url}"')
            if "call" in bar:
                clicks.append(f"    click {bar['id']} call {_gantt_call(v, bar['call'], ptr(path, 'call'))}")
    _gantt_no_cycle(v, deps)

    lines = ["gantt", *head]
    position = 0
    for name, _bars_path, bars in groups:
        indent = "    "
        if name is not None:
            lines.append(f"    section {name}")
            indent = "        "
        for _ in bars:
            lines.append(indent + rendered[position])
            position += 1
    lines += clicks
    return "\n".join(emit_frontmatter(None, config) + lines) + "\n"


def _gantt_today_marker(v: Validator, value: Any) -> str:
    path = "/todayMarker"
    if value == "off":
        return "off"
    if not isinstance(value, dict):
        raise v.error(path, 'must be "off" or a style object {stroke, strokeWidth, opacity}')
    v.fields(value, path, optional=("stroke", "strokeWidth", "opacity"))
    if not value:
        raise v.error(path, "a style object needs at least one property")
    parts = []
    if "strokeWidth" in value:
        parts.append(f"stroke-width:{v.ident(value['strokeWidth'], ptr(path, 'strokeWidth'), _GANTT_CSS_LENGTH)}")
    if "stroke" in value:
        parts.append(f"stroke:{v.text(value['stroke'], ptr(path, 'stroke'), 'common.color')}")
    if "opacity" in value:
        parts.append(f"opacity:{v.number(value['opacity'], ptr(path, 'opacity'), 0, 1)}")
    return ",".join(parts)


def _gantt_call(v: Validator, value: Any, path: str) -> str:
    v.fields(value, path, ("function",), ("args",))
    name = v.ident(value["function"], ptr(path, "function"))
    args = []
    if "args" in value:
        for i, arg in enumerate(v.array(value["args"], ptr(path, "args"))):
            args.append(f'"{v.text(arg, ptr(ptr(path, "args"), i), "gantt.arg")}"')
    return f"{name}({', '.join(args)})"


def _gantt_no_cycle(v: Validator, deps: list[list[tuple[int, str]]]) -> None:
    """Reject `until` chains that make a task's dates depend on themselves."""
    state = [0] * len(deps)  # 0 new, 1 on stack, 2 done
    for root in range(len(deps)):
        if state[root]:
            continue
        stack = [(root, iter(deps[root]))]
        state[root] = 1
        while stack:
            node, edges = stack[-1]
            step = next(edges, None)
            if step is None:
                state[node] = 2
                stack.pop()
                continue
            target, where = step
            if state[target] == 1:
                raise v.error(where, "this dependency makes the task's dates depend on themselves (cycle)")
            if state[target] == 0:
                state[target] = 1
                stack.append((target, iter(deps[target])))


register(Builder(
    "gantt", "timeline", ("gantt",), _gantt_serialize,
    text_fields=(
        "/title", "/comment", "/accessibility/title", "/accessibility/description",
        "/sections/*/name", "/sections/*/bars/*/label", "/bars/*/label",
    ),
    features={
        "gantt.title": "/title",
        "gantt.date-format": "/dateFormat",
        "gantt.date-format-unix": "/dateFormat=X",
        "gantt.axis-format": "/axisFormat",
        "gantt.tick-interval": "/tickInterval",
        "gantt.weekday": "/weekday",
        "gantt.excludes-weekends": "/excludes/*=weekends",
        "gantt.excludes-date": "/excludes/*=2026-08-12",
        "gantt.excludes-dayname": "/excludes/*=friday",
        "gantt.excludes-multiple-lines": "/excludes/2",
        "gantt.weekend-friday": "/weekend=friday",
        "gantt.weekend-saturday": "/weekend=saturday",
        "gantt.section": "/sections/*/name",
        "gantt.task": "/sections/*/bars/*/label",
        "gantt.task-no-section": "/bars/*/label",
        "gantt.tag-done": "/sections/*/bars/*/tags/*=done",
        "gantt.tag-active": "/sections/*/bars/*/tags/*=active",
        "gantt.tag-crit": "/sections/*/bars/*/tags/*=crit",
        "gantt.tag-combined": "/sections/*/bars/*/tags/1",
        "gantt.milestone": "/sections/*/bars/*/tags/*=milestone",
        "gantt.vert": "/sections/*/bars/*/tags/*=vert",
        "gantt.task-id": "/sections/*/bars/*/id",
        "gantt.start-date": "/sections/*/bars/*/start",
        "gantt.end-date": "/sections/*/bars/*/end",
        "gantt.end-only": "/sections/1/bars/7/end",
        "gantt.length-only": "/sections/1/bars/1/duration",
        "gantt.after": "/sections/*/bars/*/after/0",
        "gantt.after-multiple": "/sections/*/bars/*/after/1",
        "gantt.until": "/sections/*/bars/*/until",
        "gantt.duration-ms": "/sections/*/bars/*/duration=500ms",
        "gantt.duration-s": "/sections/*/bars/*/duration=30s",
        "gantt.duration-m": "/sections/*/bars/*/duration=90m",
        "gantt.duration-h": "/sections/*/bars/*/duration=36h",
        "gantt.duration-d": "/sections/*/bars/*/duration=3d",
        "gantt.duration-w": "/sections/*/bars/*/duration=1w",
        "gantt.duration-month": "/sections/*/bars/*/duration=1M",
        "gantt.duration-y": "/sections/*/bars/*/duration=1y",
        "gantt.duration-decimal": "/sections/*/bars/*/duration=1.5d",
        "gantt.today-marker-style": "/todayMarker/stroke",
        "gantt.today-marker-off": "/todayMarker=off",
        "gantt.click-href": "/sections/*/bars/*/href",
        "gantt.click-call": "/sections/*/bars/*/call/function",
        "gantt.comment": "/comment",
        "gantt.acc-title": "/accessibility/title",
        "gantt.acc-descr": "/accessibility/description=Build, test and ship tasks for the release",
        "gantt.acc-descr-block": "/accessibility/description=A short schedule\nwithout sections",
    },
    probes={
        "object": "/sections/1/bars/0",
        "number": "/todayMarker/opacity",
        "enum": "/weekend",
        "ref": "/sections/1/bars/0/after/0",
    },
))

# --- timeline --------------------------------------------------------------------------------

text_context("timeline.text", encode=_g2_encode(_G2_BASE))
text_context(
    "timeline.period",
    encode=_g2_encode(_G2_BASE),
    reject_patterns=_g2_keyword_start(r"timeline\b", r"title\s", r"section\s", r"acctitle\s*:", r"accdescr\s*[:{]"),
)
text_context("timeline.event", encode=_g2_encode(_G2_BASE, **{"\n": "<br>"}), allow_newline=True)

_TIMELINE_CONFIG = {
    "timeline": {"disableMulticolor": ("boolean",), **_G2_LAYOUT_CONFIG},
    "themeVariables": {
        **{f"cScale{i}": ("color",) for i in range(12)},
        **{f"cScaleLabel{i}": ("color",) for i in range(12)},
    },
}


def _timeline_events(v: Validator, events: Any, path: str, indent: str) -> list[str]:
    lines: list[str] = []
    for i, event in enumerate(_g2_min_one(v, events, path)):
        epath = ptr(path, i)
        v.fields(event, epath, ("period", "text"), ("layout",))
        period = v.text(event["period"], ptr(epath, "period"), "timeline.period")
        layout = v.enum(event["layout"], ptr(epath, "layout"), ("inline", "lines")) if "layout" in event else "inline"
        tpath = ptr(epath, "text")
        if isinstance(event["text"], str):  # one event, kept for older IR documents
            texts = [v.text(event["text"], tpath, "timeline.event")]
        else:
            texts = [v.text(t, ptr(tpath, j), "timeline.event") for j, t in enumerate(_g2_min_one(v, event["text"], tpath))]
        if layout == "inline":
            lines.append(f"{indent}{period} : " + " : ".join(texts))
        else:
            lines.append(f"{indent}{period} : {texts[0]}")
            lines.extend(f"{indent}    : {text}" for text in texts[1:])
    return lines


def _timeline_serialize(ir: dict, keyword: str) -> str:
    v = Validator(keyword)
    v.fields(ir, "", optional=("config", "direction", "title", "accessibility", "comment", "events", "sections"))
    config = _g2_config(v, ir, _TIMELINE_CONFIG)
    header = "timeline"
    if "direction" in ir:
        header += " " + v.enum(ir["direction"], "/direction", ("LR", "TD"))
    lines = [header, *emit_accessibility(v, ir)]
    if "title" in ir:
        lines.append(f"    title {v.text(ir['title'], '/title', 'timeline.text')}")
    lines += emit_comment(v, ir)
    if "events" in ir and "sections" in ir:
        # Periods before the first section are dropped by Mermaid 12.0.0 when sections follow.
        raise v.error("/events", "use either 'events' or 'sections', not both (Mermaid drops periods outside sections)")
    if "events" in ir:
        lines += _timeline_events(v, ir["events"], "/events", "    ")
    elif "sections" in ir:
        for s, section in enumerate(_g2_min_one(v, ir["sections"], "/sections")):
            spath = ptr("/sections", s)
            v.fields(section, spath, ("name", "events"))
            lines.append(f"    section {v.text(section['name'], ptr(spath, 'name'), 'timeline.text')}")
            lines += _timeline_events(v, section["events"], ptr(spath, "events"), "        ")
    else:
        raise v.error("/events", "a timeline needs 'events' or 'sections'")
    return "\n".join(emit_frontmatter(None, config) + lines) + "\n"


register(Builder(
    "timeline", "timeline", ("timeline",), _timeline_serialize,
    text_fields=(
        "/title", "/comment", "/accessibility/title", "/accessibility/description",
        "/sections/*/name", "/sections/*/events/*/period", "/sections/*/events/*/text/*",
        "/events/*/period", "/events/*/text/*",
    ),
    features={
        "timeline.title": "/title",
        "timeline.direction-lr": "/direction=LR",
        "timeline.direction-td": "/direction=TD",
        "timeline.period-event": "/sections/*/events/*/text/0",
        "timeline.multiple-events-inline": "/sections/*/events/*/text/1",
        "timeline.multiple-events-continuation": "/sections/*/events/*/layout=lines",
        "timeline.text-period": "/sections/*/events/*/period=Industry 1.0",
        "timeline.section": "/sections/*/name",
        "timeline.line-break": "/sections/*/events/*/text/*=Steam\npower",
        "timeline.comment": "/comment",
        "timeline.acc-title": "/accessibility/title",
        "timeline.acc-descr": "/accessibility/description=Four industrial ages grouped by century",
        "timeline.acc-descr-block": "/accessibility/description=Social platforms\nby launch year",
    },
    probes={
        "object": "/sections/0/events/0",
        "number": "/config/timeline/leftMargin",
        "enum": "/direction",
        "ref": None,
    },
))

# --- userJourney -----------------------------------------------------------------------------

text_context("journey.text", encode=_g2_encode(_G2_BASE))
text_context(
    "journey.task",
    encode=_g2_encode(_G2_BASE),
    reject_patterns=_g2_keyword_start(r"journey\b", r"title\s", r"section\s", r"acctitle\s*:", r"accdescr\s*[:{]"),
)
text_context("journey.actor", encode=_g2_encode(_G2_BASE + ","))

_JOURNEY_CONFIG = {"journey": {**_G2_LAYOUT_CONFIG, "maxLabelWidth": ("number", 1, 10000)}}


def _journey_serialize(ir: dict, keyword: str) -> str:
    v = Validator(keyword)
    v.fields(ir, "", ("sections",), ("config", "title", "accessibility", "comment"))
    config = _g2_config(v, ir, _JOURNEY_CONFIG)
    lines = ["journey", *emit_accessibility(v, ir)]
    if "title" in ir:
        lines.append(f"    title {v.text(ir['title'], '/title', 'journey.text')}")
    lines += emit_comment(v, ir)
    for s, section in enumerate(_g2_min_one(v, ir["sections"], "/sections")):
        spath = ptr("/sections", s)
        v.fields(section, spath, ("name", "tasks"))
        lines.append(f"    section {v.text(section['name'], ptr(spath, 'name'), 'journey.text')}")
        for t, task in enumerate(_g2_min_one(v, section["tasks"], ptr(spath, "tasks"))):
            tpath = ptr(ptr(spath, "tasks"), t)
            v.fields(task, tpath, ("name", "score", "actors"))
            name = v.text(task["name"], ptr(tpath, "name"), "journey.task")
            score = v.number(task["score"], ptr(tpath, "score"), 1, 5, integer=True)
            apath = ptr(tpath, "actors")
            actors = [v.text(a, ptr(apath, i), "journey.actor") for i, a in enumerate(_g2_min_one(v, task["actors"], apath))]
            lines.append(f"        {name}: {score}: {', '.join(actors)}")
    return "\n".join(emit_frontmatter(None, config) + lines) + "\n"


register(Builder(
    "userJourney", "journey", ("journey",), _journey_serialize,
    text_fields=(
        "/title", "/comment", "/accessibility/title", "/accessibility/description",
        "/sections/*/name", "/sections/*/tasks/*/name", "/sections/*/tasks/*/actors/*",
    ),
    features={
        "userJourney.title": "/title",
        "userJourney.section": "/sections/*/name",
        "userJourney.task": "/sections/*/tasks/*/name",
        "userJourney.task-multiple-actors": "/sections/*/tasks/*/actors/1",
        "userJourney.score-1": "/sections/*/tasks/*/score=1",
        "userJourney.score-3": "/sections/*/tasks/*/score=3",
        "userJourney.score-5": "/sections/*/tasks/*/score=5",
        "userJourney.comment": "/comment",
        "userJourney.acc-title": "/accessibility/title",
        "userJourney.acc-descr": "/accessibility/description=Steps from making tea to sitting down at home",
        "userJourney.acc-descr-block": "/accessibility/description=A short journey\nwith one section",
    },
    probes={"object": "/sections/0/tasks/0", "number": "/sections/0/tasks/0/score", "enum": None, "ref": None},
))

# --- gitgraph --------------------------------------------------------------------------------

text_context("gitgraph.quoted", encode=_g2_encode(_G2_BASE + "\\"))
text_context("gitgraph.title")  # YAML frontmatter, JSON-quoted; no entity decoding there
text_context(
    "gitgraph.main-branch",
    reject_patterns=((r"[^A-Za-z0-9_./-]", "the main branch name may contain only letters, digits and _ . / -"),),
)

_GIT_COMMIT_TYPES = ("NORMAL", "REVERSE", "HIGHLIGHT")
_GIT_CONFIG = {
    "gitGraph": {
        "showBranches": ("boolean",),
        "showCommitLabel": ("boolean",),
        "mainBranchName": ("string", "gitgraph.main-branch"),
        "mainBranchOrder": ("integer", 0, 1000),
        "parallelCommits": ("boolean",),
        "rotateCommitLabel": ("boolean",),
        "titleTopMargin": ("number", 0, 10000),
        "diagramPadding": ("number", 0, 10000),
        "useMaxWidth": ("boolean",),
    },
    "themeVariables": {
        **{f"git{i}": ("color",) for i in range(8)},
        **{f"gitBranchLabel{i}": ("color",) for i in range(8)},
        **{f"gitInv{i}": ("color",) for i in range(8)},
        "commitLabelColor": ("color",),
        "commitLabelBackground": ("color",),
        "tagLabelColor": ("color",),
        "tagLabelBackground": ("color",),
        "tagLabelBorder": ("color",),
    },
}
_GIT_OPS = {
    "commit": ((), ("id", "commitType", "tag")),
    "branch": (("name",), ("order",)),
    "checkout": (("name",), ()),
    "switch": (("name",), ()),
    "merge": (("name",), ("id", "tag", "commitType")),
    "cherry-pick": (("id",), ("parent",)),
}


@dataclass
class _GitCommit:
    branch: str
    parents: list[int]
    merge: bool = False


def _git_attrs(v: Validator, op: dict, path: str) -> list[str]:
    parts = []
    if "id" in op:
        parts.append(f'id: "{v.text(op["id"], ptr(path, "id"), "gitgraph.quoted")}"')
    if "tag" in op:
        parts.append(f'tag: "{v.text(op["tag"], ptr(path, "tag"), "gitgraph.quoted")}"')
    if "commitType" in op:
        parts.append(f"type: {v.enum(op['commitType'], ptr(path, 'commitType'), _GIT_COMMIT_TYPES)}")
    return parts


def _git_serialize(ir: dict, keyword: str) -> str:
    v = Validator(keyword)
    v.fields(ir, "", ("ops",), ("config", "title", "orientation", "colon", "accessibility", "comment"))
    config = _g2_config(v, ir, _GIT_CONFIG)
    title = v.text(ir["title"], "/title", "gitgraph.title") if "title" in ir else None
    header = "gitGraph"
    if "orientation" in ir:
        header += f" {v.enum(ir['orientation'], '/orientation', ('LR', 'TB', 'BT'))}:"
    if "colon" in ir and v.boolean(ir["colon"], "/colon"):
        if "orientation" in ir:
            raise v.error("/colon", "'colon' is the bare 'gitGraph:' form; with 'orientation' the colon is already emitted")
        header += ":"
    lines = [header, *emit_accessibility(v, ir)]
    lines += emit_comment(v, ir)

    main = (config or {}).get("gitGraph", {}).get("mainBranchName", "main")
    heads: dict[str, int | None] = {main: None}
    current = main
    commits: list[_GitCommit] = []
    by_id: dict[str, int] = {}

    def new_commit(op: dict, path: str, commit: _GitCommit) -> None:
        commits.append(commit)
        if "id" in op:
            v.unique(op["id"], ptr(path, "id"), set(by_id), "commit id")
            by_id[op["id"]] = len(commits) - 1
        heads[current] = len(commits) - 1

    def head_parents() -> list[int]:
        head = heads[current]
        return [] if head is None else [head]

    for i, op in enumerate(_g2_min_one(v, ir["ops"], "/ops")):
        path = ptr("/ops", i)
        if not isinstance(op, dict):
            raise v.error(path, f"must be an object, got {type(op).__name__}")
        kind = v.enum(op["type"], ptr(path, "type"), tuple(_GIT_OPS)) if "type" in op else None
        if kind is None:
            raise v.error(ptr(path, "type"), "required key is missing")
        required, optional = _GIT_OPS[kind]
        v.fields(op, path, ("type", *required), optional)
        if kind == "commit":
            parts = ["commit", *_git_attrs(v, op, path)]
            new_commit(op, path, _GitCommit(current, head_parents()))
            lines.append("    " + " ".join(parts))
        elif kind == "branch":
            npath = ptr(path, "name")
            name = v.text(op["name"], npath, "gitgraph.quoted")
            if op["name"] in heads:
                raise v.error(npath, f"branch {op['name']!r} already exists; use checkout")
            heads[op["name"]] = heads[current]
            current = op["name"]
            line = f'    branch "{name}"'
            if "order" in op:
                line += f" order: {v.number(op['order'], ptr(path, 'order'), 0, integer=True)}"
            lines.append(line)
        elif kind in ("checkout", "switch"):
            npath = ptr(path, "name")
            name = v.text(op["name"], npath, "gitgraph.quoted")
            current = v.ref(op["name"], npath, heads)
            lines.append(f'    {kind} "{name}"')
        elif kind == "merge":
            npath = ptr(path, "name")
            name = v.text(op["name"], npath, "gitgraph.quoted")
            other = v.ref(op["name"], npath, heads)
            if other == current:
                raise v.error(npath, "cannot merge a branch into itself")
            mine, theirs = heads[current], heads[other]
            if mine is None:
                raise v.error(path, f"the current branch {current!r} has no commits to merge into")
            if theirs is None:
                raise v.error(npath, f"branch {other!r} has no commits")
            if mine == theirs:
                raise v.error(npath, f"branch {other!r} has the same head as {current!r}; nothing to merge")
            if commits[mine].branch == other:
                raise v.error(npath, f"the head of {current!r} was committed on {other!r}; nothing to merge")
            parts = [f'merge "{name}"', *_git_attrs(v, op, path)]
            new_commit(op, path, _GitCommit(current, [mine, theirs], merge=True))
            lines.append("    " + " ".join(parts))
        else:  # cherry-pick
            ipath = ptr(path, "id")
            source_id = v.text(op["id"], ipath, "gitgraph.quoted")
            source = commits[by_id[v.ref(op["id"], ipath, by_id)]]
            line = f'    cherry-pick id: "{source_id}"'
            if "parent" in op:
                ppath = ptr(path, "parent")
                parent = v.text(op["parent"], ppath, "gitgraph.quoted")
                if by_id[v.ref(op["parent"], ppath, by_id)] not in source.parents:
                    raise v.error(ppath, f"{op['parent']!r} is not an immediate parent of {op['id']!r}")
                line += f' parent: "{parent}"'
            elif source.merge:
                raise v.error(ptr(path, "parent"), "required key is missing: the source is a merge commit")
            if source.branch == current:
                raise v.error(ipath, f"commit {op['id']!r} is already on the current branch {current!r}")
            if heads[current] is None:
                raise v.error(path, f"the current branch {current!r} has no commits")
            commits.append(_GitCommit(current, [heads[current], by_id[op["id"]]]))
            heads[current] = len(commits) - 1
            lines.append(line)
    return "\n".join(emit_frontmatter(title, config) + lines) + "\n"


register(Builder(
    "gitgraph", "git", ("gitGraph",), _git_serialize,
    text_fields=(
        "/title", "/comment", "/accessibility/title", "/accessibility/description",
        "/ops/*/tag", "/ops/11/id", "/ops/19/name",
    ),
    features={
        "gitgraph.commit": "/ops/*/type=commit",
        "gitgraph.commit-id": "/ops/0/id",
        "gitgraph.commit-type-normal": "/ops/*/commitType=NORMAL",
        "gitgraph.commit-type-reverse": "/ops/*/commitType=REVERSE",
        "gitgraph.commit-type-highlight": "/ops/*/commitType=HIGHLIGHT",
        "gitgraph.commit-tag": "/ops/*/tag",
        "gitgraph.commit-combined-attributes": "/ops/8/commitType",
        "gitgraph.branch": "/ops/*/type=branch",
        "gitgraph.branch-quoted-name": "/ops/*/name=cherry-pick",
        "gitgraph.branch-order": "/ops/*/order",
        "gitgraph.checkout": "/ops/*/type=checkout",
        "gitgraph.switch": "/ops/*/type=switch",
        "gitgraph.merge": "/ops/*/type=merge",
        "gitgraph.merge-attributes": "/ops/10/commitType",
        "gitgraph.cherry-pick": "/ops/*/type=cherry-pick",
        "gitgraph.cherry-pick-parent": "/ops/*/parent",
        "gitgraph.orientation-lr": "/orientation=LR",
        "gitgraph.orientation-tb": "/orientation=TB",
        "gitgraph.orientation-bt": "/orientation=BT",
        "gitgraph.keyword-colon": "/colon=true",
        "gitgraph.frontmatter-title": "/title",
        "gitgraph.comment": "/comment",
        "gitgraph.acc-title": "/accessibility/title",
        "gitgraph.acc-descr": "/accessibility/description=main, develop and release branches with a merge and a cherry-pick",
        "gitgraph.acc-descr-block": "/accessibility/description=Top to bottom\nwith one branch",
    },
    probes={"object": "/ops/0", "number": "/ops/1/order", "enum": "/ops/0/commitType", "ref": "/ops/4/name"},
))

# --- kanban ----------------------------------------------------------------------------------

text_context("kanban.quoted", encode=_g2_encode(_G2_BASE + "`\\"))
text_context(
    "kanban.bare",
    encode=_g2_encode(_G2_ALL, **{"@": "#64;"}),
    reject_patterns=_g2_keyword_start(r"kanban\b"),
)
text_context("kanban.url", reject_patterns=((r"^(?!https?://[^\s\"']+$)", "must be an http(s) URL without spaces or quotes"),))

_KANBAN_PRIORITIES = ("Very High", "High", "Low", "Very Low")
_KANBAN_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_KANBAN_CONFIG = {
    "kanban": {
        "ticketBaseUrl": ("string", "kanban.url"),
        "padding": ("number", 0, 1000),
        "sectionWidth": ("number", 1, 10000),
        "useMaxWidth": ("boolean",),
    },
}


def _kanban_serialize(ir: dict, keyword: str) -> str:
    v = Validator(keyword)
    v.fields(ir, "", ("columns",), ("config", "comment"))
    config = _g2_config(v, ir, _KANBAN_CONFIG)
    lines = ["kanban", *emit_comment(v, ir, indent="  ")]
    seen: set[str] = set()
    for c, column in enumerate(_g2_min_one(v, ir["columns"], "/columns")):
        cpath = ptr("/columns", c)
        v.fields(column, cpath, ("label",), ("id", "plain", "cards"))
        plain = v.boolean(column["plain"], ptr(cpath, "plain")) if "plain" in column else False
        if plain:
            if "id" in column:
                raise v.error(ptr(cpath, "plain"), "a plain-text column has no id; drop 'id' or 'plain'")
            lines.append(f"  {v.text(column['label'], ptr(cpath, 'label'), 'kanban.bare')}")
        else:
            label = v.text(column["label"], ptr(cpath, "label"), "kanban.quoted")
            prefix = ""
            if "id" in column:
                prefix = v.unique(v.ident(column["id"], ptr(cpath, "id"), _KANBAN_ID), ptr(cpath, "id"), seen)
            lines.append(f'  {prefix}["{label}"]')
        for k, card in enumerate(v.array(column.get("cards", []), ptr(cpath, "cards"))):
            kpath = ptr(ptr(cpath, "cards"), k)
            v.fields(card, kpath, ("label",), ("id", "assigned", "ticket", "priority"))
            label = v.text(card["label"], ptr(kpath, "label"), "kanban.quoted")
            prefix = ""
            if "id" in card:
                prefix = v.unique(v.ident(card["id"], ptr(kpath, "id"), _KANBAN_ID), ptr(kpath, "id"), seen)
            meta = []
            for key in ("assigned", "ticket"):
                if key in card:
                    meta.append(f'{key}: "{v.text(card[key], ptr(kpath, key), "kanban.quoted")}"')
            if "priority" in card:
                meta.append(f'priority: "{v.enum(card["priority"], ptr(kpath, "priority"), _KANBAN_PRIORITIES)}"')
            suffix = f"@{{ {', '.join(meta)} }}" if meta else ""
            lines.append(f'    {prefix}["{label}"]{suffix}')
    return "\n".join(emit_frontmatter(None, config) + lines) + "\n"


register(Builder(
    "kanban", "board", ("kanban",), _kanban_serialize,
    text_fields=(
        "/comment", "/columns/0/label", "/columns/1/label", "/columns/2/label",
        "/columns/*/cards/*/label", "/columns/*/cards/*/assigned", "/columns/*/cards/*/ticket",
    ),
    features={
        "kanban.column": "/columns/*/id",
        "kanban.column-bare-text": "/columns/*/plain=true",
        "kanban.column-title-only": "/columns/1/label",
        "kanban.task": "/columns/*/cards/*/id",
        "kanban.task-title-only": "/columns/0/cards/0/label",
        "kanban.metadata": "/columns/*/cards/*/assigned",
        "kanban.metadata-assigned": "/columns/*/cards/*/assigned",
        "kanban.metadata-ticket": "/columns/*/cards/*/ticket",
        "kanban.priority-very-high": "/columns/*/cards/*/priority=Very High",
        "kanban.priority-high": "/columns/*/cards/*/priority=High",
        "kanban.priority-low": "/columns/*/cards/*/priority=Low",
        "kanban.priority-very-low": "/columns/*/cards/*/priority=Very Low",
        "kanban.metadata-combined": "/columns/3/cards/0/priority",
        "kanban.comment": "/comment",
    },
    probes={
        "object": "/columns/3/cards/0",
        "number": "/config/kanban/padding",
        "enum": "/columns/3/cards/0/priority",
        "ref": None,
    },
))

# --- mindmap ---------------------------------------------------------------------------------

text_context("mindmap.quoted", encode=_g2_encode(_G2_BASE + "`", **{"\n": "<br/>"}), allow_newline=True)
text_context("mindmap.markdown", encode=_g2_encode(_G2_BASE + "`"), allow_newline=True)
text_context(
    "mindmap.bare",
    encode=_g2_encode(_G2_ALL, **{"\n": "<br/>"}),
    allow_newline=True,
    reject_patterns=_g2_keyword_start(r"mindmap\b"),
)
text_context("mindmap.icon", reject_patterns=((r"[^A-Za-z0-9_ :-]", "icon classes may contain only letters, digits, space and _ : -"),))

_MINDMAP_SHAPES = {
    "default": None,
    "square": ("[", "]"),
    "rounded": ("(", ")"),
    "circle": ("((", "))"),
    "bang": ("))", "(("),
    "cloud": (")", "("),
    "hexagon": ("{{", "}}"),
}
_MINDMAP_CLASS = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
_MINDMAP_CONFIG = {
    "mindmap": {
        "padding": ("number", 0, 1000),
        "maxNodeWidth": ("number", 1, 10000),
        "useMaxWidth": ("boolean",),
    },
}


def _mindmap_serialize(ir: dict, keyword: str) -> str:
    v = Validator(keyword)
    v.fields(ir, "", ("root", "nodes", "edges"), ("config", "comment"))
    config = _g2_config(v, ir, _MINDMAP_CONFIG)
    nodes: dict[str, tuple[int, dict]] = {}
    for i, node in enumerate(_g2_min_one(v, ir["nodes"], "/nodes")):
        path = ptr("/nodes", i)
        v.fields(node, path, ("id", "label"), ("kind", "icon", "classes", "markdown"))
        node_id = v.ident(node["id"], ptr(path, "id"))
        if node_id in nodes:
            raise v.error(ptr(path, "id"), f"duplicate id {json.dumps(node_id)}")
        nodes[node_id] = (i, node)
    root = v.ref(ir["root"], "/root", nodes)
    children: dict[str, list[str]] = {}
    parent_of: dict[str, str] = {}
    for e, edge in enumerate(v.array(ir["edges"], "/edges")):
        path = ptr("/edges", e)
        v.fields(edge, path, ("from", "to"))
        source = v.ref(edge["from"], ptr(path, "from"), nodes)
        target = v.ref(edge["to"], ptr(path, "to"), nodes)
        if target == root or target in parent_of:
            raise v.error(ptr(path, "to"), f"node {target!r} already has a parent; a mindmap is a tree with one root")
        parent_of[target] = source
        children.setdefault(source, []).append(target)

    body: list[str] = []
    visited: set[str] = set()
    stack = [(root, 1)]
    while stack:
        node_id, depth = stack.pop()
        visited.add(node_id)
        body.extend(_mindmap_node(v, node_id, nodes[node_id], node_id == root, "  " * depth))
        for child in reversed(children.get(node_id, [])):
            stack.append((child, depth + 1))
    for node_id, (i, _node) in nodes.items():
        if node_id not in visited:
            # Edges form a tree only when every node hangs off the root; a cycle lands here too.
            raise v.error(ptr("/nodes", i), f"node {node_id!r} is not reachable from root {root!r}")
    lines = ["mindmap", *emit_comment(v, ir, indent="  "), *body]
    return "\n".join(emit_frontmatter(None, config) + lines) + "\n"


def _mindmap_node(v: Validator, node_id: str, entry: tuple[int, dict], is_root: bool, indent: str) -> list[str]:
    i, node = entry
    path = ptr("/nodes", i)
    kind = v.enum(node["kind"], ptr(path, "kind"), tuple(_MINDMAP_SHAPES)) if "kind" in node else ("circle" if is_root else "default")
    markdown = v.boolean(node["markdown"], ptr(path, "markdown")) if "markdown" in node else False
    label_path = ptr(path, "label")
    if kind == "default":
        if markdown:
            raise v.error(ptr(path, "markdown"), "a markdown label needs a shape; the default shape is plain text")
        text = v.text(node["label"], label_path, "mindmap.bare")
    elif markdown:
        open_, close = _MINDMAP_SHAPES[kind]
        text = f'{node_id}{open_}"`{v.text(node["label"], label_path, "mindmap.markdown")}`"{close}'
    else:
        open_, close = _MINDMAP_SHAPES[kind]
        text = f'{node_id}{open_}"{v.text(node["label"], label_path, "mindmap.quoted")}"{close}'
    lines = [indent + text]
    if "icon" in node:
        lines.append(f"{indent}::icon({v.text(node['icon'], ptr(path, 'icon'), 'mindmap.icon')})")
    if "classes" in node:
        cpath = ptr(path, "classes")
        names = [v.ident(c, ptr(cpath, j), _MINDMAP_CLASS) for j, c in enumerate(_g2_min_one(v, node["classes"], cpath))]
        lines.append(f"{indent}:::{' '.join(names)}")
    return lines


register(Builder(
    "mindmap", "graph", ("mindmap",), _mindmap_serialize,
    text_fields=(
        "/comment", "/nodes/0/label", "/nodes/1/label", "/nodes/2/label", "/nodes/3/label",
        "/nodes/4/label", "/nodes/5/label", "/nodes/6/label", "/nodes/7/label", "/nodes/8/label",
    ),
    features={
        "mindmap.root": "/root",
        "mindmap.indentation-hierarchy": "/edges/*/to",
        "mindmap.unclear-indentation": "/edges/*/from",
        "mindmap.shape-default": "/nodes/*/kind=default",
        "mindmap.shape-square": "/nodes/*/kind=square",
        "mindmap.shape-rounded": "/nodes/*/kind=rounded",
        "mindmap.shape-circle": "/nodes/*/kind=circle",
        "mindmap.shape-bang": "/nodes/*/kind=bang",
        "mindmap.shape-cloud": "/nodes/*/kind=cloud",
        "mindmap.shape-hexagon": "/nodes/*/kind=hexagon",
        "mindmap.icon": "/nodes/*/icon",
        "mindmap.class": "/nodes/*/classes/0",
        "mindmap.markdown-string": "/nodes/*/markdown=true",
        "mindmap.line-break": "/nodes/*/label=On effectiveness\nand features",
        "mindmap.comment": "/comment",
    },
    probes={"object": "/nodes/1", "number": "/config/mindmap/padding", "enum": "/nodes/1/kind", "ref": "/edges/0/to"},
))

# === end group 2 ===


# === group 3: chart: pie, quadrantChart, xyChart, sankey, radar, treemap, venn ========
#
# Free text in every chart type is encoded with the full ENTITY table: each code was rendered
# with CLI 12.0.0 and comes back as the original character in the SVG text, while the raw
# characters break (`"`, `%%`, backtick, `\`) in at least one position. Chart options that
# Mermaid reads from frontmatter are a typed `config` object (validate_config), never a string.
# sankey is hand-author-only: its CSV lexer accepts printable ASCII only, so ordinary text such
# as `Ünïcode 日本` cannot be a node name, and no entity code survives it either.

_CHART_THEMES = (
    "default", "base", "dark", "forest", "neutral", "neo", "neo-dark",
    "redux", "redux-dark", "redux-color", "redux-dark-color",
)
_CHART_LOOKS = ("classic", "handDrawn", "neo")
_CHART_HEX = r"#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})"


def _chart_text_contexts(type_id: str) -> None:
    """`<type>.text` (free text, ENTITY-encoded) and `<type>.css-length` (frontmatter sizes)."""
    text_context(f"{type_id}.text", encode=ENTITY)
    text_context(
        f"{type_id}.css-length",
        reject_patterns=((r"^(?![0-9]+(\.[0-9]+)?(px|em|rem|%)?$)", "must be a CSS length such as 12px"),),
    )


def _chart_colors(*names: str) -> dict:
    return {name: ("color",) for name in names}


def _chart_no_empty(v: Validator, value: dict, path: str) -> None:
    """An empty nested config object would emit `key:` (YAML null) and reset Mermaid's defaults."""
    for key, item in value.items():
        if isinstance(item, dict):
            if not item:
                raise v.error(ptr(path, key), "must not be empty; omit the key instead")
            _chart_no_empty(v, item, ptr(path, key))


def _chart_config(v: Validator, ir: dict, schema: dict) -> tuple[list[str], dict]:
    """Validate `config` and return (frontmatter lines, config)."""
    if "config" not in ir:
        return [], {}
    config = validate_config(v, ir["config"], "/config", schema)
    _chart_no_empty(v, config, "/config")
    return emit_frontmatter(None, config), config


def _chart_style(v: Validator, style: Any, path: str, keys: dict[str, tuple[str, Any]], sep: str, colon: str) -> str:
    """A typed style object -> `key: value` pairs in a fixed key order.

    `keys` maps IR key -> (Mermaid property, check) where check is a text context name,
    or ("number", min, max).
    """
    v.fields(style, path, (), tuple(keys))
    if not style:
        raise v.error(path, "must set at least one style key")
    parts = []
    for key, (prop, check) in keys.items():
        if key not in style:
            continue
        sub = ptr(path, key)
        if isinstance(check, tuple):
            value = v.number(style[key], sub, check[1], check[2], integer=check[0] == "integer")
        else:
            value = v.text(style[key], sub, check)
        parts.append(f"{prop}{colon}{value}")
    return sep.join(parts)


# --- pie -----------------------------------------------------------------------------------

_chart_text_contexts("pie")

_PIE_CONFIG = {
    "theme": ("enum", _CHART_THEMES),
    "pie": {
        "textPosition": ("number", 0, 1),
        "donutHole": ("number", 0, 0.9),
        "legendPosition": ("enum", ("top", "bottom", "left", "right", "center")),
        "highlightSlice": ("string", "pie.text"),
        "useMaxWidth": ("boolean",),
    },
    "themeVariables": {
        "pieOuterStrokeWidth": ("string", "pie.css-length"),
        **_chart_colors(*(f"pie{i}" for i in range(1, 13))),
        "pieOpacity": ("number", 0, 1),
        "pieStrokeColor": ("color",),
        "pieStrokeWidth": ("string", "pie.css-length"),
        "pieOuterStrokeColor": ("color",),
        "pieTitleTextSize": ("string", "pie.css-length"),
        "pieTitleTextColor": ("color",),
        "pieSectionTextSize": ("string", "pie.css-length"),
        "pieSectionTextColor": ("color",),
        "pieLegendTextSize": ("string", "pie.css-length"),
        "pieLegendTextColor": ("color",),
    },
}


def _pie_serialize(ir: dict, keyword: str) -> str:
    v = Validator(keyword)
    v.fields(ir, "", ("slices",), ("title", "titlePlacement", "showData", "accessibility", "config"))
    front, config = _chart_config(v, ir, _PIE_CONFIG)
    title = v.text(ir["title"], "/title", "pie.text") if "title" in ir else None
    placement = "statement"
    if "titlePlacement" in ir:
        placement = v.enum(ir["titlePlacement"], "/titlePlacement", ("statement", "inline"))
        if title is None:
            raise v.error("/titlePlacement", "needs a 'title'")
    show_data = v.boolean(ir["showData"], "/showData") if "showData" in ir else False
    body: list[str] = []
    labels: set[str] = set()
    for i, item in enumerate(v.array(ir["slices"], "/slices", 1)):
        path = ptr("/slices", i)
        v.fields(item, path, ("label", "value"))
        label = v.text(item["label"], ptr(path, "label"), "pie.text")
        # Mermaid keeps the first of two equal labels and silently drops the second.
        v.unique(item["label"], ptr(path, "label"), labels, "slice label")
        value = v.number(item["value"], ptr(path, "value"), 0)
        body.append(f'    "{label}" : {value}')
    highlight = config.get("pie", {}).get("highlightSlice")
    if highlight is not None and highlight != "hover":
        where = "/config/pie/highlightSlice"
        v.ref(highlight, where, labels)
        if v.text(highlight, where, "pie.text") != highlight:
            raise v.error(where, "Mermaid compares it to the parsed label, which differs when the label needs entity codes")
    head = "pie" + (" showData" if show_data else "")
    if title is not None and placement == "inline":
        head += f" title {title}"
    lines = [*front, head]
    if title is not None and placement == "statement":
        lines.append(f"    title {title}")
    lines += emit_accessibility(v, ir)
    lines += body
    return "\n".join(lines) + "\n"


register(Builder(
    "pie", "chart", ("pie",), _pie_serialize,
    text_fields=("/title", "/slices/*/label", "/accessibility/title", "/accessibility/description"),
    features={
        "pie.keyword": "/target=pie",
        "pie.show-data": "/showData=true",
        "pie.title-inline": "/titlePlacement=inline",
        "pie.title-statement": "/titlePlacement=statement",
        "pie.slice": "/slices/*/label",
        "pie.slice-decimal": "/slices/*/value=42.96",
    },
    probes={
        "object": "/slices/0",
        "number": "/slices/0/value",
        "enum": "/titlePlacement",
        "ref": "/config/pie/highlightSlice",
    },
))


# --- quadrantChart -------------------------------------------------------------------------

_chart_text_contexts("quadrantChart")
text_context(
    "quadrantChart.color",
    reject_patterns=((rf"^(?!{_CHART_HEX}$)", "must be a #rgb or #rrggbb hex colour"),),
)
text_context(
    "quadrantChart.stroke-width",
    reject_patterns=((r"^(?![0-9]+px$)", "must be a whole number of px, e.g. 2px"),),
)
_QUADRANT_CLASS = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_QUADRANT_STYLE = {
    "radius": ("radius", ("integer", 0, None)),
    "color": ("color", "quadrantChart.color"),
    "strokeColor": ("stroke-color", "quadrantChart.color"),
    "strokeWidth": ("stroke-width", "quadrantChart.stroke-width"),
}
_QUADRANT_NUMBERS = (
    "chartWidth", "chartHeight", "titlePadding", "titleFontSize", "quadrantPadding",
    "quadrantTextTopPadding", "quadrantLabelFontSize", "quadrantInternalBorderStrokeWidth",
    "quadrantExternalBorderStrokeWidth", "xAxisLabelPadding", "xAxisLabelFontSize",
    "yAxisLabelPadding", "yAxisLabelFontSize", "pointTextPadding", "pointLabelFontSize", "pointRadius",
)
_QUADRANT_CONFIG = {
    "theme": ("enum", _CHART_THEMES),
    "quadrantChart": {
        **{name: ("number", 0, None) for name in _QUADRANT_NUMBERS},
        "xAxisPosition": ("enum", ("top", "bottom")),
        "yAxisPosition": ("enum", ("left", "right")),
        "useMaxWidth": ("boolean",),
    },
    "themeVariables": _chart_colors(
        *(f"quadrant{i}Fill" for i in range(1, 5)),
        *(f"quadrant{i}TextFill" for i in range(1, 5)),
        "quadrantPointFill", "quadrantPointTextFill", "quadrantXAxisTextFill", "quadrantYAxisTextFill",
        "quadrantInternalBorderStrokeFill", "quadrantExternalBorderStrokeFill", "quadrantTitleFill",
    ),
}


def _quadrant_serialize(ir: dict, keyword: str) -> str:
    v = Validator(keyword)
    v.fields(ir, "", (), ("title", "xAxis", "yAxis", "quadrants", "points", "classes", "accessibility", "config"))
    front, _config = _chart_config(v, ir, _QUADRANT_CONFIG)
    lines = [*front, "quadrantChart"]
    if "title" in ir:
        lines.append(f"    title {v.text(ir['title'], '/title', 'quadrantChart.text')}")
    lines += emit_accessibility(v, ir)

    def quoted(value: Any, path: str) -> str:
        return f'"{v.text(value, path, "quadrantChart.text")}"'

    for key, statement, first, second in (("xAxis", "x-axis", "left", "right"), ("yAxis", "y-axis", "bottom", "top")):
        if key not in ir:
            continue
        path = f"/{key}"
        axis = v.fields(ir[key], path, (first,), (second,))
        text = f"    {statement} {quoted(axis[first], ptr(path, first))}"
        if second in axis:
            text += f" --> {quoted(axis[second], ptr(path, second))}"
        lines.append(text)
    if "quadrants" in ir:
        quadrants = v.fields(ir["quadrants"], "/quadrants", (), ("1", "2", "3", "4"))
        for index in ("1", "2", "3", "4"):
            if index in quadrants:
                lines.append(f"    quadrant-{index} {quoted(quadrants[index], ptr('/quadrants', index))}")

    classes: dict[str, set[str]] = {}
    class_lines: list[str] = []
    if "classes" in ir:
        for name, style in v.obj_map(ir["classes"], "/classes").items():
            path = ptr("/classes", name)
            v.ident(name, path, _QUADRANT_CLASS)
            class_lines.append(f"    classDef {name} {_chart_style(v, style, path, _QUADRANT_STYLE, ', ', ': ')}")
            classes[name] = set(style)

    for i, point in enumerate(v.array(ir.get("points", []), "/points")):
        path = ptr("/points", i)
        v.fields(point, path, ("label", "x", "y"), ("class", "style"))
        text = f"    {quoted(point['label'], ptr(path, 'label'))}"
        effective: set[str] = set()
        if "class" in point:
            effective |= classes.get(v.ref(point["class"], ptr(path, "class"), classes), set())
            text += f":::{point['class']}"
        x_value = v.number(point["x"], ptr(path, "x"), 0, 1)
        y_value = v.number(point["y"], ptr(path, "y"), 0, 1)
        text += f": [{x_value}, {y_value}]"
        if "style" in point:
            text += " " + _chart_style(v, point["style"], ptr(path, "style"), _QUADRANT_STYLE, ", ", ": ")
            effective |= set(point["style"])
        if "strokeColor" in effective and "strokeWidth" not in effective:
            where = ptr(ptr(path, "style"), "strokeColor") if "strokeColor" in point.get("style", {}) else ptr(path, "class")
            raise v.error(where, "stroke colour has no effect without strokeWidth on the same point")
        lines.append(text)
    lines += class_lines
    return "\n".join(lines) + "\n"


register(Builder(
    "quadrantChart", "chart", ("quadrantChart",), _quadrant_serialize,
    text_fields=(
        "/title", "/xAxis/left", "/xAxis/right", "/yAxis/bottom", "/yAxis/top",
        "/quadrants/1", "/quadrants/2", "/quadrants/3", "/quadrants/4", "/points/*/label",
        "/accessibility/title", "/accessibility/description",
    ),
    features={
        "quadrantChart.keyword": "/target=quadrantChart",
        "quadrantChart.title": "/title",
        "quadrantChart.x-axis-both": "/xAxis/right",
        "quadrantChart.x-axis-left-only": "/xAxis/left",
        "quadrantChart.y-axis-both": "/yAxis/top",
        "quadrantChart.y-axis-bottom-only": "/yAxis/bottom",
        "quadrantChart.quadrant-1": "/quadrants/1",
        "quadrantChart.quadrant-2": "/quadrants/2",
        "quadrantChart.quadrant-3": "/quadrants/3",
        "quadrantChart.quadrant-4": "/quadrants/4",
        "quadrantChart.quoted-text": "/points/*/label",
        "quadrantChart.point": "/points/*/x",
        "quadrantChart.point-radius": "/points/*/style/radius",
        "quadrantChart.point-color": "/points/*/style/color",
        "quadrantChart.point-stroke-color": "/points/*/style/strokeColor",
        "quadrantChart.point-stroke-width": "/points/*/style/strokeWidth",
        "quadrantChart.point-class": "/points/*/class",
        "quadrantChart.class-def": "/classes/*",
    },
    probes={
        "object": "/points/0/style",
        "number": "/points/0/x",
        "enum": "/config/quadrantChart/xAxisPosition",
        "ref": "/points/1/class",
    },
))


# --- xyChart -------------------------------------------------------------------------------

_chart_text_contexts("xyChart")
text_context(
    "xyChart.palette",
    reject_patterns=((rf"^(?!{_CHART_HEX}(, ?{_CHART_HEX})*$)", "must be hex colours separated by ', '"),),
)
_XY_AXIS_CONFIG = {
    "showLabel": ("boolean",),
    "labelFontSize": ("number", 0, None),
    "labelPadding": ("number", 0, None),
    "showTitle": ("boolean",),
    "titleFontSize": ("number", 0, None),
    "titlePadding": ("number", 0, None),
    "showTick": ("boolean",),
    "tickLength": ("number", 0, None),
    "tickWidth": ("number", 0, None),
    "showAxisLine": ("boolean",),
    "axisLineWidth": ("number", 0, None),
    "labelRotation": ("number", -360, 360),
}
_XY_CONFIG = {
    "theme": ("enum", _CHART_THEMES),
    "xyChart": {
        "width": ("number", 0, None),
        "height": ("number", 0, None),
        "titlePadding": ("number", 0, None),
        "titleFontSize": ("number", 0, None),
        "showTitle": ("boolean",),
        "showLegend": ("boolean",),
        "legendFontSize": ("number", 0, None),
        "legendPadding": ("number", 0, None),
        "xAxis": _XY_AXIS_CONFIG,
        "yAxis": _XY_AXIS_CONFIG,
        "chartOrientation": ("enum", ("vertical", "horizontal")),
        "plotReservedSpacePercent": ("number", 0, 100),
        "showDataLabel": ("boolean",),
        "showDataLabelOutsideBar": ("boolean",),
        "useMaxWidth": ("boolean",),
    },
    "themeVariables": {
        "xyChart": {
            **_chart_colors(
                "backgroundColor", "titleColor", "dataLabelColor", "legendTextColor",
                "xAxisLabelColor", "xAxisTitleColor", "xAxisTickColor", "xAxisLineColor",
                "yAxisLabelColor", "yAxisTitleColor", "yAxisTickColor", "yAxisLineColor",
            ),
            "plotColorPalette": ("string", "xyChart.palette"),
        },
    },
}


def _xy_range(v: Validator, axis: dict, path: str) -> str | None:
    """`min --> max`, both or neither."""
    if "min" not in axis and "max" not in axis:
        return None
    for key in ("min", "max"):
        if key not in axis:
            raise v.error(ptr(path, key), "required key is missing ('min' and 'max' go together)")
    low = v.number(axis["min"], ptr(path, "min"))
    high = v.number(axis["max"], ptr(path, "max"))
    if not axis["min"] < axis["max"]:
        raise v.error(ptr(path, "max"), "must be greater than min")
    return f"{low} --> {high}"


def _xy_serialize(ir: dict, keyword: str) -> str:
    v = Validator(keyword)
    v.fields(ir, "", ("series",), ("orientation", "title", "xAxis", "yAxis", "comment", "accessibility", "config"))
    front, _config = _chart_config(v, ir, _XY_CONFIG)

    def quoted(value: Any, path: str) -> str:
        return f'"{v.text(value, path, "xyChart.text")}"'

    head = keyword
    if "orientation" in ir:
        head += " " + v.enum(ir["orientation"], "/orientation", ("vertical", "horizontal"))
    lines = [*front, head]
    if "title" in ir:
        lines.append(f"    title {quoted(ir['title'], '/title')}")
    lines += emit_accessibility(v, ir)

    categories: list[Any] | None = None
    if "xAxis" in ir:
        axis = v.fields(ir["xAxis"], "/xAxis", (), ("title", "categories", "min", "max"))
        if not axis:
            raise v.error("/xAxis", "must set title, categories, or min and max")
        parts = [quoted(axis["title"], "/xAxis/title")] if "title" in axis else []
        if "categories" in axis:
            if "min" in axis or "max" in axis:
                raise v.error("/xAxis/categories", "use categories or min and max, not both")
            categories = v.array(axis["categories"], "/xAxis/categories", 1)
            seen: set[str] = set()
            names = []
            for i, name in enumerate(categories):
                names.append(quoted(name, ptr("/xAxis/categories", i)))
                v.unique(name, ptr("/xAxis/categories", i), seen, "category")
            parts.append(f"[{', '.join(names)}]")
        else:
            span = _xy_range(v, axis, "/xAxis")
            if span:
                parts.append(span)
        lines.append("    x-axis " + " ".join(parts))
    if "yAxis" in ir:
        axis = v.fields(ir["yAxis"], "/yAxis", (), ("title", "min", "max"))
        if not axis:
            raise v.error("/yAxis", "must set title, or min and max")
        parts = [quoted(axis["title"], "/yAxis/title")] if "title" in axis else []
        span = _xy_range(v, axis, "/yAxis")
        if span:
            parts.append(span)
        lines.append("    y-axis " + " ".join(parts))
    lines += emit_comment(v, ir)

    for i, series in enumerate(v.array(ir["series"], "/series", 1)):
        path = ptr("/series", i)
        v.fields(series, path, ("type", "values"), ("name",))
        kind = v.enum(series["type"], ptr(path, "type"), ("bar", "line"))
        values = v.array(series["values"], ptr(path, "values"), 1)
        if categories is not None and len(values) != len(categories):
            raise v.error(ptr(path, "values"), f"has {len(values)} values for {len(categories)} categories")
        items = []
        for j, value in enumerate(values):
            at = ptr(ptr(path, "values"), j)
            if isinstance(value, dict):
                v.fields(value, at, ("value", "label"))
                if kind != "line":
                    raise v.error(ptr(at, "label"), "point labels render only on line series")
                items.append(f"{v.number(value['value'], ptr(at, 'value'))} {quoted(value['label'], ptr(at, 'label'))}")
            else:
                items.append(v.number(value, at))
        name = f" {quoted(series['name'], ptr(path, 'name'))}" if "name" in series else ""
        lines.append(f"    {kind}{name} [{', '.join(items)}]")
    return "\n".join(lines) + "\n"


register(Builder(
    "xyChart", "chart", ("xychart", "xychart-beta"), _xy_serialize,
    text_fields=(
        "/title", "/xAxis/title", "/xAxis/categories/*", "/yAxis/title", "/series/*/name",
        "/series/*/values/*/label", "/comment", "/accessibility/title", "/accessibility/description",
    ),
    features={
        "xyChart.keyword": "/target=xychart",
        "xyChart.keyword-beta": "/target=xychart-beta",
        "xyChart.orientation-vertical": "/orientation=vertical",
        "xyChart.orientation-horizontal": "/orientation=horizontal",
        "xyChart.title": "/title",
        "xyChart.x-axis-categories": "/xAxis/categories",
        "xyChart.x-axis-title": "/xAxis/title",
        "xyChart.x-axis-range": "/xAxis/min",
        "xyChart.y-axis-range": "/yAxis/min",
        "xyChart.y-axis-title-only": "/yAxis/title",
        "xyChart.bar": "/series/1/type=bar",
        "xyChart.bar-named": "/series/0/name",
        "xyChart.line": "/series/3/type=line",
        "xyChart.line-named": "/series/2/name",
        "xyChart.line-point-label": "/series/*/values/*/label",
        "xyChart.number-forms": "/series/*/values/*=-5.34",
        "xyChart.comment": "/comment",
    },
    probes={"object": "/yAxis", "number": "/yAxis/min", "enum": "/orientation", "ref": None},
))


# --- sankey --------------------------------------------------------------------------------

hand_author_only("sankey", "sankey", "sankey-beta")


# --- radar ---------------------------------------------------------------------------------

_chart_text_contexts("radar")
# Grammar keywords that cannot be axis or curve ids (each fails with CLI 12.0.0).
_RADAR_RESERVED = frozenset((
    "axis", "curve", "title", "max", "min", "ticks", "graticule", "showLegend",
    "true", "false", "circle", "polygon",
))
_RADAR_CONFIG = {
    "theme": ("enum", _CHART_THEMES),
    "radar": {
        name: ("number", 0, None)
        for name in (
            "width", "height", "marginTop", "marginBottom", "marginLeft", "marginRight",
            "axisScaleFactor", "axisLabelFactor", "curveTension",
        )
    },
    "themeVariables": {
        "fontSize": ("string", "radar.css-length"),
        "titleColor": ("color",),
        **_chart_colors(*(f"cScale{i}" for i in range(12))),
        "radar": {
            "axisColor": ("color",),
            "axisStrokeWidth": ("number", 0, None),
            "axisLabelFontSize": ("string", "radar.css-length"),
            "curveOpacity": ("number", 0, 1),
            "curveStrokeWidth": ("number", 0, None),
            "graticuleColor": ("color",),
            "graticuleOpacity": ("number", 0, 1),
            "graticuleStrokeWidth": ("number", 0, None),
            "legendBoxSize": ("number", 0, None),
            "legendFontSize": ("string", "radar.css-length"),
        },
    },
}


def _radar_id(v: Validator, value: Any, path: str, seen: set[str], what: str) -> str:
    v.ident(value, path)
    if value in _RADAR_RESERVED:
        raise v.error(path, f"{value!r} is a radar keyword and cannot be an id")
    return v.unique(value, path, seen, what)


def _radar_serialize(ir: dict, keyword: str) -> str:
    v = Validator(keyword)
    v.fields(
        ir, "", ("axes", "curves"),
        ("title", "showLegend", "max", "min", "graticule", "ticks", "accessibility", "config"),
    )
    front, _config = _chart_config(v, ir, _RADAR_CONFIG)
    lines = [*front, "radar-beta"]
    if "title" in ir:
        lines.append(f"    title {v.text(ir['title'], '/title', 'radar.text')}")
    lines += emit_accessibility(v, ir)

    def named(item: dict, path: str, seen: set[str], what: str) -> str:
        text = _radar_id(v, item["id"], ptr(path, "id"), seen, what)
        if "label" in item:
            text += f'["{v.text(item["label"], ptr(path, "label"), "radar.text")}"]'
        return text

    axis_ids: list[str] = []
    axis_bits = []
    seen_axes: set[str] = set()
    for i, axis in enumerate(v.array(ir["axes"], "/axes", 1)):
        path = ptr("/axes", i)
        v.fields(axis, path, ("id",), ("label",))
        axis_bits.append(named(axis, path, seen_axes, "axis id"))
        axis_ids.append(axis["id"])
    lines.append("    axis " + ", ".join(axis_bits))

    curve_bits = []
    seen_curves: set[str] = set()
    for i, curve in enumerate(v.array(ir["curves"], "/curves", 1)):
        path = ptr("/curves", i)
        v.fields(curve, path, ("id",), ("label", "values", "entries"))
        text = named(curve, path, seen_curves, "curve id")
        if ("values" in curve) == ("entries" in curve):
            raise v.error(path, "needs exactly one of 'values' (in axis order) or 'entries' (keyed by axis)")
        if "values" in curve:
            values = v.array(curve["values"], ptr(path, "values"))
            if len(values) != len(axis_ids):
                # Mermaid renders the chart but silently omits such a curve.
                raise v.error(ptr(path, "values"), f"has {len(values)} values for {len(axis_ids)} axes")
            numbers = [v.number(value, ptr(ptr(path, "values"), j), 0) for j, value in enumerate(values)]
            text += "{" + ", ".join(numbers) + "}"
        else:
            entries = v.array(curve["entries"], ptr(path, "entries"))
            named_axes: set[str] = set()
            pairs = []
            for j, entry in enumerate(entries):
                at = ptr(ptr(path, "entries"), j)
                v.fields(entry, at, ("axis", "value"))
                v.ref(entry["axis"], ptr(at, "axis"), seen_axes)
                v.unique(entry["axis"], ptr(at, "axis"), named_axes, "axis")
                pairs.append(f"{entry['axis']}: {v.number(entry['value'], ptr(at, 'value'), 0)}")
            missing = [axis for axis in axis_ids if axis not in named_axes]
            if missing:
                raise v.error(ptr(path, "entries"), f"must name every axis; missing: {', '.join(missing)}")
            text += "{ " + ", ".join(pairs) + " }"
        curve_bits.append(text)
    lines.append("    curve " + ", ".join(curve_bits))

    if "showLegend" in ir:
        lines.append(f"    showLegend {'true' if v.boolean(ir['showLegend'], '/showLegend') else 'false'}")
    if "max" in ir:
        lines.append(f"    max {v.number(ir['max'], '/max', 0)}")
    if "min" in ir:
        lines.append(f"    min {v.number(ir['min'], '/min', 0)}")
        if "max" in ir and not ir["min"] < ir["max"]:
            raise v.error("/min", "must be less than max")
    if "graticule" in ir:
        lines.append(f"    graticule {v.enum(ir['graticule'], '/graticule', ('circle', 'polygon'))}")
    if "ticks" in ir:
        lines.append(f"    ticks {v.number(ir['ticks'], '/ticks', 1, integer=True)}")
    return "\n".join(lines) + "\n"


register(Builder(
    "radar", "chart", ("radar-beta",), _radar_serialize,
    text_fields=("/title", "/axes/*/label", "/curves/*/label", "/accessibility/title", "/accessibility/description"),
    features={
        "radar.keyword": "/target=radar-beta",
        "radar.title": "/title",
        "radar.axis": "/axes/*/id",
        "radar.axis-label": "/axes/*/label",
        "radar.axis-multi": "/axes/1/id",
        "radar.curve": "/curves/*/values",
        "radar.curve-label": "/curves/*/label",
        "radar.curve-multi": "/curves/1/id",
        "radar.curve-key-value": "/curves/*/entries",
        "radar.show-legend": "/showLegend",
        "radar.max": "/max",
        "radar.min": "/min",
        "radar.graticule-circle": "/graticule=circle",
        "radar.graticule-polygon": "/graticule=polygon",
        "radar.ticks": "/ticks",
    },
    probes={
        "object": "/curves/2/entries/0",
        "number": "/max",
        "enum": "/graticule",
        "ref": "/curves/2/entries/0/axis",
    },
))


# --- treemap -------------------------------------------------------------------------------

_chart_text_contexts("treemap")
text_context(
    "treemap.color",
    reject_patterns=((rf"^(?!{_CHART_HEX}$|[a-z]+$)", "must be a #rgb or #rrggbb hex colour or a CSS colour name"),),
)
text_context(
    "treemap.stroke-width",
    reject_patterns=((r"^(?![0-9]+(\.[0-9]+)?px$)", "must be a number of px, e.g. 2px"),),
)
_TREEMAP_STYLE = {
    "fill": ("fill", "treemap.color"),
    "color": ("color", "treemap.color"),
    "stroke": ("stroke", "treemap.color"),
    "strokeWidth": ("stroke-width", "treemap.stroke-width"),
}
_TREEMAP_CONFIG = {
    "theme": ("enum", _CHART_THEMES),
    "treemap": {
        "useMaxWidth": ("boolean",),
        "padding": ("number", 0, None),
        "diagramPadding": ("number", 0, None),
        "showValues": ("boolean",),
        "nodeWidth": ("number", 0, None),
        "nodeHeight": ("number", 0, None),
        "borderWidth": ("number", 0, None),
        "valueFontSize": ("number", 0, None),
        "labelFontSize": ("number", 0, None),
        # The patterns the syntax page lists, minus `$,.2f` (12.0.0 renders it as `$1.2e+3`).
        "valueFormat": ("enum", (",", "$", ".1f", ".1%", "$0,0", "$.2f")),
    },
    "themeVariables": _chart_colors(*(f"cScale{i}" for i in range(12)), *(f"cScalePeer{i}" for i in range(12))),
}


def _treemap_serialize(ir: dict, keyword: str) -> str:
    v = Validator(keyword)
    v.fields(ir, "", ("nodes",), ("classes", "indent", "accessibility", "config"))
    front, _config = _chart_config(v, ir, _TREEMAP_CONFIG)
    tabs = "indent" in ir and v.enum(ir["indent"], "/indent", ("spaces", "tabs")) == "tabs"
    unit, base = ("\t", "") if tabs else ("    ", "    ")

    classes: set[str] = set()
    class_lines: list[str] = []
    if "classes" in ir:
        for name, style in v.obj_map(ir["classes"], "/classes").items():
            path = ptr("/classes", name)
            v.ident(name, path)
            class_lines.append(f"classDef {name} {_chart_style(v, style, path, _TREEMAP_STYLE, ',', ':')};")
            classes.add(name)

    body: list[str] = []

    def node(item: Any, path: str, depth: int) -> None:
        v.fields(item, path, ("label",), ("value", "children", "class"))
        text = f'{base}{unit * depth}"{v.text(item["label"], ptr(path, "label"), "treemap.text")}"'
        suffix = ""
        if "class" in item:
            suffix = f":::{v.ref(item['class'], ptr(path, 'class'), classes)}"
        if ("value" in item) == ("children" in item):
            # Lines under a node with a value become siblings, not children, in Mermaid.
            raise v.error(path, "needs exactly one of 'value' (a leaf) or 'children' (a section)")
        if "value" in item:
            body.append(f"{text}: {v.number(item['value'], ptr(path, 'value'), 0)}{suffix}")
            return
        body.append(text + suffix)
        for i, child in enumerate(v.array(item["children"], ptr(path, "children"), 1)):
            node(child, ptr(ptr(path, "children"), i), depth + 1)

    for i, item in enumerate(v.array(ir["nodes"], "/nodes", 1)):
        node(item, ptr("/nodes", i), 0)
    lines = [*front, keyword, *emit_accessibility(v, ir, indent=base), *body, *class_lines]
    return "\n".join(lines) + "\n"


register(Builder(
    "treemap", "chart", ("treemap-beta", "treemap"), _treemap_serialize,
    text_fields=("/nodes/*/label", "/nodes/*/children/*/label", "/accessibility/title", "/accessibility/description"),
    features={
        "treemap.keyword": "/target=treemap-beta",
        "treemap.keyword-alias": "/target=treemap",
        "treemap.section": "/nodes/*/children",
        "treemap.leaf": "/nodes/*/children/*/value",
        "treemap.nested-section": "/nodes/*/children/*/children",
        "treemap.indent-tabs": "/indent=tabs",
        "treemap.section-class": "/nodes/0/children/1/class",
        "treemap.leaf-class": "/nodes/0/children/0/children/1/class",
        "treemap.class-def": "/classes/*",
    },
    probes={
        "object": "/nodes/0",
        "number": "/nodes/0/children/0/children/0/value",
        "enum": "/indent",
        "ref": "/nodes/0/children/1/class",
    },
))


# --- venn ----------------------------------------------------------------------------------

_chart_text_contexts("venn")
text_context(
    "venn.color",
    reject_patterns=((rf"^(?!{_CHART_HEX}$|[a-z]+$)", "must be a #rgb or #rrggbb hex colour or a CSS colour name"),),
)
text_context(
    "venn.stroke-width",
    reject_patterns=((r"^(?![0-9]+(\.[0-9]+)?px$)", "must be a number of px, e.g. 3px"),),
)
# Statement keywords; a bare id equal to one of them fails, so such ids are quoted.
_VENN_KEYWORDS = frozenset(("set", "union", "text", "style", "title"))
_VENN_STYLE = {
    "fill": ("fill", "venn.color"),
    "color": ("color", "venn.color"),
    "stroke": ("stroke", "venn.color"),
    "strokeWidth": ("stroke-width", "venn.stroke-width"),
    "fillOpacity": ("fill-opacity", ("number", 0, 1)),
}
_VENN_CONFIG = {
    "theme": ("enum", _CHART_THEMES),
    "look": ("enum", _CHART_LOOKS),
    "venn": {
        "theme": ("enum", _CHART_THEMES),
        "look": ("enum", _CHART_LOOKS),
        "width": ("number", 0, None),
        "height": ("number", 0, None),
        "padding": ("number", 0, None),
        "useMaxWidth": ("boolean",),
        "useDebugLayout": ("boolean",),
    },
    "themeVariables": _chart_colors(*(f"venn{i}" for i in range(1, 9)), "vennSetTextColor", "vennTitleTextColor"),
}


def _venn_serialize(ir: dict, keyword: str) -> str:
    v = Validator(keyword)
    v.fields(ir, "", ("sets",), ("title", "unions", "styles", "config"))
    front, _config = _chart_config(v, ir, _VENN_CONFIG)
    lines = [*front, "venn-beta"]
    if "title" in ir:
        lines.append(f"    title {v.text(ir['title'], '/title', 'venn.text')}")

    ids: set[str] = set()  # set and text ids share one namespace (style targets either)
    set_ids: dict[str, str] = {}  # IR id -> emitted token
    text_ids: dict[str, str] = {}

    def token(value: Any, path: str) -> str:
        encoded = v.text(value, path, "venn.text")
        v.unique(value, path, ids)
        if _IDENT.fullmatch(value) and value.lower() not in _VENN_KEYWORDS:
            return value
        return f'"{encoded}"'

    def tail(item: dict, path: str) -> str:
        text = ""
        if "label" in item:
            text += f'["{v.text(item["label"], ptr(path, "label"), "venn.text")}"]'
        if "size" in item:
            text += f":{v.number(item['size'], ptr(path, 'size'), 0)}"
        return text

    def texts(item: dict, path: str) -> None:
        for i, text_node in enumerate(v.array(item.get("texts", []), ptr(path, "texts"))):
            at = ptr(ptr(path, "texts"), i)
            v.fields(text_node, at, ("id",), ("label",))
            emitted = token(text_node["id"], ptr(at, "id"))
            text_ids[text_node["id"]] = emitted
            lines.append(f"        text {emitted}{tail(text_node, at)}")

    for i, item in enumerate(v.array(ir["sets"], "/sets", 1)):
        path = ptr("/sets", i)
        v.fields(item, path, ("id",), ("label", "size", "texts"))
        emitted = token(item["id"], ptr(path, "id"))
        set_ids[item["id"]] = emitted
        lines.append(f"    set {emitted}{tail(item, path)}")
        texts(item, path)

    unions: set[frozenset[str]] = set()
    for i, item in enumerate(v.array(ir.get("unions", []), "/unions")):
        path = ptr("/unions", i)
        v.fields(item, path, ("sets",), ("label", "size", "texts"))
        members = v.array(item["sets"], ptr(path, "sets"), 2)
        seen: set[str] = set()
        for j, member in enumerate(members):
            v.ref(member, ptr(ptr(path, "sets"), j), set_ids)
            v.unique(member, ptr(ptr(path, "sets"), j), seen, "set in this union")
        key = frozenset(members)
        if key in unions:
            raise v.error(ptr(path, "sets"), "another union already covers these sets")
        unions.add(key)
        lines.append(f"    union {','.join(set_ids[m] for m in members)}{tail(item, path)}")
        texts(item, path)

    for i, item in enumerate(v.array(ir.get("styles", []), "/styles")):
        path = ptr("/styles", i)
        v.fields(item, path, ("targets", "style"))
        targets = v.array(item["targets"], ptr(path, "targets"), 1)
        known = {**set_ids, **text_ids} if len(targets) == 1 else set_ids
        seen = set()
        for j, target in enumerate(targets):
            v.ref(target, ptr(ptr(path, "targets"), j), known)
            v.unique(target, ptr(ptr(path, "targets"), j), seen, "target")
        if len(targets) > 1 and frozenset(targets) not in unions:
            raise v.error(ptr(path, "targets"), "no union declares exactly these sets")
        names = ",".join({**set_ids, **text_ids}[t] for t in targets)
        lines.append(f"    style {names} {_chart_style(v, item['style'], ptr(path, 'style'), _VENN_STYLE, ',', ':')}")
    return "\n".join(lines) + "\n"


register(Builder(
    "venn", "chart", ("venn-beta",), _venn_serialize,
    text_fields=(
        "/title", "/sets/*/id", "/sets/*/label", "/sets/*/texts/*/id", "/sets/*/texts/*/label",
        "/unions/*/label", "/unions/*/texts/*/id", "/unions/*/texts/*/label",
    ),
    features={
        "venn.keyword": "/target=venn-beta",
        "venn.title": "/title",
        "venn.set": "/sets/*/id",
        "venn.set-quoted-id": "/sets/*/id=Feasible tech",
        "venn.set-label": "/sets/*/label",
        "venn.union": "/unions/*/sets",
        "venn.union-higher-arity": "/unions/*/sets/2",
        "venn.set-size": "/sets/*/size",
        "venn.union-size": "/unions/*/size",
        "venn.text": "/sets/*/texts/*/id",
        "venn.text-label": "/sets/*/texts/*/label",
        "venn.style-fill": "/styles/*/style/fill",
        "venn.style-color": "/styles/*/style/color",
        "venn.style-stroke": "/styles/*/style/stroke",
        "venn.style-stroke-width": "/styles/*/style/strokeWidth",
        "venn.style-fill-opacity": "/styles/*/style/fillOpacity",
        "venn.style-union-target": "/styles/*/targets/1",
    },
    probes={
        "object": "/styles/0/style",
        "number": "/sets/1/size",
        "enum": "/config/venn/look",
        "ref": "/unions/0/sets/0",
    },
))

# === end group 3 ===


# === group 4: structure: c4, architecture, block, packet, requirementDiagram ==========

# --- group 4 shared helpers -----------------------------------------------------------------

# A frontmatter title is emitted as a JSON (YAML 1.2) string scalar, so nothing needs encoding.
text_context("g4.frontmatter-title")
text_context(
    "g4.style-color",
    reject_patterns=((r"^(?!#[0-9A-Fa-f]{3}([0-9A-Fa-f]{1}|[0-9A-Fa-f]{3}|[0-9A-Fa-f]{5})?$|[a-z]+$)",
                      "must be #hex (3, 4, 6 or 8 digits) or a lowercase CSS color name"),),
)
text_context(
    "g4.style-length",
    reject_patterns=((r"^(?!\d+(\.\d+)?(px|em|rem|pt)$)", "must be a CSS length such as 4px"),),
)
text_context(
    "g4.style-dash",
    reject_patterns=((r"^(?!\d+( \d+)*$)", "must be whole numbers separated by single spaces, such as 5 5"),),
)

# IR style key -> (CSS property, text context). Emitted in this order.
_G4_STYLE_TEXT = (
    ("fill", "fill", "g4.style-color"),
    ("stroke", "stroke", "g4.style-color"),
    ("color", "color", "g4.style-color"),
    ("strokeWidth", "stroke-width", "g4.style-length"),
    ("strokeDasharray", "stroke-dasharray", "g4.style-dash"),
    ("fontSize", "font-size", "g4.style-length"),
)
_G4_FONT_WEIGHTS = ("normal", "bold", "bolder", "lighter", "100", "200", "300", "400", "500", "600", "700", "800", "900")
_G4_FONT_STYLES = ("normal", "italic", "oblique")
_G4_STYLE_KEYS = tuple(key for key, _, _ in _G4_STYLE_TEXT) + ("fontWeight", "fontStyle")


def _g4_style(v: Validator, value: Any, path: str) -> str:
    """A typed style object -> `fill:#f9f,stroke:#333,stroke-width:4px` (for style / classDef)."""
    obj = v.fields(value, path, optional=_G4_STYLE_KEYS)
    if not obj:
        raise v.error(path, f"must set at least one of: {', '.join(_G4_STYLE_KEYS)}")
    parts = []
    for key, css, context in _G4_STYLE_TEXT:
        if key in obj:
            parts.append(f"{css}:{v.text(obj[key], ptr(path, key), context)}")
    if "fontWeight" in obj:
        parts.append(f"font-weight:{v.enum(obj['fontWeight'], ptr(path, 'fontWeight'), _G4_FONT_WEIGHTS)}")
    if "fontStyle" in obj:
        parts.append(f"font-style:{v.enum(obj['fontStyle'], ptr(path, 'fontStyle'), _G4_FONT_STYLES)}")
    return ",".join(parts)


def _g4_frontmatter(v: Validator, ir: dict, namespace: str, schema: dict, title: Any = None) -> list[str]:
    """Frontmatter with an optional title (already chosen by the caller) and typed `config`."""
    title_text = None
    if title is not None:
        title_text = v.text(title, "/title", "g4.frontmatter-title")
    config = None
    if "config" in ir:
        validated = validate_config(v, ir["config"], "/config", schema)
        config = {namespace: validated} if validated else None
    return emit_frontmatter(title_text, config)


def _g4_id(v: Validator, value: Any, path: str, reserved: set[str] = frozenset(), *,
           fold: bool = False, pattern: re.Pattern[str] = _IDENT, seen: dict | None = None) -> str:
    """A bare identifier that is not a keyword of the type, optionally unique in `seen`."""
    v.ident(value, path, pattern)
    if (value.lower() if fold else value) in reserved:
        raise v.error(path, f"{json.dumps(value)} is a keyword in this diagram type; choose another id")
    if seen is not None:
        if value in seen:
            raise v.error(path, f"duplicate id {json.dumps(value)} (first declared at {seen[value]})")
        seen[value] = path
    return value


# --- c4 -------------------------------------------------------------------------------------

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
    "C4Container": {"system_boundary", "container_boundary", "boundary"},
    "C4Component": {"container_boundary", "boundary"},
    "C4Dynamic": {"container_boundary", "boundary"},
    "C4Deployment": set(_C4_DEPLOYMENT_KINDS),
}
_C4_REL_KINDS = {
    "rel": "Rel",
    "birel": "BiRel",
    "rel_up": "Rel_Up",
    "rel_u": "Rel_U",
    "rel_down": "Rel_Down",
    "rel_d": "Rel_D",
    "rel_left": "Rel_Left",
    "rel_l": "Rel_L",
    "rel_right": "Rel_Right",
    "rel_r": "Rel_R",
    "rel_back": "Rel_Back",
    "rel_index": "RelIndex",
}
_C4_CONFIG = {
    "wrap": ("boolean",),
    "wrapPadding": ("number", 0, 1000),
    "c4ShapeInRow": ("integer", 1, 100),
    "c4BoundaryInRow": ("integer", 1, 100),
    "width": ("number", 1, 10000),
    "height": ("number", 1, 10000),
    "c4ShapeMargin": ("number", 0, 1000),
    "c4ShapePadding": ("number", 0, 1000),
    "diagramMarginX": ("number", 0, 1000),
    "diagramMarginY": ("number", 0, 1000),
    "boxMargin": ("number", 0, 1000),
    "nextLinePaddingX": ("number", 0, 1000),
    "useMaxWidth": ("boolean",),
}
# UpdateElementStyle / UpdateRelStyle: IR key -> C4 parameter, in positional order.
_C4_ELEMENT_STYLE = (("bg_color", "bgColor"), ("font_color", "fontColor"), ("border_color", "borderColor"))
_C4_REL_STYLE_COLORS = (("text_color", "textColor"), ("line_color", "lineColor"))
_C4_REL_STYLE_OFFSETS = (("offset_x", "offsetX"), ("offset_y", "offsetY"))

# Element (shape) text: no entity decoding, `>` is stripped, `&lt;` decodes, `<br>` breaks a line.
text_context(
    "c4.element",
    encode={"\n": "<br/>"},
    reject='"<>',
    allow_newline=True,
    reject_patterns=(
        (r"&#?\w+;|#\w+;", "C4 shapes do not round-trip entity codes"),
        (r"  ", "repeated spaces collapse to one in C4 shapes"),
        (r"\n\n|\n | \n", "a line break must sit between two non-blank lines"),
    ),
)
# Boundary, deployment node and relationship text: entity codes decode.
text_context("c4.boundary", encode={'"': ENTITY['"'], "#": ENTITY["#"], "<": ENTITY["<"], ">": ENTITY[">"]})
text_context("c4.rel", encode={'"': ENTITY['"'], "#": ENTITY["#"], "<": ENTITY["<"], ">": ENTITY[">"]})
text_context("c4.title", encode={"#": ENTITY["#"], ";": ENTITY[";"], "&": ENTITY["&"]})
# $tags, $link, $sprite: parsed, not drawn; only the closing quote cannot be carried.
text_context("c4.param", reject='"')


def _c4_quote(v: Validator, value: Any, path: str, context: str) -> str:
    return f'"{v.text(value, path, context)}"'


def _c4_serialize(ir: dict, keyword: str) -> str:
    v = Validator(keyword)
    v.fields(ir, "", ("nodes",), ("groups", "edges", "title", "accessibility", "comment", "config",
                                   "element_styles", "rel_styles", "layout"))
    lines = _g4_frontmatter(v, ir, "c4", _C4_CONFIG)
    lines.append(keyword)
    lines += emit_comment(v, ir)
    if "title" in ir:
        lines.append(f"    title {v.text(ir['title'], '/title', 'c4.title')}")
        if isinstance(ir.get("accessibility"), dict) and "title" in ir["accessibility"]:
            raise v.error("/accessibility/title", "C4 keeps title and accTitle in one slot and draws only the last; set one of them")
    lines += emit_accessibility(v, ir)

    seen: dict[str, str] = {}
    node_kinds = _C4_TARGET_NODE_KINDS[keyword]
    boundary_kinds = _C4_TARGET_BOUNDARY_KINDS[keyword]

    groups = v.array(ir.get("groups", []), "/groups")
    group_ids: dict[str, int] = {}
    for i, group in enumerate(groups):
        p = f"/groups/{i}"
        v.fields(group, p, ("id", "label", "kind"), ("boundary_type", "technology", "description", "group"))
        _g4_id(v, group["id"], ptr(p, "id"), seen=seen)
        kind = v.enum(group["kind"], ptr(p, "kind"), sorted(boundary_kinds))
        if "group" in group:
            v.ref(group["group"], ptr(p, "group"), group_ids)  # a parent comes before its children
        if "boundary_type" in group and kind != "boundary":
            raise v.error(ptr(p, "boundary_type"), "only kind 'boundary' takes boundary_type")
        for key in ("technology", "description"):
            if key in group and kind not in _C4_DEPLOYMENT_KINDS:
                raise v.error(ptr(p, key), f"only deployment nodes take {key}")
        group_ids[group["id"]] = i

    nodes = v.array(ir["nodes"], "/nodes", 1)
    node_ids: set[str] = set()
    for i, node in enumerate(nodes):
        p = f"/nodes/{i}"
        v.fields(node, p, ("id", "label", "kind"), ("description", "technology", "group", "tags", "link", "sprite"))
        _g4_id(v, node["id"], ptr(p, "id"), seen=seen)
        kind = v.enum(node["kind"], ptr(p, "kind"), sorted(node_kinds))
        if "technology" in node and kind not in _C4_TECH_KINDS:
            raise v.error(ptr(p, "technology"), f"kind {kind!r} takes no technology; only containers and components do")
        if "group" in node:
            v.ref(node["group"], ptr(p, "group"), group_ids)
        node_ids.add(node["id"])

    children: dict[str | None, list[tuple[str, int]]] = {}
    for i, node in enumerate(nodes):
        children.setdefault(node.get("group"), []).append(("node", i))
    for i, group in enumerate(groups):
        children.setdefault(group.get("group"), []).append(("group", i))
    for i, group in enumerate(groups):
        if not children.get(group["id"]):
            raise v.error(f"/groups/{i}", "a boundary must contain at least one node or group (Mermaid rejects an empty body)")

    def emit_node(i: int, indent: str) -> None:
        node, p = nodes[i], f"/nodes/{i}"
        args = [node["id"], _c4_quote(v, node["label"], ptr(p, "label"), "c4.element")]
        if "technology" in node:
            args.append(_c4_quote(v, node["technology"], ptr(p, "technology"), "c4.element"))
        if "description" in node:
            description = _c4_quote(v, node["description"], ptr(p, "description"), "c4.element")
            needs_name = node["kind"] in _C4_TECH_KINDS and "technology" not in node
            args.append(f"$descr={description}" if needs_name else description)
        for key in ("tags", "link", "sprite"):
            if key in node:
                args.append(f"${key}={_c4_quote(v, node[key], ptr(p, key), 'c4.param')}")
        lines.append(f'{indent}{_C4_NODE_KINDS[node["kind"]]}({", ".join(args)})')

    def emit_group(i: int, indent: str) -> None:
        group, p = groups[i], f"/groups/{i}"
        args = [group["id"], _c4_quote(v, group["label"], ptr(p, "label"), "c4.boundary")]
        if "boundary_type" in group:
            args.append(_c4_quote(v, group["boundary_type"], ptr(p, "boundary_type"), "c4.boundary"))
        if "technology" in group:
            args.append(_c4_quote(v, group["technology"], ptr(p, "technology"), "c4.boundary"))
        if "description" in group:
            description = _c4_quote(v, group["description"], ptr(p, "description"), "c4.boundary")
            args.append(description if "technology" in group else f"$descr={description}")
        lines.append(f'{indent}{_C4_BOUNDARY_KINDS[group["kind"]]}({", ".join(args)}) {{')
        emit_level(group["id"], indent + "    ")
        lines.append(f"{indent}}}")

    def emit_level(parent: str | None, indent: str) -> None:
        # Nodes first, then nested boundaries, each in input order.
        level = children.get(parent, [])
        for what, i in level:
            if what == "node":
                emit_node(i, indent)
        for what, i in level:
            if what == "group":
                emit_group(i, indent)

    emit_level(None, "    ")

    rel_pairs: set[tuple[str, str]] = set()
    for i, edge in enumerate(v.array(ir.get("edges", []), "/edges")):
        p = f"/edges/{i}"
        v.fields(edge, p, ("from", "to", "label"), ("kind", "technology", "index"))
        v.ref(edge["from"], ptr(p, "from"), node_ids)
        v.ref(edge["to"], ptr(p, "to"), node_ids)
        kind = v.enum(edge["kind"], ptr(p, "kind"), sorted(_C4_REL_KINDS)) if "kind" in edge else "rel"
        args = [edge["from"], edge["to"], _c4_quote(v, edge["label"], ptr(p, "label"), "c4.rel")]
        if kind == "rel_index":
            if keyword != "C4Dynamic":
                raise v.error(ptr(p, "kind"), "rel_index is only valid on C4Dynamic")
            if "index" not in edge:
                raise v.error(ptr(p, "index"), "required key is missing for kind 'rel_index'")
            args.insert(0, v.number(edge["index"], ptr(p, "index"), 1, integer=True))
        elif "index" in edge:
            raise v.error(ptr(p, "index"), "only kind 'rel_index' takes an index")
        if "technology" in edge:
            args.append(_c4_quote(v, edge["technology"], ptr(p, "technology"), "c4.rel"))
        lines.append(f'    {_C4_REL_KINDS[kind]}({", ".join(args)})')
        rel_pairs.add((edge["from"], edge["to"]))

    styleable = set(node_ids) | set(group_ids)
    for i, style in enumerate(v.array(ir.get("element_styles", []), "/element_styles")):
        p = f"/element_styles/{i}"
        keys = tuple(key for key, _ in _C4_ELEMENT_STYLE)
        v.fields(style, p, ("element",), keys + ("form",))
        v.ref(style["element"], ptr(p, "element"), styleable)
        values = [(key, name, f'"{v.text(style[key], ptr(p, key), "g4.style-color")}"')
                  for key, name in _C4_ELEMENT_STYLE if key in style]
        lines.append(f"    UpdateElementStyle({style['element']}, {_c4_params(v, p, style, values, keys)})")

    for i, style in enumerate(v.array(ir.get("rel_styles", []), "/rel_styles")):
        p = f"/rel_styles/{i}"
        keys = tuple(key for key, _ in _C4_REL_STYLE_COLORS + _C4_REL_STYLE_OFFSETS)
        v.fields(style, p, ("from", "to"), keys + ("form",))
        v.ref(style["from"], ptr(p, "from"), node_ids)
        v.ref(style["to"], ptr(p, "to"), node_ids)
        if (style["from"], style["to"]) not in rel_pairs:
            raise v.error(p, f"no relationship from {style['from']!r} to {style['to']!r}; Mermaid would ignore this style")
        values = [(key, name, f'"{v.text(style[key], ptr(p, key), "g4.style-color")}"')
                  for key, name in _C4_REL_STYLE_COLORS if key in style]
        values += [(key, name, f'"{v.number(style[key], ptr(p, key), -10000, 10000, integer=True)}"')
                   for key, name in _C4_REL_STYLE_OFFSETS if key in style]
        lines.append(f"    UpdateRelStyle({style['from']}, {style['to']}, {_c4_params(v, p, style, values, keys)})")

    if "layout" in ir:
        layout = v.fields(ir["layout"], "/layout", optional=("shape_in_row", "boundary_in_row"))
        if not layout:
            raise v.error("/layout", "must set shape_in_row or boundary_in_row")
        params = []
        for key, name in (("shape_in_row", "c4ShapeInRow"), ("boundary_in_row", "c4BoundaryInRow")):
            if key in layout:
                params.append(f'${name}="{v.number(layout[key], ptr("/layout", key), 1, 100, integer=True)}"')
        lines.append(f"    UpdateLayoutConfig({', '.join(params)})")
    return "\n".join(lines) + "\n"


def _c4_params(v: Validator, path: str, style: dict, values: list[tuple[str, str, str]], order: tuple[str, ...]) -> str:
    """`$name="value"` arguments, or positional ones when `form` is `positional`."""
    if not values:
        raise v.error(path, f"must set at least one of: {', '.join(order)}")
    form = v.enum(style["form"], ptr(path, "form"), ("named", "positional")) if "form" in style else "named"
    if form == "named":
        return ", ".join(f"${name}={text}" for _key, name, text in values)
    present = [key for key, _name, _text in values]
    expected = list(order[: len(present)])
    if sorted(present, key=order.index) != expected:
        missing = next(key for key in expected if key not in present)
        raise v.error(ptr(path, "form"), f"positional form needs every earlier parameter; {missing!r} is missing")
    return ", ".join(text for _key, _name, text in sorted(values, key=lambda item: order.index(item[0])))


# --- architecture ---------------------------------------------------------------------------

_ARCH_BASE_ICONS = ("cloud", "database", "disk", "internet", "server")
_ARCH_ICON_PACK = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*:[a-z0-9]+(-[a-z0-9]+)*")
_ARCH_SIDES = ("T", "B", "L", "R")
_ARCH_ARROWS = {"none": ("", ""), "forward": ("", ">"), "backward": ("<", ""), "both": ("<", ">")}
# Ids starting with a side letter or `title` are lexed as keywords by the 12.0.0 parser.
_ARCH_ID = re.compile(r"(?![LRTB]|title)[A-Za-z_][A-Za-z0-9_]*")
_ARCH_RESERVED = {"service", "group", "junction", "in", "align", "row", "column", "accTitle", "accDescr"}
_ARCH_CONFIG = {
    "padding": ("number", 0, 1000),
    "iconSize": ("number", 1, 1000),
    "fontSize": ("number", 1, 200),
    "randomize": ("boolean",),
    "nodeSeparation": ("number", 0, 10000),
    "idealEdgeLengthMultiplier": ("number", 0, 100),
    "edgeElasticity": ("number", 0, 1),
    "numIter": ("integer", 1, 1000000),
    "seed": ("integer", 0, 2147483647),
    "useMaxWidth": ("boolean",),
}
_ARCH_MARKDOWN = (r"[*_~`]|\\[!-/:-@\[-`{-~]", "'*', '_', '~', '`' and a backslash before punctuation are read as Markdown in architecture titles")
_ARCH_ENTITY = (r"&#?\w+;|#\w+;", "architecture titles do not round-trip entity codes")
text_context(
    "architecture.label",
    reject_patterns=(_ARCH_MARKDOWN, _ARCH_ENTITY, (r"  ", "repeated spaces collapse to one"), (r'^"', "a title cannot start with '\"'")),
)
# Titles with brackets use the quoted ["..."] form, which cannot carry a double quote.
text_context(
    "architecture.label-quoted",
    reject='"',
    reject_patterns=(_ARCH_MARKDOWN, _ARCH_ENTITY, (r"  ", "repeated spaces collapse to one")),
)


def _arch_label(v: Validator, value: Any, path: str) -> str:
    if isinstance(value, str) and ("[" in value or "]" in value):
        return f'["{v.text(value, path, "architecture.label-quoted")}"]'
    return f"[{v.text(value, path, 'architecture.label')}]"


def _arch_icon(v: Validator, obj: dict, path: str) -> str:
    if "icon" not in obj:
        return ""
    icon = obj["icon"]
    if isinstance(icon, str) and _ARCH_ICON_PACK.fullmatch(icon):
        return f"({icon})"
    if icon not in _ARCH_BASE_ICONS:
        raise v.error(ptr(path, "icon"), f"unknown icon {json.dumps(icon)}; use one of {', '.join(_ARCH_BASE_ICONS)} or 'pack:icon-name' for a registered icon pack")
    return f"({icon})"


def _arch_serialize(ir: dict, keyword: str) -> str:
    v = Validator(keyword)
    v.fields(ir, "", ("nodes",), ("groups", "edges", "alignments", "accessibility", "comment", "config"))
    lines = _g4_frontmatter(v, ir, "architecture", _ARCH_CONFIG)
    lines.append(keyword)
    lines += emit_accessibility(v, ir)
    lines += emit_comment(v, ir)
    seen: dict[str, str] = {}

    group_ids: set[str] = set()
    for i, group in enumerate(v.array(ir.get("groups", []), "/groups")):
        p = f"/groups/{i}"
        v.fields(group, p, ("id", "label"), ("icon", "group"))
        _g4_id(v, group["id"], ptr(p, "id"), _ARCH_RESERVED, pattern=_ARCH_ID, seen=seen)
        icon = _arch_icon(v, group, p)
        parent = ""
        if "group" in group:
            parent = f" in {v.ref(group['group'], ptr(p, 'group'), group_ids)}"  # declared on an earlier line
        lines.append(f"    group {group['id']}{icon}{_arch_label(v, group['label'], ptr(p, 'label'))}{parent}")
        group_ids.add(group["id"])

    node_group: dict[str, str | None] = {}
    node_kind: dict[str, str] = {}
    for i, node in enumerate(v.array(ir["nodes"], "/nodes", 1)):
        p = f"/nodes/{i}"
        v.fields(node, p, ("id",), ("kind", "label", "icon", "group"))
        _g4_id(v, node["id"], ptr(p, "id"), _ARCH_RESERVED, pattern=_ARCH_ID, seen=seen)
        kind = v.enum(node["kind"], ptr(p, "kind"), ("service", "junction")) if "kind" in node else "service"
        parent = ""
        if "group" in node:
            parent = f" in {v.ref(node['group'], ptr(p, 'group'), group_ids)}"
        if kind == "junction":
            for key in ("label", "icon"):
                if key in node:
                    raise v.error(ptr(p, key), "a junction has no label or icon")
            lines.append(f"    junction {node['id']}{parent}")
        else:
            if "label" not in node:
                raise v.error(ptr(p, "label"), "required key is missing for a service")
            icon = _arch_icon(v, node, p)
            lines.append(f"    service {node['id']}{icon}{_arch_label(v, node['label'], ptr(p, 'label'))}{parent}")
        node_group[node["id"]] = node.get("group")
        node_kind[node["id"]] = kind

    pairs: dict[tuple[str, str], int] = {}
    for i, edge in enumerate(v.array(ir.get("edges", []), "/edges")):
        p = f"/edges/{i}"
        v.fields(edge, p, ("from", "to", "from_side", "to_side"), ("arrow", "from_group", "to_group"))
        ends = []
        for end in ("from", "to"):
            node_id = v.ref(edge[end], ptr(p, end), node_group)
            side = v.enum(edge[f"{end}_side"], ptr(p, f"{end}_side"), _ARCH_SIDES)
            modifier = ""
            if f"{end}_group" in edge and v.boolean(edge[f"{end}_group"], ptr(p, f"{end}_group")):
                if node_kind[node_id] != "service" or node_group[node_id] is None:
                    raise v.error(ptr(p, f"{end}_group"), "the {group} modifier needs a service that is inside a group")
                modifier = "{group}"
            ends.append((node_id + modifier, side))
        if edge["from"] == edge["to"]:
            raise v.error(ptr(p, "to"), "an edge cannot connect a node to itself")
        pair = (edge["from"], edge["to"])
        if pair in pairs:
            raise v.error(p, f"a second edge from {pair[0]!r} to {pair[1]!r} crashes Mermaid (first at /edges/{pairs[pair]}); reverse it or route it through a junction")
        pairs[pair] = i
        left, right = v.enum(edge["arrow"], ptr(p, "arrow"), _ARCH_ARROWS) if "arrow" in edge else _ARCH_ARROWS["none"]
        (src, src_side), (dst, dst_side) = ends
        lines.append(f"    {src}:{src_side} {left}--{right} {dst_side}:{dst}")

    for i, align in enumerate(v.array(ir.get("alignments", []), "/alignments")):
        p = f"/alignments/{i}"
        v.fields(align, p, ("axis", "members"))
        axis = v.enum(align["axis"], ptr(p, "axis"), ("row", "column"))
        members: set[str] = set()
        for j, member in enumerate(v.array(align["members"], ptr(p, "members"), 2)):
            v.ref(member, ptr(ptr(p, "members"), j), node_group)
            v.unique(member, ptr(ptr(p, "members"), j), members, "member")
        lines.append(f"    align {axis} {' '.join(align['members'])}")
    return "\n".join(lines) + "\n"


# --- block ----------------------------------------------------------------------------------

_BLOCK_SHAPES = {
    "rect": ('["', '"]'),
    "round": ('("', '")'),
    "stadium": ('(["', '"])'),
    "subroutine": ('[["', '"]]'),
    "cylinder": ('[("', '")]'),
    "circle": ('(("', '"))'),
    "asymmetric": ('>"', '"]'),
    "rhombus": ('{"', '"}'),
    "hexagon": ('{{"', '"}}'),
    "parallelogram": ('[/"', '"/]'),
    "parallelogram-alt": ('[\\"', '"\\]'),
    "trapezoid": ('[/"', '"\\]'),
    "trapezoid-alt": ('[\\"', '"/]'),
    "double-circle": ('((("', '")))'),
}
_BLOCK_ARROW_DIRECTIONS = ("right", "left", "up", "down", "x", "y")
_BLOCK_EDGE_KINDS = {"arrow": "-->", "line": "---"}
_BLOCK_KINDS = ("block", "space", "arrow", "composite")
_BLOCK_RESERVED = {"end", "space", "block", "style", "class", "classDef", "default"}
_BLOCK_CONFIG = {"padding": ("number", 0, 1000), "useMaxWidth": ("boolean",)}
# Quoted block text decodes entity codes; U+00A0 is written as the HTML entity &nbsp;.
text_context(
    "block.label",
    encode={'"': ENTITY['"'], "#": ENTITY["#"], "<": ENTITY["<"], ">": ENTITY[">"], "&": ENTITY["&"],
            "`": ENTITY["`"], "\u00a0": "&nbsp;"},
)


def _block_serialize(ir: dict, keyword: str) -> str:
    v = Validator(keyword)
    v.fields(ir, "", ("blocks",), ("columns", "edges", "styles", "class_defs", "class_assignments", "comment", "config"))
    lines = _g4_frontmatter(v, ir, "block", _BLOCK_CONFIG)
    lines.append(keyword)
    lines += emit_comment(v, ir, indent="  ")
    if "columns" in ir:
        columns = "auto" if ir["columns"] == "auto" else v.number(ir["columns"], "/columns", 1, 100, integer=True)
        lines.append(f"  columns {columns}")
    seen: dict[str, str] = {}

    def label(obj: dict, path: str, shape: str = "rect") -> str:
        open_, close = _BLOCK_SHAPES[shape]
        return f"{open_}{v.text(obj['label'], ptr(path, 'label'), 'block.label')}{close}"

    def width(obj: dict, path: str) -> str:
        return f":{v.number(obj['width'], ptr(path, 'width'), 1, 100, integer=True)}" if "width" in obj else ""

    def walk(items: Any, path: str, indent: str) -> None:
        for i, item in enumerate(v.array(items, path, 1)):
            p = ptr(path, i)
            kind = "block"
            if isinstance(item, dict) and "kind" in item:
                kind = v.enum(item["kind"], ptr(p, "kind"), _BLOCK_KINDS)
            if kind == "block":
                v.fields(item, p, ("id",), ("kind", "label", "shape", "width"))
                block_id = _g4_id(v, item["id"], ptr(p, "id"), _BLOCK_RESERVED, seen=seen)
                text = ""
                if "shape" in item:
                    v.enum(item["shape"], ptr(p, "shape"), _BLOCK_SHAPES)
                    if "label" not in item:
                        raise v.error(ptr(p, "shape"), "a shape needs a label")
                    text = label(item, p, item["shape"])
                elif "label" in item:
                    text = label(item, p)
                lines.append(f"{indent}{block_id}{text}{width(item, p)}")
            elif kind == "space":
                v.fields(item, p, ("kind",), ("width",))
                lines.append(f"{indent}space{width(item, p)}")
            elif kind == "arrow":
                v.fields(item, p, ("kind", "id", "label", "directions"), ("width",))
                block_id = _g4_id(v, item["id"], ptr(p, "id"), _BLOCK_RESERVED, seen=seen)
                text = v.text(item["label"], ptr(p, "label"), "block.label")
                dirs: set[str] = set()
                dpath = ptr(p, "directions")
                for j, direction in enumerate(v.array(item["directions"], dpath, 1)):
                    v.enum(direction, ptr(dpath, j), _BLOCK_ARROW_DIRECTIONS)
                    v.unique(direction, ptr(dpath, j), dirs, "direction")
                lines.append(f'{indent}{block_id}<["{text}"]>({", ".join(item["directions"])}){width(item, p)}')
            else:
                v.fields(item, p, ("kind", "children"), ("id", "label", "width", "columns"))
                head = "block"
                if "id" in item:
                    head += ":" + _g4_id(v, item["id"], ptr(p, "id"), _BLOCK_RESERVED, seen=seen)
                    if "label" in item:
                        head += label(item, p)
                    head += width(item, p)
                else:
                    for key in ("label", "width"):
                        if key in item:
                            raise v.error(ptr(p, key), f"a composite block needs an id to take a {key}")
                lines.append(f"{indent}{head}")
                if "columns" in item:
                    columns = "auto" if item["columns"] == "auto" else v.number(item["columns"], ptr(p, "columns"), 1, 100, integer=True)
                    lines.append(f"{indent}  columns {columns}")
                walk(item["children"], ptr(p, "children"), indent + "  ")
                lines.append(f"{indent}end")

    walk(ir["blocks"], "/blocks", "  ")

    for i, edge in enumerate(v.array(ir.get("edges", []), "/edges")):
        p = f"/edges/{i}"
        v.fields(edge, p, ("from", "to"), ("label", "kind"))
        src = v.ref(edge["from"], ptr(p, "from"), seen)
        dst = v.ref(edge["to"], ptr(p, "to"), seen)
        arrow = v.enum(edge["kind"], ptr(p, "kind"), _BLOCK_EDGE_KINDS) if "kind" in edge else _BLOCK_EDGE_KINDS["arrow"]
        if "label" in edge:
            text = v.text(edge["label"], ptr(p, "label"), "block.label")
            lines.append(f'  {src} -- "{text}" {arrow} {dst}')
        else:
            lines.append(f"  {src} {arrow} {dst}")

    classes: set[str] = set()
    for i, class_def in enumerate(v.array(ir.get("class_defs", []), "/class_defs")):
        p = f"/class_defs/{i}"
        v.fields(class_def, p, ("name", "style"))
        name = v.ident(class_def["name"], ptr(p, "name"))
        if name in _BLOCK_RESERVED:
            raise v.error(ptr(p, "name"), f"{json.dumps(name)} is a keyword in block diagrams")
        v.unique(name, ptr(p, "name"), classes, "class name")
        lines.append(f"  classDef {name} {_g4_style(v, class_def['style'], ptr(p, 'style'))}")
    for i, assignment in enumerate(v.array(ir.get("class_assignments", []), "/class_assignments")):
        p = f"/class_assignments/{i}"
        v.fields(assignment, p, ("blocks", "class"))
        targets = [v.ref(b, ptr(ptr(p, "blocks"), j), seen) for j, b in enumerate(v.array(assignment["blocks"], ptr(p, "blocks"), 1))]
        lines.append(f"  class {','.join(targets)} {v.ref(assignment['class'], ptr(p, 'class'), classes)}")
    for i, style in enumerate(v.array(ir.get("styles", []), "/styles")):
        p = f"/styles/{i}"
        v.fields(style, p, ("block", "style"))
        lines.append(f"  style {v.ref(style['block'], ptr(p, 'block'), seen)} {_g4_style(v, style['style'], ptr(p, 'style'))}")
    return "\n".join(lines) + "\n"


# --- packet ---------------------------------------------------------------------------------

_PACKET_CONFIG = {
    "bitsPerRow": ("integer", 1, 1024),
    "bitWidth": ("number", 1, 1000),
    "rowHeight": ("number", 1, 1000),
    "showBits": ("boolean",),
    "paddingX": ("number", 0, 1000),
    "paddingY": ("number", 0, 1000),
    "useMaxWidth": ("boolean",),
}
text_context("packet.label", encode={'"': ENTITY['"'], "#": ENTITY["#"], "\\": ENTITY["\\"]})
text_context("packet.title", encode={"#": ENTITY["#"], "%": ENTITY["%"]})


def _packet_serialize(ir: dict, keyword: str) -> str:
    v = Validator(keyword)
    v.fields(ir, "", ("fields",), ("title", "title_in_frontmatter", "accessibility", "comment", "config"))
    in_frontmatter = False
    if "title_in_frontmatter" in ir:
        in_frontmatter = v.boolean(ir["title_in_frontmatter"], "/title_in_frontmatter")
        if in_frontmatter and "title" not in ir:
            raise v.error("/title_in_frontmatter", "is true but there is no title")
    lines = _g4_frontmatter(v, ir, "packet", _PACKET_CONFIG, ir.get("title") if in_frontmatter else None)
    lines.append(keyword)
    lines += emit_comment(v, ir)
    if "title" in ir and not in_frontmatter:
        lines.append(f"    title {v.text(ir['title'], '/title', 'packet.title')}")
    lines += emit_accessibility(v, ir)
    cursor = 0
    for i, field_ in enumerate(v.array(ir["fields"], "/fields", 1)):
        p = f"/fields/{i}"
        v.fields(field_, p, ("label",), ("bits", "bit", "start", "end"))
        forms = [key for key in ("bits", "bit", "start") if key in field_]
        if "end" in field_ and "start" not in field_:
            raise v.error(ptr(p, "end"), "needs start")
        if len(forms) != 1:
            raise v.error(p, "give exactly one of: bits, bit, or start with end")
        label = v.text(field_["label"], ptr(p, "label"), "packet.label")
        if "bits" in field_:
            bits = v.number(field_["bits"], ptr(p, "bits"), 1, integer=True)
            lines.append(f'    +{bits}: "{label}"')
            cursor += field_["bits"]
            continue
        key = "bit" if "bit" in field_ else "start"
        start = v.number(field_[key], ptr(p, key), 0, integer=True)
        if field_[key] != cursor:
            raise v.error(ptr(p, key), f"is {start}, but fields must be contiguous: the next free bit is {cursor}")
        if key == "bit":
            lines.append(f'    {start}: "{label}"')
            cursor += 1
            continue
        if "end" not in field_:
            raise v.error(ptr(p, "end"), "required key is missing; use bit for a single-bit field")
        end = v.number(field_["end"], ptr(p, "end"), field_["start"] + 1, integer=True)
        lines.append(f'    {start}-{end}: "{label}"')
        cursor = field_["end"] + 1
    return "\n".join(lines) + "\n"


# --- requirementDiagram ---------------------------------------------------------------------

_REQUIREMENT_TYPES = (
    "requirement", "functionalRequirement", "interfaceRequirement",
    "performanceRequirement", "physicalRequirement", "designConstraint",
)
_REQUIREMENT_RISKS = ("low", "medium", "high")
_REQUIREMENT_METHODS = ("analysis", "inspection", "test", "demonstration")
_REQUIREMENT_LINK_KINDS = ("contains", "copies", "derives", "satisfies", "verifies", "refines", "traces")
_REQUIREMENT_DIRECTIONS = ("TB", "BT", "LR", "RL")
# Whole-word, case-insensitive keywords of the 12.0.0 lexer; a bare name equal to one fails to parse.
_REQUIREMENT_RESERVED = {
    *(t.lower() for t in _REQUIREMENT_TYPES), "element", *_REQUIREMENT_LINK_KINDS,
    "style", "class", "classdef", "click", "text", "risk", "type", "id", "docref", "verifymethod",
    *_REQUIREMENT_RISKS, *_REQUIREMENT_METHODS,
}
# Quoted requirement text is Markdown with HTML: encode everything that would be read as markup.
_REQUIREMENT_ENCODE = {'"': ENTITY['"'], "#": ENTITY["#"], "<": ENTITY["<"], ">": ENTITY[">"], "&": ENTITY["&"],
                       "\\": ENTITY["\\"]}
text_context("requirementDiagram.text", encode={**_REQUIREMENT_ENCODE, "*": "#42;", "_": "#95;"})
text_context("requirementDiagram.markdown", encode=_REQUIREMENT_ENCODE)


def _requirement_serialize(ir: dict, keyword: str) -> str:
    v = Validator(keyword)
    v.fields(ir, "", ("requirements",), ("elements", "links", "title", "direction", "accessibility", "comment",
                                          "styles", "class_defs", "class_assignments"))
    lines = _g4_frontmatter(v, ir, "requirement", {}, ir.get("title"))
    lines.append(keyword)
    lines += emit_accessibility(v, ir)
    if "direction" in ir:
        lines.append(f"    direction {v.enum(ir['direction'], '/direction', _REQUIREMENT_DIRECTIONS)}")
    lines += emit_comment(v, ir)

    # class names are needed by the `:::` shorthand on definitions, so read classDefs first.
    classes: dict[str, str] = {}
    class_lines = []
    for i, class_def in enumerate(v.array(ir.get("class_defs", []), "/class_defs")):
        p = f"/class_defs/{i}"
        v.fields(class_def, p, ("name", "style"))
        name = v.ident(class_def["name"], ptr(p, "name"))
        if name.lower() in _REQUIREMENT_RESERVED:
            raise v.error(ptr(p, "name"), f"{json.dumps(name)} is a keyword in requirement diagrams")
        v.unique(name, ptr(p, "name"), set(classes), "class name")
        classes[name] = p
        class_lines.append(f"    classDef {name} {_g4_style(v, class_def['style'], ptr(p, 'style'))}")

    def class_list(value: Any, path: str) -> str:
        names: set[str] = set()
        for j, name in enumerate(v.array(value, path, 1)):
            v.ref(name, ptr(path, j), classes)
            v.unique(name, ptr(path, j), names, "class")
        return ",".join(value)

    seen: dict[str, str] = {}
    refs: dict[str, str] = {}  # IR id -> emitted node name
    emitted: dict[str, str] = {}  # emitted node name -> path

    def node_name(obj: dict, path: str, context: str) -> str:
        _g4_id(v, obj["id"], ptr(path, "id"), _REQUIREMENT_RESERVED, fold=True, seen=seen)
        name = f'"{v.text(obj["name"], ptr(path, "name"), context)}"' if "name" in obj else obj["id"]
        key = obj.get("name", obj["id"])
        if key in emitted:
            raise v.error(ptr(path, "name") if "name" in obj else ptr(path, "id"),
                          f"node name {json.dumps(key)} is already used at {emitted[key]}")
        emitted[key] = path
        refs[obj["id"]] = name
        return name

    def context_of(obj: dict, path: str) -> str:
        if "markdown" in obj and v.boolean(obj["markdown"], ptr(path, "markdown")):
            return "requirementDiagram.markdown"
        return "requirementDiagram.text"

    for i, req in enumerate(v.array(ir["requirements"], "/requirements")):
        p = f"/requirements/{i}"
        v.fields(req, p, ("id",), ("type", "name", "req_id", "text", "risk", "verify_method", "classes", "markdown"))
        context = context_of(req, p)
        rtype = v.enum(req["type"], ptr(p, "type"), _REQUIREMENT_TYPES) if "type" in req else "requirement"
        name = node_name(req, p, context)
        shorthand = f":::{class_list(req['classes'], ptr(p, 'classes'))}" if "classes" in req else ""
        lines.append(f"    {rtype} {name}{shorthand} {{")
        if "req_id" in req:
            lines.append(f'        id: "{v.text(req["req_id"], ptr(p, "req_id"), context)}"')
        if "text" in req:
            lines.append(f'        text: "{v.text(req["text"], ptr(p, "text"), context)}"')
        if "risk" in req:
            lines.append(f"        risk: {v.enum(req['risk'], ptr(p, 'risk'), _REQUIREMENT_RISKS)}")
        if "verify_method" in req:
            lines.append(f"        verifymethod: {v.enum(req['verify_method'], ptr(p, 'verify_method'), _REQUIREMENT_METHODS)}")
        lines.append("    }")

    for i, element in enumerate(v.array(ir.get("elements", []), "/elements")):
        p = f"/elements/{i}"
        v.fields(element, p, ("id",), ("name", "type", "docref", "classes", "markdown"))
        context = context_of(element, p)
        name = node_name(element, p, context)
        shorthand = f":::{class_list(element['classes'], ptr(p, 'classes'))}" if "classes" in element else ""
        lines.append(f"    element {name}{shorthand} {{")
        if "type" in element:
            lines.append(f'        type: "{v.text(element["type"], ptr(p, "type"), context)}"')
        if "docref" in element:
            lines.append(f'        docRef: "{v.text(element["docref"], ptr(p, "docref"), context)}"')
        lines.append("    }")

    for i, link in enumerate(v.array(ir.get("links", []), "/links")):
        p = f"/links/{i}"
        v.fields(link, p, ("from", "to", "kind"), ("reverse",))
        src = refs[v.ref(link["from"], ptr(p, "from"), refs)]
        dst = refs[v.ref(link["to"], ptr(p, "to"), refs)]
        kind = v.enum(link["kind"], ptr(p, "kind"), _REQUIREMENT_LINK_KINDS)
        if "reverse" in link and v.boolean(link["reverse"], ptr(p, "reverse")):
            lines.append(f"    {dst} <- {kind} - {src}")
        else:
            lines.append(f"    {src} - {kind} -> {dst}")

    lines += class_lines

    def node_list(value: Any, path: str) -> str:
        names: set[str] = set()
        out = []
        for j, node in enumerate(v.array(value, path, 1)):
            v.ref(node, ptr(path, j), refs)
            v.unique(node, ptr(path, j), names, "node")
            out.append(refs[node])
        return ",".join(out)

    for i, assignment in enumerate(v.array(ir.get("class_assignments", []), "/class_assignments")):
        p = f"/class_assignments/{i}"
        v.fields(assignment, p, ("nodes", "classes"), ("shorthand",))
        nodes = node_list(assignment["nodes"], ptr(p, "nodes"))
        names = class_list(assignment["classes"], ptr(p, "classes"))
        if "shorthand" in assignment and v.boolean(assignment["shorthand"], ptr(p, "shorthand")):
            if len(assignment["nodes"]) != 1:
                raise v.error(ptr(p, "nodes"), "the ::: shorthand takes exactly one node")
            lines.append(f"    {nodes}:::{names}")
        else:
            lines.append(f"    class {nodes} {names}")
    for i, style in enumerate(v.array(ir.get("styles", []), "/styles")):
        p = f"/styles/{i}"
        v.fields(style, p, ("nodes", "style"))
        lines.append(f"    style {node_list(style['nodes'], ptr(p, 'nodes'))} {_g4_style(v, style['style'], ptr(p, 'style'))}")
    return "\n".join(lines) + "\n"


# --- registration ---------------------------------------------------------------------------

_C4_ELEMENT_TEXT = ("/nodes/*/label", "/nodes/*/description", "/nodes/*/technology")
register(Builder(
    "c4", "graph", ("C4Context", "C4Container", "C4Component", "C4Dynamic", "C4Deployment"), _c4_serialize,
    text_fields=_C4_ELEMENT_TEXT + (
        "/nodes/*/tags", "/nodes/*/link", "/nodes/*/sprite",
        "/groups/*/label", "/groups/*/boundary_type", "/groups/*/technology", "/groups/*/description",
        "/edges/*/label", "/edges/*/technology",
        "/title", "/comment", "/accessibility/title", "/accessibility/description",
    ),
    features={
        "c4.keyword-c4context": "/target=C4Context",
        "c4.keyword-c4container": "/target=C4Container",
        "c4.keyword-c4component": "/target=C4Component",
        "c4.keyword-c4dynamic": "/target=C4Dynamic",
        "c4.keyword-c4deployment": "/target=C4Deployment",
        "c4.title": "/title",
        "c4.acc-title": "/accessibility/title",
        "c4.acc-descr": "/accessibility/description=Containers inside the banking system",
        "c4.acc-descr-block": "/accessibility/description=Customers, the banking system\nand its neighbours.",
        "c4.comment": "/comment",
        **{f"c4.{kind.replace('_', '-')}": f"/nodes/*/kind={kind}" for kind in _C4_NODE_KINDS},
        "c4.boundary": "/groups/*/kind=boundary",
        "c4.enterprise-boundary": "/groups/*/kind=enterprise_boundary",
        "c4.system-boundary": "/groups/*/kind=system_boundary",
        "c4.container-boundary": "/groups/*/kind=container_boundary",
        "c4.deployment-node": "/groups/*/kind=deployment_node",
        "c4.node": "/groups/*/kind=node",
        "c4.node-l": "/groups/*/kind=node_left",
        "c4.node-r": "/groups/*/kind=node_right",
        "c4.nested-boundary": "/groups/*/group",
        "c4.rel": "/edges/*/kind=rel",
        "c4.birel": "/edges/*/kind=birel",
        "c4.rel-up": "/edges/*/kind=rel_up",
        "c4.rel-u": "/edges/*/kind=rel_u",
        "c4.rel-down": "/edges/*/kind=rel_down",
        "c4.rel-d": "/edges/*/kind=rel_d",
        "c4.rel-left": "/edges/*/kind=rel_left",
        "c4.rel-l": "/edges/*/kind=rel_l",
        "c4.rel-right": "/edges/*/kind=rel_right",
        "c4.rel-r": "/edges/*/kind=rel_r",
        "c4.rel-back": "/edges/*/kind=rel_back",
        "c4.rel-index": "/edges/*/index",
        "c4.rel-technology": "/edges/*/technology",
        "c4.element-description": "/nodes/*/description",
        "c4.element-technology": "/nodes/*/technology",
        "c4.boundary-type": "/groups/*/boundary_type",
        "c4.positional-params": "/rel_styles/*/form=positional",
        "c4.named-params": "/rel_styles/*/form=named",
        "c4.param-tags": "/nodes/*/tags",
        "c4.param-link": "/nodes/*/link",
        "c4.param-sprite": "/nodes/*/sprite",
        "c4.label-line-break": "/nodes/0/description=A customer\nwith accounts",
        "c4.update-element-style": "/element_styles/*/element",
        "c4.style-bg-color": "/element_styles/*/bg_color",
        "c4.style-font-color": "/element_styles/*/font_color",
        "c4.style-border-color": "/element_styles/*/border_color",
        "c4.update-rel-style": "/rel_styles/*/from",
        "c4.style-text-color": "/rel_styles/*/text_color",
        "c4.style-line-color": "/rel_styles/*/line_color",
        "c4.style-offset-x": "/rel_styles/*/offset_x",
        "c4.style-offset-y": "/rel_styles/*/offset_y",
        "c4.update-layout-config": "/layout",
        "c4.layout-shape-in-row": "/layout/shape_in_row",
        "c4.layout-boundary-in-row": "/layout/boundary_in_row",
    },
    probes={"object": "/nodes/1", "number": "/rel_styles/0/offset_y", "enum": "/edges/1/kind", "ref": "/edges/0/from"},
))
register(Builder(
    "architecture", "graph", ("architecture-beta",), _arch_serialize,
    text_fields=("/groups/*/label", "/nodes/*/label", "/comment", "/accessibility/title", "/accessibility/description"),
    features={
        "architecture.keyword": "/target=architecture-beta",
        "architecture.group": "/groups/*/icon",
        "architecture.group-nested": "/groups/*/group",
        "architecture.group-no-icon": "/groups/2/label=Storage",
        "architecture.service": "/nodes/*/icon",
        "architecture.service-in-group": "/nodes/*/group",
        "architecture.service-no-icon": "/nodes/5/label=Logs",
        "architecture.junction": "/nodes/*/kind=junction",
        "architecture.junction-in-group": "/nodes/8/group",
        "architecture.edge": "/edges/*/arrow=none",
        "architecture.side-left": "/edges/*/from_side=L",
        "architecture.side-right": "/edges/*/from_side=R",
        "architecture.side-top": "/edges/*/from_side=T",
        "architecture.side-bottom": "/edges/*/from_side=B",
        "architecture.edge-right-angle": "/edges/3/to_side=L",
        "architecture.arrow-right": "/edges/*/arrow=forward",
        "architecture.arrow-left": "/edges/*/arrow=backward",
        "architecture.arrow-both": "/edges/*/arrow=both",
        "architecture.edge-group-modifier": "/edges/*/from_group=true",
        "architecture.align-row": "/alignments/*/axis=row",
        "architecture.align-column": "/alignments/*/axis=column",
        "architecture.icon-cloud": "/groups/*/icon=cloud",
        "architecture.icon-database": "/nodes/*/icon=database",
        "architecture.icon-disk": "/nodes/*/icon=disk",
        "architecture.icon-internet": "/nodes/*/icon=internet",
        "architecture.icon-server": "/nodes/*/icon=server",
        "architecture.icon-pack": "/nodes/*/icon=logos:aws-ec2",
        "architecture.acc-title": "/accessibility/title",
        "architecture.acc-descr": "/accessibility/description",
        "architecture.comment": "/comment",
    },
    probes={"object": "/nodes/1", "number": "/config/padding", "enum": "/edges/0/from_side", "ref": "/edges/0/from"},
))
register(Builder(
    "block", "graph", ("block", "block-beta"), _block_serialize,
    text_fields=("/blocks/*/label", "/blocks/*/children/*/label", "/edges/*/label", "/comment"),
    features={
        "block.keyword": "/target=block",
        "block.keyword-beta": "/target=block-beta",
        "block.block-plain": "/blocks/14/id=plain",
        "block.block-label": "/blocks/*/label",
        "block.columns": "/columns=4",
        "block.columns-auto": "/columns=auto",
        "block.width": "/blocks/*/width",
        "block.composite": "/blocks/26/children",
        "block.composite-id": "/blocks/*/kind=composite",
        "block.composite-width": "/blocks/24/width",
        "block.composite-columns": "/blocks/*/columns",
        "block.shape-rect": "/blocks/*/shape=rect",
        "block.shape-round": "/blocks/*/shape=round",
        "block.shape-stadium": "/blocks/*/shape=stadium",
        "block.shape-subroutine": "/blocks/*/shape=subroutine",
        "block.shape-cylinder": "/blocks/*/shape=cylinder",
        "block.shape-circle": "/blocks/*/shape=circle",
        "block.shape-asymmetric": "/blocks/*/shape=asymmetric",
        "block.shape-rhombus": "/blocks/*/shape=rhombus",
        "block.shape-hexagon": "/blocks/*/shape=hexagon",
        "block.shape-parallelogram": "/blocks/*/shape=parallelogram",
        "block.shape-parallelogram-alt": "/blocks/*/shape=parallelogram-alt",
        "block.shape-trapezoid": "/blocks/*/shape=trapezoid",
        "block.shape-trapezoid-alt": "/blocks/*/shape=trapezoid-alt",
        "block.shape-double-circle": "/blocks/*/shape=double-circle",
        "block.arrow-right": "/blocks/*/directions/0=right",
        "block.arrow-left": "/blocks/*/directions/0=left",
        "block.arrow-up": "/blocks/*/directions/0=up",
        "block.arrow-down": "/blocks/*/directions/0=down",
        "block.arrow-x": "/blocks/*/directions/0=x",
        "block.arrow-y": "/blocks/*/directions/0=y",
        "block.arrow-combined": "/blocks/*/directions/1",
        "block.space": "/blocks/*/kind=space",
        "block.space-width": "/blocks/25/width",
        "block.edge-arrow": "/edges/*/kind=arrow",
        "block.edge-line": "/edges/*/kind=line",
        "block.edge-text": "/edges/*/label",
        "block.edge-from-composite": "/edges/0/from=ID",
        "block.style": "/styles/*/style",
        "block.class-def": "/class_defs/*/style",
        "block.class": "/class_assignments/*/class",
        "block.html-entity": "/blocks/22/label=both\u00a0ways",
        "block.comment": "/comment",
    },
    probes={"object": "/blocks/15", "number": "/blocks/15/width", "enum": "/blocks/0/shape", "ref": "/edges/0/from"},
))
register(Builder(
    "packet", "packet", ("packet", "packet-beta"), _packet_serialize,
    text_fields=("/fields/*/label", "/title", "/comment", "/accessibility/title", "/accessibility/description"),
    features={
        "packet.keyword": "/target=packet",
        "packet.keyword-beta": "/target=packet-beta",
        "packet.field-range": "/fields/*/end",
        "packet.field-single-bit": "/fields/*/bit",
        "packet.field-bit-count": "/fields/*/bits",
        "packet.field-bit-count-single": "/fields/*/bits=1",
        "packet.mixed-notation": "/fields/1/start=16",
        "packet.row-wrap": "/fields/*/end=255",
        "packet.title": "/title",
        "packet.frontmatter-title": "/title_in_frontmatter=true",
        "packet.comment": "/comment",
        "packet.acc-title": "/accessibility/title",
        "packet.acc-descr": "/accessibility/description=Fields of a UDP header",
        "packet.acc-descr-block": "/accessibility/description=Fields of a TCP header,\nbit by bit.",
    },
    probes={"object": "/fields/1", "number": "/fields/1/end", "enum": None, "ref": None},
))
register(Builder(
    "requirementDiagram", "requirement-links", ("requirementDiagram",), _requirement_serialize,
    text_fields=(
        "/requirements/*/name", "/requirements/*/req_id", "/requirements/*/text",
        "/elements/*/name", "/elements/*/type", "/elements/*/docref",
        "/title", "/comment", "/accessibility/title", "/accessibility/description",
    ),
    features={
        "requirementDiagram.keyword": "/target=requirementDiagram",
        "requirementDiagram.type-requirement": "/requirements/0/id",
        "requirementDiagram.type-functional": "/requirements/*/type=functionalRequirement",
        "requirementDiagram.type-interface": "/requirements/*/type=interfaceRequirement",
        "requirementDiagram.type-performance": "/requirements/*/type=performanceRequirement",
        "requirementDiagram.type-physical": "/requirements/*/type=physicalRequirement",
        "requirementDiagram.type-design-constraint": "/requirements/*/type=designConstraint",
        "requirementDiagram.field-id": "/requirements/*/req_id",
        "requirementDiagram.field-text": "/requirements/*/text",
        "requirementDiagram.risk-low": "/requirements/*/risk=low",
        "requirementDiagram.risk-medium": "/requirements/*/risk=medium",
        "requirementDiagram.risk-high": "/requirements/*/risk=high",
        "requirementDiagram.verify-analysis": "/requirements/*/verify_method=analysis",
        "requirementDiagram.verify-inspection": "/requirements/*/verify_method=inspection",
        "requirementDiagram.verify-test": "/requirements/*/verify_method=test",
        "requirementDiagram.verify-demonstration": "/requirements/*/verify_method=demonstration",
        "requirementDiagram.element": "/elements/*/id",
        "requirementDiagram.element-type": "/elements/*/type",
        "requirementDiagram.element-docref": "/elements/*/docref",
        "requirementDiagram.quoted-text": "/elements/*/type=test suite",
        "requirementDiagram.markdown-text": "/requirements/*/markdown=true",
        "requirementDiagram.quoted-name": "/requirements/*/name",
        "requirementDiagram.rel-contains": "/links/*/kind=contains",
        "requirementDiagram.rel-copies": "/links/*/kind=copies",
        "requirementDiagram.rel-derives": "/links/*/kind=derives",
        "requirementDiagram.rel-satisfies": "/links/*/kind=satisfies",
        "requirementDiagram.rel-verifies": "/links/*/kind=verifies",
        "requirementDiagram.rel-refines": "/links/*/kind=refines",
        "requirementDiagram.rel-traces": "/links/*/kind=traces",
        "requirementDiagram.rel-reverse": "/links/*/reverse=true",
        "requirementDiagram.direction-tb": "/direction=TB",
        "requirementDiagram.direction-bt": "/direction=BT",
        "requirementDiagram.direction-lr": "/direction=LR",
        "requirementDiagram.direction-rl": "/direction=RL",
        "requirementDiagram.style": "/styles/*/style",
        "requirementDiagram.class-def": "/class_defs/*/name=important",
        "requirementDiagram.class-def-default": "/class_defs/*/name=default",
        "requirementDiagram.class": "/class_assignments/0/classes",
        "requirementDiagram.class-shorthand-definition": "/requirements/*/classes",
        "requirementDiagram.class-shorthand-statement": "/class_assignments/*/shorthand=true",
        "requirementDiagram.acc-title": "/accessibility/title",
        "requirementDiagram.acc-descr": "/accessibility/description=Left to right",
        "requirementDiagram.acc-descr-block": "/accessibility/description=Six requirement kinds, three elements,\nevery relationship.",
        "requirementDiagram.comment": "/comment",
    },
    probes={"object": "/requirements/0", "number": None, "enum": "/requirements/0/risk", "ref": "/links/0/from"},
))

# === end group 4 ===


# === group 5: Mermaid 12 and beta: agentflow, usecase, swimlanes, wardley, cynefin, eventmodeling ====

# --- shared group-5 helpers ------------------------------------------------------------------

_G5_DIRECTIONS = ("TB", "TD", "BT", "LR", "RL")


def _g5_list(v: Validator, obj: dict, path: str, key: str, min_items: int = 0) -> list:
    """`obj[key]` as an array, or `[]` when the optional key is absent."""
    if key not in obj:
        return []
    return v.array(obj[key], ptr(path, key), min_items)


text_context(
    "g5.color",
    reject_patterns=((r"^(?!#[0-9A-Fa-f]{3}$|#[0-9A-Fa-f]{6}$|#[0-9A-Fa-f]{8}$|[a-z]+$)", "must be #rgb, #rrggbb, #rrggbbaa or a lowercase CSS color name"),),
)
text_context("g5.length", reject_patterns=((r"^(?![0-9]+(\.[0-9]+)?px$)", "must be a length like 2px"),))
text_context("g5.dasharray", reject_patterns=((r"^(?![0-9]+( [0-9]+)*$)", "must be numbers separated by single spaces, like '5 5'"),))

# Typed style object -> CSS property list. Values never carry raw CSS.
_G5_STYLE_KEYS = {
    "fill": ("fill", "g5.color"),
    "stroke": ("stroke", "g5.color"),
    "color": ("color", "g5.color"),
    "strokeWidth": ("stroke-width", "g5.length"),
    "strokeDasharray": ("stroke-dasharray", "g5.dasharray"),
}


def _g5_style(v: Validator, value: Any, path: str) -> str:
    """`{fill, stroke, color, strokeWidth, strokeDasharray}` -> `fill:#f9f,stroke:#333`."""
    v.fields(value, path, optional=tuple(_G5_STYLE_KEYS))
    if not value:
        raise v.error(path, "must set at least one style property")
    parts = []
    for key, (css, context) in _G5_STYLE_KEYS.items():
        if key in value:
            parts.append(f"{css}:{v.text(value[key], ptr(path, key), context)}")
    return ",".join(parts)


# Canonical flowchart `@{ shape: ... }` names in Mermaid 12.0.0 (see catalog/flowchart.md).
_G5_FLOW_SHAPES = (
    "rect", "rounded", "stadium", "subproc", "cyl", "circle", "odd", "diamond", "hex", "lean-r",
    "lean-l", "datastore", "trap-b", "trap-t", "dbl-circ", "text", "notch-rect", "lin-rect",
    "sm-circ", "framed-circle", "fork", "hourglass", "comment", "brace-r", "braces", "bolt", "doc",
    "delay", "das", "lin-cyl", "curv-trap", "div-rect", "tri", "win-pane", "f-circ", "lin-doc",
    "notch-pent", "flip-tri", "sl-rect", "docs", "processes", "flag", "bow-rect", "cross-circ",
    "tag-doc", "tag-rect", "manual-file", "manual-input", "procs", "paper-tape",
)

# Ids for the flowchart-family lexers (agentflow, swimlanes): a bare word that is not a keyword.
_G5_FLOW_RESERVED = frozenset(
    {"end", "subgraph", "graph", "flowchart", "style", "linkStyle", "class", "classDef", "click",
     "call", "href", "direction", "default", "flow", "global", "connector", "agentflow", "swimlane",
     "accTitle", "accDescr", "interpolate"}
)
_G5_FLOW_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _g5_flow_id(v: Validator, value: Any, path: str) -> str:
    v.ident(value, path, _G5_FLOW_ID)
    if value in _G5_FLOW_RESERVED:
        raise v.error(path, f"{value!r} is a keyword and cannot be an id")
    return value


# --- cynefin -------------------------------------------------------------------------------

# Item badges, transition labels and the title all render Mermaid entity codes back.
text_context("cynefin.text", encode=ENTITY)

_CYNEFIN_DOMAINS = ("complex", "complicated", "clear", "chaotic", "confusion")
_CYNEFIN_CONFIG = {
    "width": ("number", 1, None),
    "height": ("number", 1, None),
    "padding": ("number", 0, None),
    "showDomainDescriptions": ("boolean",),
    "boundaryAmplitude": ("number", 0, None),
    "seed": ("integer", 0, None),
}


def _cynefin_serialize(ir: dict, keyword: str) -> str:
    v = Validator(keyword)
    v.fields(ir, "", ("domains",), ("title", "accessibility", "config", "transitions"))
    lines: list[str] = []
    if "config" in ir:
        config = validate_config(v, ir["config"], "/config", _CYNEFIN_CONFIG)
        if config:
            lines += emit_frontmatter(config={"cynefin": config})
    lines.append("cynefin-beta")
    if "title" in ir:
        lines.append(f"  title {v.text(ir['title'], '/title', 'cynefin.text')}")
    lines += emit_accessibility(v, ir, "  ")
    seen: set[str] = set()
    for i, entry in enumerate(v.array(ir["domains"], "/domains", 1)):
        path = ptr("/domains", i)
        v.fields(entry, path, ("domain",), ("items",))
        name = v.enum(entry["domain"], ptr(path, "domain"), _CYNEFIN_DOMAINS)
        v.unique(name, ptr(path, "domain"), seen, "domain")
        lines.append(f"  {name}")
        for j, item in enumerate(_g5_list(v, entry, path, "items")):
            lines.append(f'    "{v.text(item, ptr(ptr(path, "items"), j), "cynefin.text")}"')
    for i, transition in enumerate(_g5_list(v, ir, "", "transitions")):
        path = ptr("/transitions", i)
        v.fields(transition, path, ("from", "to"), ("label",))
        source = v.enum(transition["from"], ptr(path, "from"), _CYNEFIN_DOMAINS)
        target = v.enum(transition["to"], ptr(path, "to"), _CYNEFIN_DOMAINS)
        if source == target:
            raise v.error(ptr(path, "to"), "a self-transition is silently ignored by Mermaid; from and to must differ")
        label = ""
        if "label" in transition:
            label = f' : "{v.text(transition["label"], ptr(path, "label"), "cynefin.text")}"'
        lines.append(f"  {source} --> {target}{label}")
    return "\n".join(lines) + "\n"


register(Builder(
    "cynefin", "cynefin", ("cynefin-beta",), _cynefin_serialize,
    text_fields=(
        "/title", "/domains/*/items/*", "/transitions/*/label",
        "/accessibility/title", "/accessibility/description",
    ),
    features={
        "cynefin.keyword": "/target=cynefin-beta",
        "cynefin.title": "/title",
        "cynefin.domain-complex": "/domains/*/domain=complex",
        "cynefin.domain-complicated": "/domains/*/domain=complicated",
        "cynefin.domain-clear": "/domains/*/domain=clear",
        "cynefin.domain-chaotic": "/domains/*/domain=chaotic",
        "cynefin.domain-confusion": "/domains/*/domain=confusion",
        "cynefin.domain-empty": "/domains/*/items=[]",
        "cynefin.item": "/domains/*/items/*",
        "cynefin.transition": "/transitions/*/to",
        "cynefin.transition-label": "/transitions/*/label",
        "cynefin.acc-title": "/accessibility/title",
        "cynefin.acc-descr": "/accessibility/description",
    },
    probes={"object": "/domains/0", "number": "/config/seed", "enum": "/domains/0/domain", "ref": None},
))


# --- eventmodeling -------------------------------------------------------------------------

# Data values are shown as text in the frame box and render entity codes back.
text_context("eventmodeling.value", encode=ENTITY, allow_empty=True)

_EVENTMODELING_TYPES = ("ui", "pcr", "processor", "cmd", "command", "rmo", "readmodel", "evt", "event")
_EVENTMODELING_DATA_TYPES = ("json", "jsobj", "figma", "salt", "uri", "md", "html", "text")
_EVENTMODELING_FORMS = ("compact", "relaxed")
_EVENTMODELING_ENTITY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_EVENTMODELING_NUMBER = re.compile(r"[0-9]+")
_EVENTMODELING_RESERVED = frozenset({"tf", "rf", "timeframe", "resetframe", "data", *_EVENTMODELING_TYPES})


def _eventmodeling_data(v: Validator, fields: Any, path: str) -> list[str]:
    """`[{key, value, raw?}]` -> `key: 'text'` / `key: 12.5` / `key: string` (raw type name)."""
    out = []
    for i, item in enumerate(v.array(fields, path, 1)):
        at = ptr(path, i)
        v.fields(item, at, ("key", "value"), ("raw",))
        key = v.ident(item["key"], ptr(at, "key"))
        raw = v.boolean(item["raw"], ptr(at, "raw")) if "raw" in item else False
        value, value_at = item["value"], ptr(at, "value")
        if raw:
            text = v.ident(value, value_at)
        elif isinstance(value, str):
            text = f"'{v.text(value, value_at, 'eventmodeling.value')}'"
        else:
            text = v.number(value, value_at)
        out.append(f"{key}: {text}")
    return out


def _eventmodeling_entity(v: Validator, value: Any, path: str) -> str:
    v.ident(value, path, _EVENTMODELING_ENTITY)
    if value in _EVENTMODELING_RESERVED:
        raise v.error(path, f"{value!r} is a keyword and cannot be an entity name")
    return value


def _eventmodeling_serialize(ir: dict, keyword: str) -> str:
    v = Validator(keyword)
    v.fields(ir, "", ("timeframes",), ("dataBlocks",))
    frames = v.array(ir["timeframes"], "/timeframes", 1)
    blocks = _g5_list(v, ir, "", "dataBlocks")
    block_ids: set[str] = set()
    block_lines: list[str] = []
    for i, block in enumerate(blocks):
        path = ptr("/dataBlocks", i)
        v.fields(block, path, ("id", "fields"), ("dataType",))
        block_id = v.unique(v.ident(block["id"], ptr(path, "id")), ptr(path, "id"), block_ids)
        tag = ""
        if "dataType" in block:
            tag = f"`{v.enum(block['dataType'], ptr(path, 'dataType'), _EVENTMODELING_DATA_TYPES)}`"
        block_lines.append(f"data {block_id} {tag}{{")
        block_lines += [f"  {field}" for field in _eventmodeling_data(v, block["fields"], ptr(path, "fields"))]
        block_lines.append("}")
    numbers: set[str] = set()
    for i, frame in enumerate(frames):
        path = ptr("/timeframes", i)
        v.fields(frame, path, ("number", "type", "entity"),
                 ("reset", "form", "data", "dataType", "dataRef", "relations"))
        number = v.ident(frame["number"], ptr(path, "number"), _EVENTMODELING_NUMBER)
        v.unique(number, ptr(path, "number"), numbers, "frame number")
    lines = ["eventmodeling"]
    for i, frame in enumerate(frames):
        path = ptr("/timeframes", i)
        reset = v.boolean(frame["reset"], ptr(path, "reset")) if "reset" in frame else False
        form = v.enum(frame.get("form", "compact"), ptr(path, "form"), _EVENTMODELING_FORMS)
        word = {("compact", False): "tf", ("compact", True): "rf",
                ("relaxed", False): "timeframe", ("relaxed", True): "resetframe"}[(form, reset)]
        kind = v.enum(frame["type"], ptr(path, "type"), _EVENTMODELING_TYPES)
        entity = _eventmodeling_entity(v, frame["entity"], ptr(path, "entity"))
        line = f"{word} {frame['number']} {kind} {entity}"
        if "data" in frame and "dataRef" in frame:
            raise v.error(ptr(path, "dataRef"), "use either inline data or dataRef, not both")
        if "dataType" in frame and "data" not in frame:
            raise v.error(ptr(path, "dataType"), "dataType applies to inline data; set it on the data block instead")
        if "relations" in frame and ("data" in frame or "dataRef" in frame):
            raise v.error(ptr(path, "relations"), "relations cannot follow data or dataRef (Mermaid rejects it)")
        if "data" in frame:
            tag = ""
            if "dataType" in frame:
                tag = f"`{v.enum(frame['dataType'], ptr(path, 'dataType'), _EVENTMODELING_DATA_TYPES)}`"
            fields = _eventmodeling_data(v, frame["data"], ptr(path, "data"))
            line += f" {tag}{{ {', '.join(fields)} }}"
        if "dataRef" in frame:
            line += f" [[{v.ref(frame['dataRef'], ptr(path, 'dataRef'), block_ids)}]]"
        for j, target in enumerate(_g5_list(v, frame, path, "relations", 1)):
            line += f" ->> {v.ref(target, ptr(ptr(path, 'relations'), j), numbers)}"
        lines.append(line)
    return "\n".join(lines + block_lines) + "\n"


register(Builder(
    "eventmodeling", "eventmodeling", ("eventmodeling",), _eventmodeling_serialize,
    text_fields=("/timeframes/*/data/*/value", "/dataBlocks/*/fields/*/value"),
    features={
        "eventmodeling.keyword": "/target=eventmodeling",
        "eventmodeling.timeframe-compact": "/timeframes/*/form=compact",
        "eventmodeling.timeframe-relaxed": "/timeframes/*/form=relaxed",
        "eventmodeling.resetframe-compact": "/timeframes/*/reset=true",
        "eventmodeling.resetframe-relaxed": "/timeframes/*/reset=true",
        "eventmodeling.type-ui": "/timeframes/*/type=ui",
        "eventmodeling.type-pcr": "/timeframes/*/type=pcr",
        "eventmodeling.type-processor": "/timeframes/*/type=processor",
        "eventmodeling.type-cmd": "/timeframes/*/type=cmd",
        "eventmodeling.type-command": "/timeframes/*/type=command",
        "eventmodeling.type-rmo": "/timeframes/*/type=rmo",
        "eventmodeling.type-readmodel": "/timeframes/*/type=readmodel",
        "eventmodeling.type-evt": "/timeframes/*/type=evt",
        "eventmodeling.type-event": "/timeframes/*/type=event",
        "eventmodeling.entity-reuse": "/timeframes/*/entity=ItemAdded",
        "eventmodeling.namespace": "/timeframes/*/entity=External.InventoryChanged",
        "eventmodeling.inline-data": "/timeframes/*/data/*/key",
        "eventmodeling.data-ref": "/timeframes/*/dataRef",
        "eventmodeling.data-block": "/dataBlocks/*/fields/*/key",
        "eventmodeling.multiple-relations": "/timeframes/*/relations/1",
        "eventmodeling.data-type-json": "/timeframes/*/dataType=json",
        "eventmodeling.data-type-jsobj": "/timeframes/*/dataType=jsobj",
        "eventmodeling.data-type-figma": "/timeframes/*/dataType=figma",
        "eventmodeling.data-type-salt": "/timeframes/*/dataType=salt",
        "eventmodeling.data-type-uri": "/timeframes/*/dataType=uri",
        "eventmodeling.data-type-md": "/timeframes/*/dataType=md",
        "eventmodeling.data-type-html": "/timeframes/*/dataType=html",
        "eventmodeling.data-type-text": "/dataBlocks/*/dataType=text",
    },
    probes={
        "object": "/timeframes/1",
        "number": "/dataBlocks/0/fields/2/value",
        "enum": "/timeframes/0/type",
        "ref": "/timeframes/2/dataRef",
    },
))


# --- wardley -------------------------------------------------------------------------------

# Every wardley text is emitted in a quoted or line-final position that renders entity codes
# back; the flow label sits in single quotes, so `'` is encoded there too.
text_context("wardley.text", encode=ENTITY)
text_context("wardley.flow-label", encode={**ENTITY, "'": "#39;"})

_WARDLEY_SOURCING = ("build", "buy", "outsource", "market")
_WARDLEY_LINKS = {
    "dependency": "->",
    "dependencyAlt": "-->",
    "dashed": "-.->",
    "flow": "+>",
    "flowReverse": "+<",
    "flowBidirectional": "+<>",
}
_WARDLEY_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _wardley_coord(v: Validator, value: Any, path: str) -> str:
    """A 0..1 coordinate; Mermaid needs a leading digit and a decimal point (`1.0`, not `1`)."""
    text = v.number(value, path, 0, 1)
    return text if "." in text else f"{text}.0"


def _wardley_point(v: Validator, obj: dict, path: str) -> str:
    return f"[{_wardley_coord(v, obj['visibility'], ptr(path, 'visibility'))}, " \
           f"{_wardley_coord(v, obj['evolution'], ptr(path, 'evolution'))}]"


def _wardley_pair(v: Validator, value: Any, path: str, *, integer: bool, minimum: float | None) -> str:
    pair = v.array(value, path, 2)
    if len(pair) != 2:
        raise v.error(path, "must have exactly 2 items")
    return ", ".join(v.number(item, ptr(path, i), minimum, integer=integer) for i, item in enumerate(pair))


def _wardley_serialize(ir: dict, keyword: str) -> str:
    v = Validator(keyword)
    v.fields(ir, "", (), (
        "title", "accessibility", "comment", "size", "evolutionStages", "anchors", "components",
        "pipelines", "links", "evolve", "notes", "accelerators", "deaccelerators",
        "annotationsPosition", "annotations",
    ))
    lines = ["wardley-beta"]
    if "title" in ir:
        lines.append(f"title {v.text(ir['title'], '/title', 'wardley.text')}")
    lines += emit_accessibility(v, ir, "")
    if "size" in ir:
        lines.append(f"size [{_wardley_pair(v, ir['size'], '/size', integer=True, minimum=1)}]")
    stages = _g5_list(v, ir, "", "evolutionStages", 2)
    if stages:
        parts = []
        for i, stage in enumerate(stages):
            path = ptr("/evolutionStages", i)
            v.fields(stage, path, ("label",), ("dualLabel", "width"))
            part = f'"{v.text(stage["label"], ptr(path, "label"), "wardley.text")}"'
            if "dualLabel" in stage:
                if "width" in stage:
                    raise v.error(ptr(path, "width"), "a stage with a dualLabel cannot also set a width (Mermaid rejects it)")
                part += f' / "{v.text(stage["dualLabel"], ptr(path, "dualLabel"), "wardley.text")}"'
            if "width" in stage:
                part += f"@{_wardley_coord(v, stage['width'], ptr(path, 'width'))}"
            parts.append(part)
        lines.append("evolution " + " -> ".join(parts))
    lines += emit_comment(v, ir, "", "")
    names: dict[str, str] = {}  # IR id -> quoted, encoded Mermaid name
    shown: dict[str, str] = {}  # encoded name -> pointer of its declaration
    components: set[str] = set()

    def declare(item: dict, path: str) -> str:
        item_id = v.ident(item["id"], ptr(path, "id"), _WARDLEY_ID)
        if item_id in names:
            raise v.error(ptr(path, "id"), f"duplicate id {json.dumps(item_id)}")
        at = ptr(path, "label") if "label" in item else ptr(path, "id")
        name = f'"{v.text(item.get("label", item_id), at, "wardley.text")}"'
        if name in shown:
            raise v.error(at, f"name is already used at {shown[name]}; Mermaid would merge them")
        shown[name] = at
        names[item_id] = name
        return name

    for i, anchor in enumerate(_g5_list(v, ir, "", "anchors")):
        path = ptr("/anchors", i)
        v.fields(anchor, path, ("id", "visibility", "evolution"), ("label",))
        lines.append(f"anchor {declare(anchor, path)} {_wardley_point(v, anchor, path)}")
    for i, comp in enumerate(_g5_list(v, ir, "", "components")):
        path = ptr("/components", i)
        v.fields(comp, path, ("id", "visibility", "evolution"), ("label", "labelOffset", "sourcing", "inertia"))
        line = f"component {declare(comp, path)} {_wardley_point(v, comp, path)}"
        components.add(comp["id"])
        if "labelOffset" in comp:
            line += f" label [{_wardley_pair(v, comp['labelOffset'], ptr(path, 'labelOffset'), integer=False, minimum=None)}]"
        if "sourcing" in comp:
            line += f" ({v.enum(comp['sourcing'], ptr(path, 'sourcing'), _WARDLEY_SOURCING)})"
        if "inertia" in comp and v.boolean(comp["inertia"], ptr(path, "inertia")):
            line += " (inertia)"
        lines.append(line)
    for i, pipeline in enumerate(_g5_list(v, ir, "", "pipelines")):
        path = ptr("/pipelines", i)
        v.fields(pipeline, path, ("parent", "stages"))
        parent = v.ref(pipeline["parent"], ptr(path, "parent"), components)
        lines.append(f"pipeline {names[parent]} {{")
        for j, stage in enumerate(v.array(pipeline["stages"], ptr(path, "stages"), 1)):
            at = ptr(ptr(path, "stages"), j)
            v.fields(stage, at, ("label", "evolution"))
            name = f'"{v.text(stage["label"], ptr(at, "label"), "wardley.text")}"'
            if name in shown:
                raise v.error(ptr(at, "label"), f"name is already used at {shown[name]}; Mermaid would merge them")
            shown[name] = ptr(at, "label")
            lines.append(f"  component {name} [{_wardley_coord(v, stage['evolution'], ptr(at, 'evolution'))}]")
        lines.append("}")
    for i, link in enumerate(_g5_list(v, ir, "", "links")):
        path = ptr("/links", i)
        v.fields(link, path, ("from", "to"), ("kind", "label"))
        source = names[v.ref(link["from"], ptr(path, "from"), names)]
        target = names[v.ref(link["to"], ptr(path, "to"), names)]
        kind = v.enum(link.get("kind", "dependency"), ptr(path, "kind"), _WARDLEY_LINKS)
        if "label" not in link:
            lines.append(f"{source} {kind} {target}")
        elif link.get("kind", "dependency") == "flow":
            label = v.text(link["label"], ptr(path, "label"), "wardley.flow-label")
            lines.append(f"{source} +'{label}'> {target}")
        elif link.get("kind", "dependency") in ("dependency", "dependencyAlt", "dashed"):
            lines.append(f"{source} {kind} {target}; {v.text(link['label'], ptr(path, 'label'), 'wardley.text')}")
        else:
            raise v.error(ptr(path, "label"), "only dependency and flow links take a label")
    for i, evolve in enumerate(_g5_list(v, ir, "", "evolve")):
        path = ptr("/evolve", i)
        v.fields(evolve, path, ("id", "target"))
        name = names[v.ref(evolve["id"], ptr(path, "id"), components)]
        lines.append(f"evolve {name} {_wardley_coord(v, evolve['target'], ptr(path, 'target'))}")
    for key in ("accelerators", "deaccelerators"):
        for i, force in enumerate(_g5_list(v, ir, "", key)):
            path = ptr(f"/{key}", i)
            v.fields(force, path, ("text", "visibility", "evolution"))
            text = v.text(force["text"], ptr(path, "text"), "wardley.text")
            lines.append(f'{key[:-1]} "{text}" {_wardley_point(v, force, path)}')
    if "annotationsPosition" in ir:
        v.fields(ir["annotationsPosition"], "/annotationsPosition", ("visibility", "evolution"))
        lines.append(f"annotations {_wardley_point(v, ir['annotationsPosition'], '/annotationsPosition')}")
    numbers: set[str] = set()
    for i, note in enumerate(_g5_list(v, ir, "", "annotations")):
        path = ptr("/annotations", i)
        v.fields(note, path, ("number", "visibility", "evolution", "text"))
        number = v.number(note["number"], ptr(path, "number"), 1, integer=True)
        v.unique(number, ptr(path, "number"), numbers, "annotation number")
        text = v.text(note["text"], ptr(path, "text"), "wardley.text")
        lines.append(f'annotation {number},{_wardley_point(v, note, path)} "{text}"')
    for i, note in enumerate(_g5_list(v, ir, "", "notes")):
        path = ptr("/notes", i)
        v.fields(note, path, ("text", "visibility", "evolution"))
        text = v.text(note["text"], ptr(path, "text"), "wardley.text")
        lines.append(f'note "{text}" {_wardley_point(v, note, path)}')
    if not names:
        raise v.error("", "a map needs at least one anchor or component")
    return "\n".join(lines) + "\n"


register(Builder(
    "wardley", "graph", ("wardley-beta",), _wardley_serialize,
    text_fields=(
        "/title", "/comment", "/evolutionStages/*/label", "/evolutionStages/*/dualLabel",
        "/anchors/*/label", "/components/*/label", "/pipelines/*/stages/*/label",
        "/links/*/label", "/notes/*/text", "/annotations/*/text", "/accelerators/*/text",
        "/deaccelerators/*/text", "/accessibility/title", "/accessibility/description",
    ),
    features={
        "wardley.keyword": "/target=wardley-beta",
        "wardley.title": "/title",
        "wardley.size": "/size/1",
        "wardley.component": "/components/*/visibility",
        "wardley.component-quoted": "/components/*/label",
        "wardley.component-hyphen": "/components/*/label=real-time cache",
        "wardley.component-label-offset": "/components/*/labelOffset/1",
        "wardley.anchor": "/anchors/*/visibility",
        "wardley.inertia": "/components/*/inertia=true",
        "wardley.source-build": "/components/*/sourcing=build",
        "wardley.source-buy": "/components/*/sourcing=buy",
        "wardley.source-outsource": "/components/*/sourcing=outsource",
        "wardley.source-market": "/components/*/sourcing=market",
        "wardley.link": "/links/*/from",
        "wardley.link-alt": "/links/*/kind=dependencyAlt",
        "wardley.link-annotation": "/links/*/label",
        "wardley.link-dashed": "/links/*/kind=dashed",
        "wardley.flow": "/links/*/kind=flow",
        "wardley.flow-reverse": "/links/*/kind=flowReverse",
        "wardley.flow-bidirectional": "/links/*/kind=flowBidirectional",
        "wardley.flow-labeled": "/links/*/kind=flow",
        "wardley.evolve": "/evolve/*/target",
        "wardley.pipeline": "/pipelines/*/parent",
        "wardley.pipeline-component": "/pipelines/*/stages/*/evolution",
        "wardley.evolution-stages": "/evolutionStages/*/label",
        "wardley.evolution-dual-labels": "/evolutionStages/*/dualLabel",
        "wardley.evolution-widths": "/evolutionStages/*/width",
        "wardley.note": "/notes/*/text",
        "wardley.annotations": "/annotationsPosition/visibility",
        "wardley.annotation": "/annotations/*/number",
        "wardley.accelerator": "/accelerators/*/text",
        "wardley.deaccelerator": "/deaccelerators/*/text",
        "wardley.comment": "/comment",
    },
    probes={
        "object": "/components/0",
        "number": "/components/0/visibility",
        "enum": "/components/0/sourcing",
        "ref": "/links/0/to",
    },
))


# --- swimlanes -----------------------------------------------------------------------------

# Labels sit in double quotes (node brackets, `@{ label }`, lane titles, `|edge|` text) and
# render entity codes back. Markdown labels sit in "`...`"; `*` and `_` stay Markdown.
text_context("swimlanes.label", encode=ENTITY)

_SWIMLANES_KINDS = {
    "rect": ('["', '"]'),
    "round": ('("', '")'),
    "stadium": ('(["', '"])'),
    "decision": ('{"', '"}'),
    "circle": ('(("', '"))'),
}
_SWIMLANES_EDGES = {"arrow": "-->", "line": "---", "dotted": "-.->", "thick": "==>"}


def _swimlanes_hop(v: Validator, hop: dict, path: str, known: set[str]) -> str:
    """` --> target` / ` -->|"label"| target` for one edge or chain hop."""
    arrow = v.enum(hop.get("kind", "arrow"), ptr(path, "kind"), _SWIMLANES_EDGES)
    label = ""
    if "label" in hop:
        label = f'|"{v.text(hop["label"], ptr(path, "label"), "swimlanes.label")}"|'
    return f" {arrow}{label} {v.ref(hop['to'], ptr(path, 'to'), known)}"


def _swimlanes_serialize(ir: dict, keyword: str) -> str:
    v = Validator(keyword)
    v.fields(ir, "", ("nodes",), ("direction", "accessibility", "comment", "groups", "edges", "classDefs"))
    header = "swimlane-beta"
    if "direction" in ir:
        header += f" {v.enum(ir['direction'], '/direction', _G5_DIRECTIONS)}"
    lines = [header, *emit_accessibility(v, ir, "  "), *emit_comment(v, ir, "", "  ")]
    ids: set[str] = set()
    class_names: set[str] = set()
    class_lines: list[str] = []
    for i, cdef in enumerate(_g5_list(v, ir, "", "classDefs")):
        path = ptr("/classDefs", i)
        v.fields(cdef, path, ("name", "style"))
        name = v.unique(v.ident(cdef["name"], ptr(path, "name")), ptr(path, "name"), class_names, "class name")
        class_lines.append(f"  classDef {name} {_g5_style(v, cdef['style'], ptr(path, 'style'))};")
    groups = _g5_list(v, ir, "", "groups")
    group_ids: set[str] = set()
    for i, group in enumerate(groups):
        path = ptr("/groups", i)
        v.fields(group, path, ("id",), ("label",))
        v.unique(_g5_flow_id(v, group["id"], ptr(path, "id")), ptr(path, "id"), ids)
        group_ids.add(group["id"])
    members: dict[str | None, list[str]] = {}
    assignments: list[str] = []
    for i, node in enumerate(v.array(ir["nodes"], "/nodes", 1)):
        path = ptr("/nodes", i)
        v.fields(node, path, ("id",), ("label", "markdown", "kind", "shape", "group", "class"))
        node_id = v.unique(_g5_flow_id(v, node["id"], ptr(path, "id")), ptr(path, "id"), ids)
        if ("label" in node) == ("markdown" in node):
            raise v.error(ptr(path, "label"), "set exactly one of label or markdown")
        if "kind" in node and "shape" in node:
            raise v.error(ptr(path, "shape"), "set either kind or shape, not both")
        if "label" in node:
            text = v.text(node["label"], ptr(path, "label"), "swimlanes.label")
        else:
            text = f"`{v.text(node['markdown'], ptr(path, 'markdown'), 'swimlanes.label')}`"
        if "shape" in node:
            if "markdown" in node:
                raise v.error(ptr(path, "markdown"), "a shape node takes a plain label")
            shape = v.enum(node["shape"], ptr(path, "shape"), _G5_FLOW_SHAPES)
            decl = f'{node_id}@{{ shape: {shape}, label: "{text}" }}'
        else:
            left, right = v.enum(node.get("kind", "rect"), ptr(path, "kind"), _SWIMLANES_KINDS)
            decl = f"{node_id}{left}{text}{right}"
        group = v.ref(node["group"], ptr(path, "group"), group_ids) if "group" in node else None
        members.setdefault(group, []).append(decl)
        if "class" in node:
            assignments.append(f"  class {node_id} {v.ref(node['class'], ptr(path, 'class'), class_names)};")
    nodes = ids - group_ids
    for i, group in enumerate(groups):
        path = ptr("/groups", i)
        title = ""
        if "label" in group:
            title = f' ["{v.text(group["label"], ptr(path, "label"), "swimlanes.label")}"]'
        lines.append(f"  subgraph {group['id']}{title}")
        lines += [f"    {decl}" for decl in members.get(group["id"], [])]
        lines.append("  end")
    lines += [f"  {decl}" for decl in members.get(None, [])]
    for i, edge in enumerate(_g5_list(v, ir, "", "edges")):
        path = ptr("/edges", i)
        v.fields(edge, path, ("from", "to"), ("kind", "label", "then"))
        line = f"  {v.ref(edge['from'], ptr(path, 'from'), nodes)}{_swimlanes_hop(v, edge, path, nodes)}"
        for j, hop in enumerate(_g5_list(v, edge, path, "then", 1)):
            at = ptr(ptr(path, "then"), j)
            v.fields(hop, at, ("to",), ("kind", "label"))
            line += _swimlanes_hop(v, hop, at, nodes)
        lines.append(line)
    return "\n".join(lines + class_lines + assignments) + "\n"


register(Builder(
    "swimlanes", "graph", ("swimlane-beta",), _swimlanes_serialize,
    text_fields=(
        "/groups/*/label", "/nodes/*/label", "/nodes/*/markdown", "/edges/*/label",
        "/edges/*/then/*/label", "/comment", "/accessibility/title", "/accessibility/description",
    ),
    features={
        "swimlanes.keyword": "/target=swimlane-beta",
        "swimlanes.direction-tb": "/direction=TB",
        "swimlanes.direction-td": "/direction=TD",
        "swimlanes.direction-bt": "/direction=BT",
        "swimlanes.direction-lr": "/direction=LR",
        "swimlanes.direction-rl": "/direction=RL",
        "swimlanes.lane": "/groups/*/id",
        "swimlanes.lane-id-label": "/groups/*/label",
        "swimlanes.node-rect": "/nodes/*/kind=rect",
        "swimlanes.node-rounded": "/nodes/*/kind=round",
        "swimlanes.node-stadium": "/nodes/*/kind=stadium",
        "swimlanes.node-decision": "/nodes/*/kind=decision",
        "swimlanes.node-circle": "/nodes/*/kind=circle",
        "swimlanes.node-shape-metadata": "/nodes/*/shape",
        "swimlanes.markdown-string": "/nodes/*/markdown",
        "swimlanes.edge-arrow": "/edges/*/kind=arrow",
        "swimlanes.edge-line": "/edges/*/kind=line",
        "swimlanes.edge-label": "/edges/*/label",
        "swimlanes.edge-dotted": "/edges/*/kind=dotted",
        "swimlanes.edge-thick": "/edges/*/kind=thick",
        "swimlanes.edge-chain": "/edges/*/then/*/to",
        "swimlanes.edge-cross-lane": "/edges/*/to=triage",
        "swimlanes.classdef": "/classDefs/*/style/fill",
        "swimlanes.class": "/nodes/*/class",
        "swimlanes.acc-title": "/accessibility/title",
        "swimlanes.acc-descr": "/accessibility/description",
    },
    probes={"object": "/nodes/0", "number": None, "enum": "/nodes/0/kind", "ref": "/edges/0/to"},
))


# --- agentflow -----------------------------------------------------------------------------

# Displayed labels (node brackets, `@{ label }`, flow and connector titles, `|edge|` text)
# render entity codes back. Metadata values are not displayed, so an entity code there could
# not be checked: they are emitted verbatim inside YAML double quotes, and characters that
# YAML or Mermaid's entity pass would change are rejected.
text_context("agentflow.label", encode=ENTITY)
text_context(
    "agentflow.meta",
    reject='"\\',
    reject_patterns=((r"#\w+;", "an entity-like '#name;' would be decoded by Mermaid"),),
)
text_context("agentflow.title")

_AGENTFLOW_ALIASES = ("task", "tool", "input", "decision", "refdoc", "action")
_AGENTFLOW_SHAPES = _AGENTFLOW_ALIASES + _G5_FLOW_SHAPES
_AGENTFLOW_EDGES = {"sequence": "-->", "reference": "-.-", "failure": "--x"}
_AGENTFLOW_CURVES = ("basis", "bumpX", "bumpY", "cardinal", "catmullRom", "linear", "monotoneX",
                     "monotoneY", "natural", "step", "stepAfter", "stepBefore")
_AGENTFLOW_ALGORITHMS = ("elk.layered", "elk.rectpacking", "elk.force", "elk.mrtree", "elk.stress",
                         "elk.radial", "elk.box", "elk.disco", "elk.sporeOverlap", "elk.sporeCompaction")
_AGENTFLOW_META = ("description", "instruction", "model", "params", "returns")
_AGENTFLOW_NODE_META = _AGENTFLOW_META + ("value", "example", "connectorRef")
_AGENTFLOW_RESERVED_META = frozenset(
    {"shape", "label", "labelType", "view", "algorithm", "curve", "animate", "animation", "protocol",
     "endpoint", "class", "style", "icon", "img", "w", "h", "__proto__", "constructor", "prototype",
     *_AGENTFLOW_NODE_META}
)
_AGENTFLOW_CONFIG = {
    "titleTopMargin": ("number", 0, None),
    "diagramPadding": ("number", 0, None),
    "nodeSpacing": ("number", 0, None),
    "rankSpacing": ("number", 0, None),
    "useMaxWidth": ("boolean",),
}


def _agentflow_meta(v: Validator, obj: dict, path: str, keys: tuple[str, ...]) -> list[str]:
    """Typed metadata keys plus `custom: {key: string | number | boolean}` -> YAML pairs."""
    pairs = []
    for key in keys:
        if key in obj:
            pairs.append(f'{key}: "{v.text(obj[key], ptr(path, key), "agentflow.meta")}"')
    if "custom" in obj:
        at = ptr(path, "custom")
        custom = v.obj_map(obj["custom"], at)
        if not custom:
            raise v.error(at, "must have at least one key")
        for key, value in custom.items():
            key_at = ptr(at, key)
            if not isinstance(key, str) or not _IDENT.fullmatch(key):
                raise v.error(key_at, "custom metadata keys must be identifiers")
            if key in _AGENTFLOW_RESERVED_META:
                raise v.error(key_at, f"{key!r} is a reserved metadata key; use the typed field")
            if isinstance(value, bool):
                text = "true" if value else "false"
            elif isinstance(value, str):
                text = f'"{v.text(value, key_at, "agentflow.meta")}"'
            else:
                text = v.number(value, key_at)
            pairs.append(f"{key}: {text}")
    return pairs


def _agentflow_hop(v: Validator, hop: dict, path: str, known: set[str], edge_id: str = "") -> str:
    arrow = v.enum(hop.get("kind", "sequence"), ptr(path, "kind"), _AGENTFLOW_EDGES)
    label = ""
    if "label" in hop:
        label = f'|"{v.text(hop["label"], ptr(path, "label"), "agentflow.label")}"|'
    prefix = f"{edge_id}@" if edge_id else ""
    return f" {prefix}{arrow}{label} {v.ref(hop['to'], ptr(path, 'to'), known)}"


def _agentflow_serialize(ir: dict, keyword: str) -> str:
    v = Validator(keyword)
    v.fields(ir, "", ("nodes",), (
        "direction", "title", "config", "accessibility", "connectors", "flows", "edges",
    ))
    config = validate_config(v, ir["config"], "/config", _AGENTFLOW_CONFIG) if "config" in ir else {}
    title = v.text(ir["title"], "/title", "agentflow.title") if "title" in ir else None
    lines = emit_frontmatter(title, {"agentflow": config} if config else None)
    header = "agentflow-beta"
    if "direction" in ir:
        header += f" {v.enum(ir['direction'], '/direction', _G5_DIRECTIONS)}"
    lines += [header, *emit_accessibility(v, ir, "  ")]
    ids: set[str] = set()

    for i, conn in enumerate(_g5_list(v, ir, "", "connectors")):
        path = ptr("/connectors", i)
        v.fields(conn, path, ("id", "label"), ("protocol", "endpoint", "description", "custom"))
        conn_id = v.unique(_g5_flow_id(v, conn["id"], ptr(path, "id")), ptr(path, "id"), ids)
        lines.append(f'  connector {conn_id}["{v.text(conn["label"], ptr(path, "label"), "agentflow.label")}"]')
        meta = _agentflow_meta(v, conn, path, ("protocol", "endpoint", "description"))
        if meta:
            lines.append(f"  {conn_id}@{{ {', '.join(meta)} }}")

    flows = _g5_list(v, ir, "", "flows")
    flow_ids: set[str] = set()
    for i, flow in enumerate(flows):
        path = ptr("/flows", i)
        v.fields(flow, path, ("id", "label"), ("parent", "view", "algorithm", "custom", *_AGENTFLOW_META))
        flow_ids.add(v.unique(_g5_flow_id(v, flow["id"], ptr(path, "id")), ptr(path, "id"), ids))
    children: dict[str | None, list[int]] = {}
    for i, flow in enumerate(flows):
        path = ptr("/flows", i)
        parent = v.ref(flow["parent"], ptr(path, "parent"), flow_ids) if "parent" in flow else None
        children.setdefault(parent, []).append(i)

    nodes = v.array(ir["nodes"], "/nodes", 1)
    node_ids: set[str] = set()
    in_flow: dict[str | None, list[list[str]]] = {}
    global_nodes: list[list[str]] = []
    for i, node in enumerate(nodes):
        path = ptr("/nodes", i)
        v.fields(node, path, ("id",), (
            "label", "metaLabel", "labelType", "shape", "flow", "global", "metadataBlock", "custom",
            *_AGENTFLOW_NODE_META,
        ))
        node_id = v.unique(_g5_flow_id(v, node["id"], ptr(path, "id")), ptr(path, "id"), ids)
        node_ids.add(node_id)
        if ("label" in node) == ("metaLabel" in node):
            raise v.error(ptr(path, "label"), "set exactly one of label (bracket) or metaLabel (metadata)")
        meta = []
        if "shape" in node:
            meta.append(f"shape: {v.enum(node['shape'], ptr(path, 'shape'), _AGENTFLOW_SHAPES)}")
        if "metaLabel" in node:
            meta.append(f'label: "{v.text(node["metaLabel"], ptr(path, "metaLabel"), "agentflow.label")}"')
        if "labelType" in node:
            if "metaLabel" not in node:
                raise v.error(ptr(path, "labelType"), "labelType applies to metaLabel")
            meta.append(f"labelType: {v.enum(node['labelType'], ptr(path, 'labelType'), ('markdown', 'string'))}")
        meta += _agentflow_meta(v, node, path, _AGENTFLOW_NODE_META)
        block = v.boolean(node["metadataBlock"], ptr(path, "metadataBlock")) if "metadataBlock" in node else False
        if block and not meta:
            raise v.error(ptr(path, "metadataBlock"), "the node has no metadata to put in a block")
        decl = node_id
        if "label" in node:
            decl += f'["{v.text(node["label"], ptr(path, "label"), "agentflow.label")}"]'
        if block:
            stmt = [decl, f"{node_id}@{{", *[f"  {pair}" for pair in meta], "}"] if "label" in node else \
                [f"{node_id}@{{", *[f"  {pair}" for pair in meta], "}"]
        else:
            stmt = [f"{decl}@{{ {', '.join(meta)} }}" if meta else decl]
        is_global = v.boolean(node["global"], ptr(path, "global")) if "global" in node else False
        if is_global:
            if "flow" in node:
                raise v.error(ptr(path, "global"), "a global node cannot also belong to a flow")
            global_nodes.append(stmt)
        else:
            flow = v.ref(node["flow"], ptr(path, "flow"), flow_ids) if "flow" in node else None
            in_flow.setdefault(flow, []).append(stmt)

    if global_nodes:
        lines.append("  global")
        lines += [f"    {line}" for stmt in global_nodes for line in stmt]
        lines.append("  end")

    emitted: set[int] = set()

    def emit_flow(index: int, indent: str) -> None:
        emitted.add(index)
        flow, path = flows[index], ptr("/flows", index)
        lines.append(f'{indent}flow {flow["id"]}["{v.text(flow["label"], ptr(path, "label"), "agentflow.label")}"]')
        lines.extend(f"{indent}  {line}" for stmt in in_flow.get(flow["id"], []) for line in stmt)
        for child in children.get(flow["id"], []):
            emit_flow(child, indent + "  ")
        lines.append(f"{indent}end")
        meta = []
        if "view" in flow:
            meta.append(f'view: "{v.enum(flow["view"], ptr(path, "view"), ("collapsed",))}"')
        if "algorithm" in flow:
            meta.append(f'algorithm: "{v.enum(flow["algorithm"], ptr(path, "algorithm"), _AGENTFLOW_ALGORITHMS)}"')
        meta += _agentflow_meta(v, flow, path, _AGENTFLOW_META)
        if meta:
            lines.append(f"{indent}{flow['id']}@{{ {', '.join(meta)} }}")

    for index in children.get(None, []):
        emit_flow(index, "  ")
    for index, flow in enumerate(flows):
        if index not in emitted:
            raise v.error(ptr(ptr("/flows", index), "parent"), "flow parents form a cycle")
    lines += [f"  {line}" for stmt in in_flow.get(None, []) for line in stmt]

    endpoints = node_ids | flow_ids
    edge_meta: list[str] = []
    for i, edge in enumerate(_g5_list(v, ir, "", "edges")):
        path = ptr("/edges", i)
        v.fields(edge, path, ("from", "to"), ("kind", "label", "id", "curve", "animate", "animation", "then"))
        edge_id = ""
        meta = []
        if "id" in edge:
            edge_id = v.unique(_g5_flow_id(v, edge["id"], ptr(path, "id")), ptr(path, "id"), ids)
            if "curve" in edge:
                meta.append(f"curve: {v.enum(edge['curve'], ptr(path, 'curve'), _AGENTFLOW_CURVES)}")
            if "animate" in edge:
                meta.append(f"animate: {'true' if v.boolean(edge['animate'], ptr(path, 'animate')) else 'false'}")
            if "animation" in edge:
                meta.append(f"animation: {v.enum(edge['animation'], ptr(path, 'animation'), ('fast', 'slow'))}")
        else:
            for key in ("curve", "animate", "animation"):
                if key in edge:
                    raise v.error(ptr(path, key), "edge metadata needs an edge id")
        line = f"  {v.ref(edge['from'], ptr(path, 'from'), endpoints)}{_agentflow_hop(v, edge, path, endpoints, edge_id)}"
        for j, hop in enumerate(_g5_list(v, edge, path, "then", 1)):
            at = ptr(ptr(path, "then"), j)
            v.fields(hop, at, ("to",), ("kind", "label"))
            line += _agentflow_hop(v, hop, at, endpoints)
        lines.append(line)
        if meta:
            edge_meta.append(f"  {edge_id}@{{ {', '.join(meta)} }}")
    return "\n".join(lines + edge_meta) + "\n"


register(Builder(
    "agentflow", "graph", ("agentflow-beta",), _agentflow_serialize,
    text_fields=(
        "/title", "/accessibility/title", "/accessibility/description",
        "/nodes/*/label", "/nodes/*/metaLabel", "/flows/*/label", "/connectors/*/label",
        "/edges/*/label", "/edges/*/then/*/label",
        "/nodes/*/description", "/nodes/*/instruction", "/nodes/*/model", "/nodes/*/params",
        "/nodes/*/returns", "/nodes/*/value", "/nodes/*/example", "/nodes/*/connectorRef",
        "/nodes/*/custom/*", "/flows/*/description", "/flows/*/instruction", "/flows/*/model",
        "/flows/*/params", "/flows/*/returns", "/flows/*/custom/*", "/connectors/*/protocol",
        "/connectors/*/endpoint", "/connectors/*/description", "/connectors/*/custom/*",
    ),
    features={
        "agentflow.keyword": "/target=agentflow-beta",
        "agentflow.direction-tb": "/direction=TB",
        "agentflow.direction-td": "/direction=TD",
        "agentflow.direction-bt": "/direction=BT",
        "agentflow.direction-lr": "/direction=LR",
        "agentflow.direction-rl": "/direction=RL",
        "agentflow.node": "/nodes/*/label",
        "agentflow.shape-task": "/nodes/*/shape=task",
        "agentflow.shape-tool": "/nodes/*/shape=tool",
        "agentflow.shape-input": "/nodes/*/shape=input",
        "agentflow.shape-decision": "/nodes/*/shape=decision",
        "agentflow.shape-refdoc": "/nodes/*/shape=refdoc",
        "agentflow.shape-action": "/nodes/*/shape=action",
        "agentflow.shape-canonical": "/nodes/*/shape=rounded",
        "agentflow.edge-sequence": "/edges/*/kind=sequence",
        "agentflow.edge-reference": "/edges/*/kind=reference",
        "agentflow.edge-failure": "/edges/*/kind=failure",
        "agentflow.edge-label": "/edges/*/label",
        "agentflow.edge-chain": "/edges/*/then/*/to",
        "agentflow.flow": "/flows/*/label",
        "agentflow.flow-nested": "/flows/*/parent",
        "agentflow.flow-endpoint": "/edges/*/to=publisher",
        "agentflow.global": "/nodes/*/global=true",
        "agentflow.view-collapsed": "/flows/*/view=collapsed",
        "agentflow.algorithm": "/flows/*/algorithm",
        "agentflow.metadata-inline": "/flows/*/model",
        "agentflow.metadata-block": "/nodes/*/metadataBlock=true",
        "agentflow.meta-label": "/nodes/*/metaLabel",
        "agentflow.meta-label-type": "/nodes/*/labelType",
        "agentflow.edge-curve": "/edges/*/curve",
        "agentflow.edge-animate": "/edges/*/animate",
        "agentflow.edge-animation": "/edges/*/animation",
        "agentflow.meta-description": "/nodes/*/description",
        "agentflow.meta-instruction": "/flows/*/instruction",
        "agentflow.meta-model": "/flows/*/model",
        "agentflow.meta-params": "/nodes/*/params",
        "agentflow.meta-returns": "/nodes/*/returns",
        "agentflow.meta-value": "/nodes/*/value",
        "agentflow.meta-example": "/nodes/*/example",
        "agentflow.meta-connector-ref": "/nodes/*/connectorRef",
        "agentflow.meta-custom": "/nodes/*/custom/*",
        "agentflow.connector": "/connectors/*/label",
        "agentflow.connector-metadata": "/connectors/*/protocol",
    },
    probes={"object": "/nodes/0", "number": "/config/nodeSpacing", "enum": "/nodes/0/shape", "ref": "/edges/0/to"},
))


# --- usecase -------------------------------------------------------------------------------

# Labels, stereotypes, notes, edge labels, boundary titles and JSON strings all sit in double
# quotes (or `<<...>>`) and render entity codes back. Markdown labels sit in "`...`".
text_context("usecase.text", encode=ENTITY)
text_context("usecase.title")
# A Markdown label may span lines (a real newline inside the backticks).
text_context("usecase.markdown", encode=ENTITY, allow_newline=True, reject_patterns=((r"\r", "use \\n line breaks"),))
# The quoted declaration form derives the id from the text, so only words and spaces fit.
text_context("usecase.quoted-form", reject_patterns=((r"[^A-Za-z0-9_ ]", "a quoted declaration takes only letters, digits, '_' and spaces"),))

_USECASE_ID = re.compile(r"[A-Za-z0-9_]+")
_USECASE_RESERVED = frozenset({
    "end", "note", "actor", "style", "json", "class", "classDef", "direction", "systemBoundary",
    "for", "include", "extend", "true", "false", "TB", "TD", "BT", "LR", "RL",
})
_USECASE_ACTOR_TYPES = ("normal", "hollow", "awesome")
_USECASE_SHAPES = {"ellipse": ('("', '")'), "rect": ('["', '"]')}
_USECASE_FORMS = ("declared", "quoted")
_USECASE_BOUNDARY_TYPES = ("rect", "package")
_USECASE_EDGES = {
    # kind: (unlabelled arrow, labelled (left, right) or None, takes extra length)
    "association": ("-->", ("--", "-->"), True),
    "reverseAssociation": ("<--", ("<--", "--"), True),
    "line": ("--", ("--", "--"), True),
    "circle": ("--o", ("--", "--o"), False),
    "reverseCircle": ("o--", None, False),
    "cross": ("--x", ("--", "--x"), False),
    "reverseCross": ("x--", None, False),
    "include": ("..> : include", None, False),
    "extend": ("..> : extend", None, False),
    "generalization": ("--|>", None, False),
}
_USECASE_CONFIG = {
    "actorFontSize": ("number", 1, None),
    "usecaseFontSize": ("number", 1, None),
    "actorFontWeight": ("enum", ("normal", "bold", "lighter", "bolder")),
    "usecaseFontWeight": ("enum", ("normal", "bold", "lighter", "bolder")),
    "nodeSpacing": ("number", 0, None),
    "rankSpacing": ("number", 0, None),
    "diagramPadding": ("number", 0, None),
    "colorScheme": ("enum", ("role", "rotate")),
    "useMaxWidth": ("boolean",),
}
text_context("usecase.icon", reject_patterns=((r"^(?![a-z0-9-]+:[a-z0-9-]+$)", "must look like pack:name"),))


def _usecase_id(v: Validator, value: Any, path: str) -> str:
    v.ident(value, path, _USECASE_ID)
    if value in _USECASE_RESERVED or value.lower() == "package":
        raise v.error(path, f"{value!r} is a keyword and cannot be an id")
    return value


def _usecase_json(v: Validator, value: Any, path: str) -> str:
    """A JSON value with every string (keys too) entity-encoded."""
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            at = ptr(path, key)
            if not isinstance(key, str) or not key:
                raise v.error(at, "JSON keys must be non-empty strings")
            parts.append(f'"{v.text(key, at, "usecase.text")}": {_usecase_json(v, item, at)}')
        return "{ " + ", ".join(parts) + " }" if parts else "{}"
    if isinstance(value, list):
        return "[" + ", ".join(_usecase_json(v, item, ptr(path, i)) for i, item in enumerate(value)) + "]"
    if isinstance(value, str):
        return f'"{v.text(value, path, "usecase.text")}"'
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return v.number(value, path)


def _usecase_serialize(ir: dict, keyword: str) -> str:
    v = Validator(keyword)
    v.fields(ir, "", (), (
        "title", "config", "direction", "accessibility", "comment", "actors", "usecases",
        "boundaries", "jsonNodes", "notes", "edges", "classDefs", "classAssignments", "styles",
    ))
    config = validate_config(v, ir["config"], "/config", _USECASE_CONFIG) if "config" in ir else {}
    title = v.text(ir["title"], "/title", "usecase.title") if "title" in ir else None
    lines = emit_frontmatter(title, {"usecase": config} if config else None)
    lines.append("usecase-beta")
    if "direction" in ir:
        lines.append(f"direction {v.enum(ir['direction'], '/direction', _G5_DIRECTIONS)}")
    lines += emit_accessibility(v, ir, "")
    lines += emit_comment(v, ir, "", "")

    ids: set[str] = set()
    class_names: set[str] = set()
    class_lines: list[str] = []
    for i, cdef in enumerate(_g5_list(v, ir, "", "classDefs")):
        path = ptr("/classDefs", i)
        v.fields(cdef, path, ("names", "style"))
        names = []
        for j, name in enumerate(v.array(cdef["names"], ptr(path, "names"), 1)):
            at = ptr(ptr(path, "names"), j)
            names.append(v.unique(v.ident(name, at), at, class_names, "class name"))
        class_lines.append(f"classDef {','.join(names)} {_g5_style(v, cdef['style'], ptr(path, 'style'))}")

    def suffix(obj: dict, path: str) -> str:
        out = ""
        if "stereotype" in obj:
            out += f" <<{v.text(obj['stereotype'], ptr(path, 'stereotype'), 'usecase.text')}>>"
        if "class" in obj:
            out += f":::{v.ref(obj['class'], ptr(path, 'class'), class_names)}"
        return out

    boundaries = _g5_list(v, ir, "", "boundaries")
    boundary_ids: set[str] = set()
    for i, boundary in enumerate(boundaries):
        path = ptr("/boundaries", i)
        v.fields(boundary, path, ("id",), ("label", "form", "type", "metadataStatement", "class"))
        boundary_ids.add(v.unique(_usecase_id(v, boundary["id"], ptr(path, "id")), ptr(path, "id"), ids))

    actor_decls: dict[str | None, list[str]] = {}
    case_decls: dict[str | None, list[str]] = {}
    actor_ids: set[str] = set()
    for i, actor in enumerate(_g5_list(v, ir, "", "actors")):
        path = ptr("/actors", i)
        v.fields(actor, path, ("id",), ("label", "type", "icon", "business", "stereotype", "class", "boundary"))
        actor_id = v.unique(_usecase_id(v, actor["id"], ptr(path, "id")), ptr(path, "id"), ids)
        actor_ids.add(actor_id)
        decl = f"actor {actor_id}"
        if "label" in actor:
            decl += f'("{v.text(actor["label"], ptr(path, "label"), "usecase.text")}")'
        meta = []
        if "type" in actor:
            meta.append(f"type: {v.enum(actor['type'], ptr(path, 'type'), _USECASE_ACTOR_TYPES)}")
        if "icon" in actor:
            if "type" in actor or actor.get("business"):
                raise v.error(ptr(path, "icon"), "an icon actor cannot also set type or business")
            meta.append(f'icon: "{v.text(actor["icon"], ptr(path, "icon"), "usecase.icon")}"')
        if "business" in actor and v.boolean(actor["business"], ptr(path, "business")):
            meta.append("business: true")
        if meta:
            decl += f"@{{ {', '.join(meta)} }}"
        decl += suffix(actor, path)
        boundary = v.ref(actor["boundary"], ptr(path, "boundary"), boundary_ids) if "boundary" in actor else None
        actor_decls.setdefault(boundary, []).append(decl)

    case_ids: set[str] = set()
    implicit: dict[str, str] = {}  # id -> pointer, for use cases declared only by an edge
    for i, case in enumerate(_g5_list(v, ir, "", "usecases")):
        path = ptr("/usecases", i)
        v.fields(case, path, ("id",), (
            "label", "markdown", "shape", "form", "implicit", "business", "stereotype", "class", "boundary",
        ))
        case_id = v.unique(_usecase_id(v, case["id"], ptr(path, "id")), ptr(path, "id"), ids)
        case_ids.add(case_id)
        if "implicit" in case and v.boolean(case["implicit"], ptr(path, "implicit")):
            extra = sorted(set(case) - {"id", "implicit"})
            if extra:
                raise v.error(ptr(path, extra[0]), "an implicit use case takes only an id")
            implicit[case_id] = path
            continue
        if ("label" in case) == ("markdown" in case):
            raise v.error(ptr(path, "label"), "set exactly one of label or markdown")
        form = v.enum(case.get("form", "declared"), ptr(path, "form"), _USECASE_FORMS)
        shape = v.enum(case.get("shape", "ellipse"), ptr(path, "shape"), _USECASE_SHAPES)
        if form == "quoted":
            for key in ("markdown", "shape", "business", "stereotype", "class"):
                if key in case:
                    raise v.error(ptr(path, key), "the quoted declaration form takes only a label")
            text = v.text(case["label"], ptr(path, "label"), "usecase.quoted-form")
            if text.replace(" ", "_") != case_id:
                raise v.error(ptr(path, "id"), f"the quoted form derives the id {text.replace(' ', '_')!r}")
            decl = f'"{text}"'
        else:
            if "label" in case:
                text = v.text(case["label"], ptr(path, "label"), "usecase.text")
            else:
                text = f"`{v.text(case['markdown'], ptr(path, 'markdown'), 'usecase.markdown')}`"
            decl = f"{case_id}{shape[0]}{text}{shape[1]}"
            if "business" in case and v.boolean(case["business"], ptr(path, "business")):
                if case.get("shape") == "rect":
                    raise v.error(ptr(path, "business"), "only an ellipse use case takes business")
                decl += "@{ business: true }"
            decl += suffix(case, path)
        boundary = v.ref(case["boundary"], ptr(path, "boundary"), boundary_ids) if "boundary" in case else None
        case_decls.setdefault(boundary, []).append(decl)

    lines += actor_decls.get(None, [])
    statement_lines: list[str] = []
    for i, boundary in enumerate(boundaries):
        path = ptr("/boundaries", i)
        form = v.enum(boundary.get("form", "declared"), ptr(path, "form"), _USECASE_FORMS)
        if form == "quoted":
            if "label" not in boundary:
                raise v.error(ptr(path, "label"), "the quoted form needs a label")
            text = v.text(boundary["label"], ptr(path, "label"), "usecase.quoted-form")
            if text.replace(" ", "_") != boundary["id"]:
                raise v.error(ptr(path, "id"), f"the quoted form derives the id {text.replace(' ', '_')!r}")
            decl = f'systemBoundary "{text}"'
        else:
            decl = f"systemBoundary {boundary['id']}"
            if "label" in boundary:
                decl += f'["{v.text(boundary["label"], ptr(path, "label"), "usecase.text")}"]'
        statement = v.boolean(boundary["metadataStatement"], ptr(path, "metadataStatement")) \
            if "metadataStatement" in boundary else False
        if "type" in boundary:
            kind = v.enum(boundary["type"], ptr(path, "type"), _USECASE_BOUNDARY_TYPES)
            if statement:
                statement_lines.append(f"{boundary['id']}@{{ type: {kind} }}")
            else:
                decl += f"@{{ type: {kind} }}"
        elif statement:
            raise v.error(ptr(path, "metadataStatement"), "needs a type to put in the statement")
        if "class" in boundary:
            decl += f":::{v.ref(boundary['class'], ptr(path, 'class'), class_names)}"
        inside = actor_decls.get(boundary["id"], []) + case_decls.get(boundary["id"], [])
        if not inside:
            raise v.error(ptr(path, "id"), "a boundary needs at least one actor or use case")
        lines += [decl, *[f"  {d}" for d in inside], "end"]
    lines += statement_lines
    lines += case_decls.get(None, [])

    json_ids: set[str] = set()
    for i, node in enumerate(_g5_list(v, ir, "", "jsonNodes")):
        path = ptr("/jsonNodes", i)
        v.fields(node, path, ("id", "data"), ("class",))
        node_id = v.unique(_usecase_id(v, node["id"], ptr(path, "id")), ptr(path, "id"), ids)
        json_ids.add(node_id)
        data = v.obj_map(node["data"], ptr(path, "data"))
        if not data:
            raise v.error(ptr(path, "data"), "must have at least one key")
        decl = f"json {node_id}@{_usecase_json(v, data, ptr(path, 'data'))}"
        if "class" in node:
            decl += f":::{v.ref(node['class'], ptr(path, 'class'), class_names)}"
        lines.append(decl)

    for i, note in enumerate(_g5_list(v, ir, "", "notes")):
        path = ptr("/notes", i)
        v.fields(note, path, ("for", "text"))
        target = v.ref(note["for"], ptr(path, "for"), actor_ids | case_ids)
        lines.append(f'note for {target} "{v.text(note["text"], ptr(path, "text"), "usecase.text")}"')

    endpoints = actor_ids | case_ids | json_ids
    referenced: set[str] = set()
    edge_ids: set[str] = set()
    edge_meta: list[str] = []
    for i, edge in enumerate(_g5_list(v, ir, "", "edges")):
        path = ptr("/edges", i)
        v.fields(edge, path, ("from", "to"), ("kind", "label", "length", "id", "animate", "animation"))
        source = v.ref(edge["from"], ptr(path, "from"), endpoints)
        target = v.ref(edge["to"], ptr(path, "to"), endpoints)
        referenced |= {source, target}
        kind = edge.get("kind", "association")
        arrow, labelled, stretch = v.enum(kind, ptr(path, "kind"), _USECASE_EDGES)
        if kind in ("include", "extend") and not {source, target} <= case_ids:
            raise v.error(ptr(path, "kind"), f"{kind} needs use cases at both ends")
        if kind == "generalization" and not ({source, target} <= case_ids or {source, target} <= actor_ids):
            raise v.error(ptr(path, "kind"), "generalization needs two actors or two use cases")
        if {source, target} & json_ids and kind not in ("association", "reverseAssociation", "line"):
            raise v.error(ptr(path, "kind"), "a JSON node takes only association, reverseAssociation or line edges")
        extra = 0
        if "length" in edge:
            if not stretch:
                raise v.error(ptr(path, "length"), f"a {kind} edge cannot be lengthened")
            extra = int(v.number(edge["length"], ptr(path, "length"), 1, 8, integer=True))
        prefix = ""
        if "id" in edge:
            edge_id = v.unique(_usecase_id(v, edge["id"], ptr(path, "id")), ptr(path, "id"), ids)
            edge_ids.add(edge_id)
            prefix = f"{edge_id}@"
            meta = []
            if "animate" in edge:
                meta.append(f"animate: {'true' if v.boolean(edge['animate'], ptr(path, 'animate')) else 'false'}")
            if "animation" in edge:
                meta.append(f"animation: {v.enum(edge['animation'], ptr(path, 'animation'), ('fast', 'slow'))}")
            if meta:
                edge_meta.append(f"{edge_id}@{{ {', '.join(meta)} }}")
        else:
            for key in ("animate", "animation"):
                if key in edge:
                    raise v.error(ptr(path, key), "edge metadata needs an edge id")
        if "label" in edge:
            if labelled is None:
                raise v.error(ptr(path, "label"), f"a {kind} edge takes no label")
            left, right = labelled
            if extra:
                right = right.replace("--", "--" + "-" * extra, 1)
            text = v.text(edge["label"], ptr(path, "label"), "usecase.text")
            lines.append(f'{source} {prefix}{left} "{text}" {right} {target}')
        else:
            if extra:
                arrow = arrow.replace("--", "--" + "-" * extra, 1)
            lines.append(f"{source} {prefix}{arrow} {target}")
    for case_id, path in implicit.items():
        if case_id not in referenced:
            raise v.error(ptr(path, "implicit"), "an implicit use case must be the end of an edge")

    lines += class_lines
    targets = endpoints | boundary_ids | edge_ids
    for i, assign in enumerate(_g5_list(v, ir, "", "classAssignments")):
        path = ptr("/classAssignments", i)
        v.fields(assign, path, ("ids", "classes"))
        who = [v.ref(x, ptr(ptr(path, "ids"), j), targets) for j, x in enumerate(v.array(assign["ids"], ptr(path, "ids"), 1))]
        what = [v.ref(x, ptr(ptr(path, "classes"), j), class_names)
                for j, x in enumerate(v.array(assign["classes"], ptr(path, "classes"), 1))]
        lines.append(f"class {','.join(who)} {','.join(what)}")
    for i, style in enumerate(_g5_list(v, ir, "", "styles")):
        path = ptr("/styles", i)
        v.fields(style, path, ("id", "style"))
        target = v.ref(style["id"], ptr(path, "id"), targets)
        lines.append(f"style {target} {_g5_style(v, style['style'], ptr(path, 'style'))}")
    lines += edge_meta
    if not (actor_ids or case_ids or json_ids):
        raise v.error("", "a diagram needs at least one actor, use case or JSON node")
    return "\n".join(lines) + "\n"


register(Builder(
    "usecase", "usecase", ("usecase-beta",), _usecase_serialize,
    text_fields=(
        "/title", "/comment", "/accessibility/title", "/accessibility/description",
        "/actors/*/label", "/actors/*/stereotype", "/usecases/*/label", "/usecases/*/markdown",
        "/usecases/*/stereotype", "/boundaries/*/label", "/edges/*/label", "/notes/*/text",
        "/jsonNodes/*/data/*", "/jsonNodes/*/data/*/*/*",
    ),
    features={
        "usecase.keyword": "/target=usecase-beta",
        "usecase.direction-td": "/direction=TD",
        "usecase.direction-tb": "/direction=TB",
        "usecase.direction-bt": "/direction=BT",
        "usecase.direction-lr": "/direction=LR",
        "usecase.direction-rl": "/direction=RL",
        "usecase.actor": "/actors/*/id=Customer",
        "usecase.actor-label": "/actors/*/label",
        "usecase.actor-digit-id": "/actors/*/id=3rd",
        "usecase.actor-normal": "/actors/*/type=normal",
        "usecase.actor-hollow": "/actors/*/type=hollow",
        "usecase.actor-awesome": "/actors/*/type=awesome",
        "usecase.actor-icon": "/actors/*/icon",
        "usecase.business-actor": "/actors/*/business=true",
        "usecase.business-usecase": "/usecases/*/business=true",
        "usecase.stereotype": "/usecases/*/stereotype",
        "usecase.usecase-ellipse": "/usecases/*/shape=ellipse",
        "usecase.usecase-rect": "/usecases/*/shape=rect",
        "usecase.usecase-quoted": "/usecases/*/form=quoted",
        "usecase.usecase-implicit": "/usecases/*/implicit=true",
        "usecase.label-unquoted": "/usecases/*/label=Costs 19.95 EUR!",
        "usecase.label-string": "/usecases/*/label=**Literal markers**",
        "usecase.label-markdown": "/usecases/*/markdown",
        "usecase.label-entity": "/usecases/*/label=Refund (partial)",
        "usecase.comment": "/comment",
        "usecase.boundary": "/boundaries/*/label",
        "usecase.boundary-quoted": "/boundaries/*/form=quoted",
        "usecase.boundary-rect": "/boundaries/*/type=rect",
        "usecase.boundary-package": "/boundaries/*/type=package",
        "usecase.boundary-metadata-statement": "/boundaries/*/metadataStatement=true",
        "usecase.assoc-point": "/edges/*/kind=association",
        "usecase.assoc-reverse-point": "/edges/*/kind=reverseAssociation",
        "usecase.assoc-plain": "/edges/*/kind=line",
        "usecase.assoc-circle": "/edges/*/kind=circle",
        "usecase.assoc-reverse-circle": "/edges/*/kind=reverseCircle",
        "usecase.assoc-cross": "/edges/*/kind=cross",
        "usecase.assoc-reverse-cross": "/edges/*/kind=reverseCross",
        "usecase.assoc-label": "/edges/*/label",
        "usecase.assoc-label-unquoted": "/edges/*/label=files R&D report",
        "usecase.assoc-length": "/edges/*/length",
        "usecase.include": "/edges/*/kind=include",
        "usecase.extend": "/edges/*/kind=extend",
        "usecase.generalization": "/edges/*/kind=generalization",
        "usecase.edge-id": "/edges/*/id",
        "usecase.edge-animate": "/edges/*/animate",
        "usecase.edge-animation-fast": "/edges/*/animation=fast",
        "usecase.edge-animation-slow": "/edges/*/animation=slow",
        "usecase.note": "/notes/*/text",
        "usecase.json": "/jsonNodes/*/data",
        "usecase.classdef": "/classDefs/*/style",
        "usecase.classdef-default": "/classDefs/*/names/*=default",
        "usecase.classdef-multi": "/classDefs/*/names/1",
        "usecase.class": "/classAssignments/*/classes/*",
        "usecase.class-shorthand": "/usecases/*/class",
        "usecase.style": "/styles/*/id=ordering",
        "usecase.style-edge": "/styles/*/id=pays",
        "usecase.acc-title": "/accessibility/title",
        "usecase.acc-descr": "/accessibility/description=A customer signs in",
        "usecase.acc-descr-block": "/accessibility/description=A customer places an order.\nStaff review it and inspect its data.",
    },
    probes={"object": "/actors/1", "number": "/edges/0/length", "enum": "/actors/1/type", "ref": "/edges/0/to"},
))

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
