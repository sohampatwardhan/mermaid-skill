"""Strict wardley-beta target contract (see reference/syntax/wardley.md)."""

from __future__ import annotations

from typing import Any

from ..diagnostics import join_pointer, sort_diagnostics
from ..legacy_serializers import render_wardley
from ..model import Diagnostic
from ..semantic import duplicate_id_diagnostics, reference_diagnostics
from ._base import legacy_serializer, make_target_spec

LEGACY_FIELDS = frozenset([
    'size', 'evolutionStages', 'anchors', 'components', 'pipelines', 'links', 'evolve',
    'notes', 'accelerators', 'deaccelerators', 'annotationsPosition', 'annotations',
])


def wardley_semantics(document: dict[str, Any]) -> tuple[Diagnostic, ...]:
    """Validate duplicate node ids and every id-reference against declared anchors/components."""

    content = document["content"]
    anchors = content.get("anchors", [])
    components = content.get("components", [])
    diagnostics = list(duplicate_id_diagnostics(anchors, "/content/anchors"))
    diagnostics.extend(duplicate_id_diagnostics(components, "/content/components"))
    known = {item["id"] for item in anchors if "id" in item} | {item["id"] for item in components if "id" in item}

    diagnostics.extend(reference_diagnostics(content.get("links", []), known, "/content/links", ("from", "to")))
    diagnostics.extend(reference_diagnostics(content.get("evolve", []), known, "/content/evolve", ("id",)))
    diagnostics.extend(reference_diagnostics(content.get("pipelines", []), known, "/content/pipelines", ("parent",)))
    return sort_diagnostics(diagnostics)


SPEC = make_target_spec(
    'wardley-beta', 'wardley', LEGACY_FIELDS,
    legacy_serializer('wardley', 'wardley-beta', render_wardley),
    validator=wardley_semantics,
)
