"""Offline evaluator for the project's constrained JSON Schema Draft 2020-12 subset.

Only the keywords declared here are accepted. Rejecting unknown validation keywords keeps
schema authors from believing an unenforced rule is active, while permitting documentation
annotations and ``default`` for the separate normalization pass.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .diagnostics import join_pointer, sort_diagnostics
from .model import Diagnostic

VALIDATION_KEYWORDS = {
    "$ref", "$defs", "type", "const", "enum", "required", "properties",
    "patternProperties", "additionalProperties", "items", "minItems", "maxItems",
    "uniqueItems", "minimum", "maximum", "minLength", "pattern", "allOf", "oneOf",
    "if", "then", "else",
}
ANNOTATION_KEYWORDS = {"$schema", "$id", "title", "description", "default"}
ALLOWED_KEYWORDS = VALIDATION_KEYWORDS | ANNOTATION_KEYWORDS


class SchemaError(ValueError):
    """Report an invalid or unsafe bundled schema before validating caller data."""


class SchemaRegistry:
    """Load and lint bundled schemas beneath one immutable offline root.

    Remote references and path traversal are rejected because validation must never turn a
    diagram document into a network or arbitrary-filesystem read primitive.
    """

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        self._cache: dict[Path, dict[str, Any]] = {}

    def _safe_path(self, value: str | Path, base_path: Path | None = None) -> Path:
        text = str(value)
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", text):
            raise SchemaError(f"remote schema reference is forbidden: {text}")
        candidate = ((base_path.parent if base_path else self.root) / text).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise SchemaError(f"schema reference resolves outside bundled root: {text}") from exc
        return candidate

    def load(self, value: str | Path, base_path: Path | None = None) -> tuple[dict[str, Any], Path]:
        """Load one local schema and return its parsed object plus canonical path."""

        target = self._safe_path(value, base_path)
        if target not in self._cache:
            try:
                parsed = json.loads(target.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise SchemaError(f"cannot load schema {target}: {exc}") from exc
            if not isinstance(parsed, dict):
                raise SchemaError(f"schema root must be an object: {target}")
            self.lint_schema(parsed)
            self._cache[target] = parsed
        return self._cache[target], target

    def lint_schema(self, schema: Any, location: str = "#") -> None:
        """Reject unsupported keywords while treating property names as instance keys."""

        if isinstance(schema, bool):
            return
        if not isinstance(schema, dict):
            raise SchemaError(f"schema at {location} must be an object or boolean")
        for key, value in schema.items():
            if key not in ALLOWED_KEYWORDS:
                raise SchemaError(f"unsupported schema keyword {key!r} at {location}")
            child_location = f"{location}/{key}"
            if key in {"properties", "patternProperties", "$defs"}:
                if not isinstance(value, dict):
                    raise SchemaError(f"{key} at {location} must be an object")
                for name, child in value.items():
                    self.lint_schema(child, f"{child_location}/{name}")
            elif key in {"items", "additionalProperties", "if", "then", "else"}:
                if isinstance(value, (dict, bool)):
                    self.lint_schema(value, child_location)
            elif key in {"allOf", "oneOf"}:
                if not isinstance(value, list):
                    raise SchemaError(f"{key} at {location} must be an array")
                for index, child in enumerate(value):
                    self.lint_schema(child, f"{child_location}/{index}")

    def resolve_ref(
        self, reference: str, base_schema: dict[str, Any] | None, base_path: Path | None
    ) -> tuple[dict[str, Any] | bool, Path | None, str]:
        """Resolve a file/fragment reference without escaping the bundled schema root."""

        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", reference):
            raise SchemaError(f"remote schema reference is forbidden: {reference}")
        file_part, separator, fragment = reference.partition("#")
        if file_part:
            document, resolved_path = self.load(unquote(file_part), base_path)
        else:
            if base_schema is None:
                raise SchemaError(f"fragment reference requires a containing schema: {reference}")
            document, resolved_path = base_schema, base_path
        current: Any = document
        if separator and fragment:
            if not fragment.startswith("/"):
                raise SchemaError(f"unsupported schema fragment {reference!r}; use a JSON Pointer")
            for raw_token in fragment[1:].split("/"):
                token = unquote(raw_token).replace("~1", "/").replace("~0", "~")
                if not isinstance(current, dict) or token not in current:
                    raise SchemaError(f"unresolved schema fragment {reference!r}")
                current = current[token]
        if not isinstance(current, (dict, bool)):
            raise SchemaError(f"schema reference does not resolve to a schema: {reference}")
        return current, resolved_path, f"{resolved_path or '<inline>'}#{fragment}"


class _Validator:
    def __init__(self, registry: SchemaRegistry):
        self.registry = registry
        self.diagnostics: list[Diagnostic] = []
        self._ref_stack: list[str] = []

    def error(self, code: str, pointer: str, message: str) -> None:
        self.diagnostics.append(Diagnostic(code, pointer, message))

    def branch_valid(
        self, instance: Any, schema: dict[str, Any] | bool, pointer: str,
        base_schema: dict[str, Any] | None, base_path: Path | None,
    ) -> bool:
        branch = _Validator(self.registry)
        branch._ref_stack = list(self._ref_stack)
        branch.validate(instance, schema, pointer, base_schema, base_path)
        return not branch.diagnostics

    def descend(
        self, instance: Any, schema: dict[str, Any] | bool, pointer: str,
        base_schema: dict[str, Any] | None, base_path: Path | None,
    ) -> None:
        """Validate a genuinely new instance value (an object property or array item).

        The `$ref` cycle guard tracks tokens seen without the instance changing, so it can tell a
        true infinite loop (a ref chain that revisits itself with no properties/items ever
        inspected) from ordinary recursive data (a step whose branch contains another step, an
        arbitrary number of times). Once we step into a new property or array element, that data
        is strictly smaller and finite, so any `$ref` a schema reuses from here on is legitimate
        recursion, not a cycle — the stack resets rather than being inherited.
        """
        saved_stack = self._ref_stack
        self._ref_stack = []
        try:
            self.validate(instance, schema, pointer, base_schema, base_path)
        finally:
            self._ref_stack = saved_stack

    def validate(
        self, instance: Any, schema: dict[str, Any] | bool, pointer: str = "",
        base_schema: dict[str, Any] | None = None, base_path: Path | None = None,
    ) -> None:
        if schema is True:
            return
        if schema is False:
            self.error("schema.false", pointer, "value is rejected by the schema")
            return
        if "$ref" in schema:
            reference = schema["$ref"]
            resolved, resolved_path, token = self.registry.resolve_ref(reference, base_schema, base_path)
            if token in self._ref_stack:
                raise SchemaError(f"schema reference cycle detected at {token}")
            self._ref_stack.append(token)
            try:
                # A ref with a file part crosses into a different document, whose own top-level
                # object becomes the new root for any fragment it contains. A local (`#/...`)
                # fragment ref stays inside the current document, so the root and its path must
                # stay exactly what they were — including when the caller has no path at all
                # (e.g. a target schema loaded directly from disk, bypassing the registry cache).
                # Inferring "crossed a file" from `resolved_path is None` breaks precisely in that
                # path-less case: it would wrongly re-root every fragment ref at the fragment
                # itself, and a second-level or recursive local ref would then fail to resolve.
                file_part = reference.partition("#")[0]
                if file_part:
                    resolved_root = self.registry.load(resolved_path)[0]
                else:
                    resolved_root = base_schema
                    resolved_path = base_path
                self.validate(instance, resolved, pointer, resolved_root, resolved_path)
            finally:
                self._ref_stack.pop()
            return

        for child in schema.get("allOf", []):
            self.validate(instance, child, pointer, base_schema, base_path)
        if "oneOf" in schema:
            matches = sum(
                self.branch_valid(instance, child, pointer, base_schema, base_path)
                for child in schema["oneOf"]
            )
            if matches != 1:
                self.error("schema.oneOf", pointer, f"value must match exactly one alternative; matched {matches}")
        if "if" in schema:
            branch = schema.get("then") if self.branch_valid(instance, schema["if"], pointer, base_schema, base_path) else schema.get("else")
            if branch is not None:
                self.validate(instance, branch, pointer, base_schema, base_path)

        expected = schema.get("type")
        if expected is not None and not _matches_type(instance, expected):
            self.error("schema.type", pointer, f"expected {expected}, got {_json_type(instance)}")
            return
        if "const" in schema and instance != schema["const"]:
            self.error("schema.const", pointer, f"expected constant {schema['const']!r}")
        if "enum" in schema and instance not in schema["enum"]:
            self.error("schema.enum", pointer, f"expected one of {schema['enum']!r}")

        if isinstance(instance, dict):
            self._validate_object(instance, schema, pointer, base_schema, base_path)
        elif isinstance(instance, list):
            self._validate_array(instance, schema, pointer, base_schema, base_path)
        elif isinstance(instance, str):
            if "minLength" in schema and len(instance) < schema["minLength"]:
                self.error("schema.minLength", pointer, f"string must contain at least {schema['minLength']} characters")
            if "pattern" in schema and re.search(schema["pattern"], instance) is None:
                self.error("schema.pattern", pointer, f"string does not match {schema['pattern']!r}")
        elif isinstance(instance, (int, float)) and not isinstance(instance, bool):
            if "minimum" in schema and instance < schema["minimum"]:
                self.error("schema.minimum", pointer, f"value must be at least {schema['minimum']}")
            if "maximum" in schema and instance > schema["maximum"]:
                self.error("schema.maximum", pointer, f"value must be at most {schema['maximum']}")

    def _validate_object(
        self, instance: dict[str, Any], schema: dict[str, Any], pointer: str,
        base_schema: dict[str, Any] | None, base_path: Path | None,
    ) -> None:
        properties = schema.get("properties", {})
        patterns = schema.get("patternProperties", {})
        for key in schema.get("required", []):
            if key not in instance:
                self.error("schema.required", join_pointer(pointer, key), "required field is missing")
        for key, value in instance.items():
            child_pointer = join_pointer(pointer, key)
            matched = False
            if key in properties:
                matched = True
                self.descend(value, properties[key], child_pointer, base_schema, base_path)
            for pattern, child_schema in patterns.items():
                if re.search(pattern, key):
                    matched = True
                    self.descend(value, child_schema, child_pointer, base_schema, base_path)
            if not matched and "additionalProperties" in schema:
                additional = schema["additionalProperties"]
                if additional is False:
                    self.error("schema.additionalProperties", child_pointer, "unknown field is not allowed")
                elif isinstance(additional, dict):
                    self.descend(value, additional, child_pointer, base_schema, base_path)

    def _validate_array(
        self, instance: list[Any], schema: dict[str, Any], pointer: str,
        base_schema: dict[str, Any] | None, base_path: Path | None,
    ) -> None:
        if "minItems" in schema and len(instance) < schema["minItems"]:
            self.error("schema.minItems", pointer, f"array must contain at least {schema['minItems']} items")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            self.error("schema.maxItems", pointer, f"array must contain at most {schema['maxItems']} items")
        if schema.get("uniqueItems"):
            encoded = [json.dumps(value, sort_keys=True, separators=(",", ":")) for value in instance]
            if len(encoded) != len(set(encoded)):
                self.error("schema.uniqueItems", pointer, "array items must be unique")
        if "items" in schema:
            for index, value in enumerate(instance):
                self.descend(value, schema["items"], join_pointer(pointer, index), base_schema, base_path)


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _matches_type(value: Any, expected: str | list[str]) -> bool:
    names = [expected] if isinstance(expected, str) else expected
    actual = _json_type(value)
    return actual in names or (actual == "integer" and "number" in names)


def validate_schema(
    instance: Any,
    schema: str | Path | dict[str, Any] | bool,
    registry: SchemaRegistry,
) -> tuple[Diagnostic, ...]:
    """Validate an instance offline and return all independent failures in stable order.

    ``schema`` may be a bundled relative path or an inline schema. Unsafe schema references
    raise ``SchemaError`` because they invalidate the contract itself, not the caller's data.
    """

    if isinstance(schema, (str, Path)):
        loaded, schema_path = registry.load(schema)
        root_schema: dict[str, Any] | None = loaded
    else:
        registry.lint_schema(schema)
        loaded, schema_path = schema, None
        root_schema = schema if isinstance(schema, dict) else None
    validator = _Validator(registry)
    validator.validate(instance, loaded, "", root_schema, schema_path)
    return sort_diagnostics(validator.diagnostics)
