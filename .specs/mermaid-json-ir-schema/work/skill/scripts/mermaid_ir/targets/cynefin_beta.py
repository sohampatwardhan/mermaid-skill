"""Strict cynefin-beta target contract (see reference/syntax/cynefin.md)."""

from __future__ import annotations

from typing import Any

from ..diagnostics import join_pointer, sort_diagnostics
from ..legacy_serializers import render_cynefin
from ..model import Diagnostic
from ._base import legacy_serializer, make_target_spec

LEGACY_FIELDS = frozenset(['domains', 'transitions'])


def cynefin_semantics(document: dict[str, Any]) -> tuple[Diagnostic, ...]:
    """Report each domain declared more than once, at its later declaration."""

    content = document["content"]
    first: dict[str, str] = {}
    diagnostics: list[Diagnostic] = []
    for index, entry in enumerate(content.get("domains", [])):
        domain = entry.get("domain")
        if domain is None:
            continue
        pointer = join_pointer(join_pointer("/content/domains", index), "domain")
        if domain in first:
            diagnostics.append(Diagnostic(
                "semantic.duplicateId", pointer, f"domain {domain!r} is declared more than once", (first[domain],)
            ))
        else:
            first[domain] = pointer
    return sort_diagnostics(diagnostics)


SPEC = make_target_spec(
    'cynefin-beta', 'cynefin', LEGACY_FIELDS,
    legacy_serializer('cynefin', 'cynefin-beta', render_cynefin),
    validator=cynefin_semantics,
)
