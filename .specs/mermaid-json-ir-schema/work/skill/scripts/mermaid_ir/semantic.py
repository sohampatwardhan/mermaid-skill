"""Reusable semantic diagnostics that JSON Schema cannot express clearly."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .diagnostics import join_pointer, sort_diagnostics
from .model import Diagnostic


def duplicate_id_diagnostics(items: list[dict[str, Any]], pointer: str) -> tuple[Diagnostic, ...]:
    """Report every duplicate ID at its later declaration and link the first declaration."""

    first: dict[str, str] = {}
    diagnostics: list[Diagnostic] = []
    for index, item in enumerate(items):
        if "id" not in item:
            continue
        identifier = str(item["id"])
        current = join_pointer(join_pointer(pointer, index), "id")
        if identifier in first:
            diagnostics.append(Diagnostic(
                "semantic.duplicateId", current, f"duplicate identifier {identifier!r}", (first[identifier],)
            ))
        else:
            first[identifier] = current
    return sort_diagnostics(diagnostics)


def reference_diagnostics(
    items: list[dict[str, Any]], known: Iterable[str], pointer: str, fields: tuple[str, ...]
) -> tuple[Diagnostic, ...]:
    """Report references whose exact identifier is absent from the declared identifier set."""

    allowed = set(known)
    diagnostics: list[Diagnostic] = []
    for index, item in enumerate(items):
        for field in fields:
            if field in item and item[field] not in allowed:
                diagnostics.append(Diagnostic(
                    "semantic.unknownReference",
                    join_pointer(join_pointer(pointer, index), field),
                    f"reference {item[field]!r} is not declared",
                ))
    return sort_diagnostics(diagnostics)


def forbidden_combination(
    condition: bool, code: str, message: str, pointers: tuple[str, ...]
) -> tuple[Diagnostic, ...]:
    """Create symmetric cross-field diagnostics when a forbidden combination is present."""

    if not condition:
        return ()
    return sort_diagnostics(
        Diagnostic(code, pointer, message, tuple(other for other in pointers if other != pointer))
        for pointer in pointers
    )
