"""Strict eventmodeling target contract (see reference/syntax/eventmodeling.md)."""

from __future__ import annotations

from typing import Any

from ..diagnostics import join_pointer, sort_diagnostics
from ..legacy_serializers import render_eventmodeling
from ..model import Diagnostic
from ._base import legacy_serializer, make_target_spec

LEGACY_FIELDS = frozenset(['timeframes', 'dataBlocks'])


def eventmodeling_semantics(document: dict[str, Any]) -> tuple[Diagnostic, ...]:
    """Validate Time Frame number uniqueness, dataRef/relations targets, and data-block ids."""

    content = document["content"]
    timeframes = content.get("timeframes", [])
    data_blocks = content.get("dataBlocks", [])
    diagnostics: list[Diagnostic] = []

    seen_numbers: dict[str, str] = {}
    for index, frame in enumerate(timeframes):
        number = frame.get("number")
        pointer = join_pointer(join_pointer("/content/timeframes", index), "number")
        if number is None:
            continue
        if number in seen_numbers:
            diagnostics.append(Diagnostic(
                "semantic.duplicateId", pointer, f"Time Frame number {number!r} is declared more than once",
                (seen_numbers[number],),
            ))
        else:
            seen_numbers[number] = pointer

    first_block: dict[str, str] = {}
    for index, block in enumerate(data_blocks):
        block_id = block.get("id")
        pointer = join_pointer(join_pointer("/content/dataBlocks", index), "id")
        if block_id is None:
            continue
        if block_id in first_block:
            diagnostics.append(Diagnostic(
                "semantic.duplicateId", pointer, f"data block {block_id!r} is declared more than once",
                (first_block[block_id],),
            ))
        else:
            first_block[block_id] = pointer

    known_numbers = set(seen_numbers)
    known_blocks = set(first_block)
    for index, frame in enumerate(timeframes):
        base = join_pointer("/content/timeframes", index)
        if frame.get("data") is not None and frame.get("dataRef") is not None:
            diagnostics.append(Diagnostic(
                "semantic.conflictingFields", base, "a Time Frame cannot set both data and dataRef",
            ))
        data_ref = frame.get("dataRef")
        if data_ref is not None and data_ref not in known_blocks:
            diagnostics.append(Diagnostic(
                "semantic.unknownReference", join_pointer(base, "dataRef"),
                f"reference {data_ref!r} is not declared in content.dataBlocks",
            ))
        for rel_index, relation in enumerate(frame.get("relations", [])):
            if relation not in known_numbers:
                diagnostics.append(Diagnostic(
                    "semantic.unknownReference", join_pointer(join_pointer(base, "relations"), rel_index),
                    f"reference {relation!r} is not a declared Time Frame number",
                ))

    return sort_diagnostics(diagnostics)


SPEC = make_target_spec(
    'eventmodeling', 'eventmodeling', LEGACY_FIELDS,
    legacy_serializer('eventmodeling', 'eventmodeling', render_eventmodeling),
    validator=eventmodeling_semantics,
)
