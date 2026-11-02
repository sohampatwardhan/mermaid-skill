"""Materialize schema-declared defaults without mutating caller documents."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .migrate import get_target_spec, migrate_legacy
from .model import Diagnostic, IRError
from .schema_runtime import SchemaRegistry, validate_schema


def _canonical_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _canonical_copy(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical_copy(item) for item in value]
    return copy.deepcopy(value)


def _apply_defaults(
    value: Any,
    schema: dict[str, Any] | bool,
    registry: SchemaRegistry,
    base_schema: dict[str, Any] | None = None,
    base_path: Path | None = None,
) -> Any:
    if not isinstance(schema, dict):
        return _canonical_copy(value)
    if "$ref" in schema:
        reference = schema["$ref"]
        resolved, resolved_path, _token = registry.resolve_ref(reference, base_schema, base_path)
        # See the matching comment in schema_runtime.py: only a ref with a file part crosses into
        # a new document/root. A local `#/...` fragment ref must keep the caller's root and path
        # unchanged, even when that root has no path of its own (a target schema loaded straight
        # from disk) — otherwise a second-level or recursive local ref can't resolve.
        file_part = reference.partition("#")[0]
        if file_part:
            resolved_root = registry.load(resolved_path)[0]
        else:
            resolved_root = base_schema
            resolved_path = base_path
        return _apply_defaults(value, resolved, registry, resolved_root, resolved_path)
    result = _canonical_copy(value)
    for child in schema.get("allOf", []):
        result = _apply_defaults(result, child, registry, base_schema, base_path)
    if "oneOf" in schema:
        matches = [child for child in schema["oneOf"] if not validate_schema(result, child, registry)]
        if len(matches) == 1:
            result = _apply_defaults(result, matches[0], registry, base_schema, base_path)
    if "if" in schema:
        selected = schema.get("then") if not validate_schema(result, schema["if"], registry) else schema.get("else")
        if selected is not None:
            result = _apply_defaults(result, selected, registry, base_schema, base_path)
    if isinstance(result, dict):
        properties = schema.get("properties", {})
        expanded: dict[str, Any] = {}
        for key in sorted(set(result) | set(properties)):
            child_schema = properties.get(key)
            if key in result:
                expanded[key] = _apply_defaults(result[key], child_schema, registry, base_schema, base_path) if child_schema is not None else result[key]
            elif isinstance(child_schema, dict) and "default" in child_schema:
                expanded[key] = _apply_defaults(copy.deepcopy(child_schema["default"]), child_schema, registry, base_schema, base_path)
        result = expanded
    elif isinstance(result, list) and "items" in schema:
        result = [_apply_defaults(item, schema["items"], registry, base_schema, base_path) for item in result]
    return result


def normalize(ir: dict[str, Any], target_override: str | None = None) -> dict[str, Any]:
    """Migrate, deep-copy, default, and key-order a document idempotently.

    Defaults are read from the selected target schema; an explicit invalid value is retained for
    structural validation rather than being silently replaced.
    """

    canonical = migrate_legacy(ir, target_override)
    target = canonical.get("target")
    spec = get_target_spec(target) if isinstance(target, str) else None
    if spec is None:
        raise IRError(Diagnostic("schema.target", "/target", f"unsupported target {target!r}"))
    registry = getattr(spec, "schema_registry", None) or SchemaRegistry(Path(__file__).resolve().parents[2] / "schema")
    schema = spec.schema
    base_schema = schema if isinstance(schema, dict) else None
    return _apply_defaults(canonical, schema, registry, base_schema, None)
