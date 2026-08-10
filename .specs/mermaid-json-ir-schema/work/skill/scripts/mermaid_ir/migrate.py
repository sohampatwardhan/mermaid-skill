"""Convert documented flat legacy IR into the strict canonical envelope.

Migration is intentionally registry-dispatched: target modules own grammar-shaped legacy
values, while this module owns the closed top-level boundary and cross-cutting sections.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from .diagnostics import join_pointer, sort_diagnostics
from .model import Diagnostic, IRError

_TARGET_LOOKUP: Callable[[str], Any | None] = lambda _target: None
_COMMON_LEGACY_FIELDS = frozenset({"diagram", "target", "accTitle", "accDescr"})


def set_target_lookup(provider: Callable[[str], Any | None]) -> None:
    """Bind target lookup without importing the later registry layer.

    The seam keeps compiler scaffolding independently testable and is replaced once the real
    ``TARGETS`` registry is assembled.
    """

    global _TARGET_LOOKUP
    _TARGET_LOOKUP = provider


def get_target_spec(target: str) -> Any | None:
    """Return the registered target contract, or ``None`` when the target is unsupported."""

    return _TARGET_LOOKUP(target)


def migrate_legacy(ir: dict[str, Any], target_override: str | None) -> dict[str, Any]:
    """Return a deep-copied canonical document or fail on undocumented legacy fields.

    Canonical target overrides must agree with the document. Legacy target-specific parsing is
    delegated so opaque Mermaid grammar never becomes a generic raw-fragment escape hatch.
    """

    if not isinstance(ir, dict):
        raise IRError(Diagnostic("migration.type", "", "IR document must be an object"))
    if "schemaVersion" in ir:
        if target_override is not None and ir.get("target") != target_override:
            raise IRError(Diagnostic("migration.targetConflict", "/target", "canonical target conflicts with override"))
        return copy.deepcopy(ir)

    resolved_target = target_override or ir.get("target")
    if not isinstance(resolved_target, str) or not resolved_target:
        raise IRError(Diagnostic("migration.target", "/target", "legacy document requires a target"))
    spec = get_target_spec(resolved_target)
    if spec is None:
        raise IRError(Diagnostic("migration.target", "/target", f"unsupported target {resolved_target!r}"))
    allowed = _COMMON_LEGACY_FIELDS | frozenset(spec.legacy_fields)
    unknown = [
        Diagnostic("migration.unmapped", join_pointer("", key), "legacy field has no canonical mapping")
        for key in ir if key not in allowed
    ]
    if unknown:
        raise IRError(sort_diagnostics(unknown))
    diagram = ir.get("diagram")
    if not isinstance(diagram, str) or not diagram:
        raise IRError(Diagnostic("migration.diagram", "/diagram", "legacy document requires a diagram family"))

    result: dict[str, Any] = {
        "schemaVersion": "1.0.0",
        "diagram": diagram,
        "target": resolved_target,
        "content": spec.migrate_legacy_content(ir),
    }
    accessibility: dict[str, str] = {}
    if "accTitle" in ir:
        accessibility["title"] = copy.deepcopy(ir["accTitle"])
    if "accDescr" in ir:
        accessibility["description"] = copy.deepcopy(ir["accDescr"])
    if accessibility:
        result["accessibility"] = accessibility
    return result
