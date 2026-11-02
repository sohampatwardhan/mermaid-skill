"""Strict venn-beta target contract (see reference/syntax/venn.md)."""

from __future__ import annotations

from typing import Any

from ..diagnostics import join_pointer, sort_diagnostics
from ..legacy_serializers import render_venn
from ..model import Diagnostic
from ..semantic import duplicate_id_diagnostics
from ._base import legacy_serializer, make_target_spec

LEGACY_FIELDS = frozenset(['sets', 'unions'])


def venn_semantics(document: dict[str, Any]) -> tuple[Diagnostic, ...]:
    """Validate duplicate set/text ids and that every union member references a declared set."""

    content = document["content"]
    sets = content.get("sets", [])
    unions = content.get("unions", [])
    diagnostics = list(duplicate_id_diagnostics(sets, "/content/sets"))
    known = {item["id"] for item in sets if "id" in item}
    for index, union in enumerate(unions):
        base = join_pointer(join_pointer("/content/unions", index), "ids")
        for member_index, member in enumerate(union.get("ids", [])):
            if member not in known:
                diagnostics.append(Diagnostic(
                    "semantic.unknownReference", join_pointer(base, member_index),
                    f"reference {member!r} is not a declared set",
                ))
    return sort_diagnostics(diagnostics)


SPEC = make_target_spec(
    'venn-beta', 'venn', LEGACY_FIELDS,
    legacy_serializer('venn', 'venn-beta', render_venn),
    validator=venn_semantics,
)
