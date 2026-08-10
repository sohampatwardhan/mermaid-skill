"""Shared construction helpers for disjoint strict target modules."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Callable

from ..model import Diagnostic
from ..registry import TargetSpec
from ..semantic import duplicate_id_diagnostics, reference_diagnostics
from ..serialization import merge_preamble

SKILL_ROOT = Path(__file__).resolve().parents[3]


def load_target_schema(target: str) -> dict[str, Any]:
    """Load one bundled target schema without introducing runtime package dependencies."""

    path = SKILL_ROOT / "schema" / "targets" / f"{target}.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def copy_legacy_fields(fields: frozenset[str]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Build a migration adapter for legacy fields already represented as typed JSON values."""

    def migrate(ir: dict[str, Any]) -> dict[str, Any]:
        return {key: copy.deepcopy(ir[key]) for key in sorted(fields) if key in ir}

    return migrate


def graph_semantics(document: dict[str, Any]) -> tuple[Diagnostic, ...]:
    """Validate duplicate declarations and edge references for graph-shaped targets."""

    content = document["content"]
    nodes = content.get("nodes", [])
    groups = content.get("groups", [])
    diagnostics = list(duplicate_id_diagnostics(nodes, "/content/nodes"))
    diagnostics.extend(duplicate_id_diagnostics(groups, "/content/groups"))
    known = {item["id"] for item in nodes if "id" in item} | {item["id"] for item in groups if "id" in item}
    diagnostics.extend(reference_diagnostics(content.get("edges", []), known, "/content/edges", ("from", "to")))
    return tuple(sorted(diagnostics, key=lambda item: (item.pointer, item.code, item.message)))


def legacy_serializer(
    family: str,
    target: str,
    function: Callable[[dict[str, Any]], str],
    prepare: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> Callable[[dict[str, Any]], str]:
    """Adapt canonical content to a proven flat serializer and merge canonical preamble fields."""

    def serialize(document: dict[str, Any]) -> str:
        content = copy.deepcopy(document["content"])
        if prepare is not None:
            content = prepare(content)
        legacy = {"diagram": family, "target": target, **content}
        return merge_preamble(document, function(legacy))

    return serialize


def make_target_spec(
    target: str,
    family: str,
    legacy_fields: frozenset[str],
    serializer: Callable[[dict[str, Any]], str],
    validator: Callable[[dict[str, Any]], tuple[Diagnostic, ...]] = graph_semantics,
    migrator: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    config_namespace: str | None = None,
) -> TargetSpec:
    """Create a complete target contract from independently owned target artifacts."""

    return TargetSpec(
        target=target,
        family=family,
        schema=load_target_schema(target),
        legacy_fields=legacy_fields,
        migrate_legacy_content=migrator or copy_legacy_fields(legacy_fields),
        validate_semantics=validator,
        serialize=serializer,
        config_namespace=config_namespace,
    )
