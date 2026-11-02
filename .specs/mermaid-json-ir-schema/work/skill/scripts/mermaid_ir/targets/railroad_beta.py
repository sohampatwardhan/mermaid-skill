"""Strict railroad-beta target contract (see reference/syntax/railroad.md)."""

from __future__ import annotations

from typing import Any

from ..diagnostics import join_pointer, sort_diagnostics
from ..legacy_serializers import render_railroad
from ..model import Diagnostic
from ._base import legacy_serializer, make_target_spec

LEGACY_FIELDS = frozenset(['rules'])


def _walk_nonterminals(expr: dict, pointer: str, known: set[str], diagnostics: list[Diagnostic]) -> None:
    kind = expr.get("kind")
    if kind == "nonterminal":
        name = expr.get("name")
        if name is not None and name not in known:
            diagnostics.append(Diagnostic(
                "semantic.unknownReference", join_pointer(pointer, "name"),
                f"reference {name!r} is not a declared rule",
            ))
    elif kind in ("sequence", "choice"):
        for index, item in enumerate(expr.get("items", [])):
            _walk_nonterminals(item, join_pointer(join_pointer(pointer, "items"), index), known, diagnostics)
    elif kind in ("optional", "zeroOrMore", "oneOrMore") and expr.get("item") is not None:
        _walk_nonterminals(expr["item"], join_pointer(pointer, "item"), known, diagnostics)


def railroad_semantics(document: dict[str, Any]) -> tuple[Diagnostic, ...]:
    """Report duplicate rule names and nonterminal references to undeclared rules."""

    content = document["content"]
    rules = content.get("rules", [])
    diagnostics: list[Diagnostic] = []
    first: dict[str, str] = {}
    for index, rule in enumerate(rules):
        name = rule.get("name")
        pointer = join_pointer(join_pointer("/content/rules", index), "name")
        if name is None:
            continue
        if name in first:
            diagnostics.append(Diagnostic(
                "semantic.duplicateId", pointer, f"rule {name!r} is declared more than once", (first[name],)
            ))
        else:
            first[name] = pointer
    known = set(first)
    for index, rule in enumerate(rules):
        expression = rule.get("expression")
        if expression is not None:
            _walk_nonterminals(expression, join_pointer(join_pointer("/content/rules", index), "expression"), known, diagnostics)
    return sort_diagnostics(diagnostics)


SPEC = make_target_spec(
    'railroad-beta', 'railroad', LEGACY_FIELDS,
    legacy_serializer('railroad', 'railroad-beta', render_railroad),
    validator=railroad_semantics,
)
