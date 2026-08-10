"""Behavioral tests for the constrained offline JSON Schema runtime."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SCHEMAS = Path(__file__).resolve().parents[1] / "schema"
sys.path.insert(0, str(SCRIPTS))

from mermaid_ir.schema_runtime import SchemaError, SchemaRegistry, validate_schema


class SchemaRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = SchemaRegistry(SCHEMAS)

    def test_envelope_reports_missing_and_unknown_fields_at_json_pointers(self) -> None:
        diagnostics = validate_schema(
            {"schemaVersion": "1.0.0", "diagram": "graph", "content": {}, "extra": True},
            "envelope.schema.json",
            self.registry,
        )
        self.assertEqual([(d.code, d.pointer) for d in diagnostics], [
            ("schema.additionalProperties", "/extra"),
            ("schema.required", "/target"),
        ])

    def test_boolean_is_not_an_integer(self) -> None:
        diagnostics = validate_schema(True, {"type": "integer"}, self.registry)
        self.assertEqual(diagnostics[0].code, "schema.type")

    def test_annotations_are_allowed_but_unknown_validation_keywords_fail_lint(self) -> None:
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "example.schema.json",
            "title": "Example",
            "description": "Example contract",
            "default": {},
            "type": "object",
        }
        self.registry.lint_schema(schema)
        with self.assertRaisesRegex(SchemaError, "unsupported schema keyword"):
            self.registry.lint_schema({"type": "string", "format": "email"})

    def test_remote_and_traversing_references_are_rejected(self) -> None:
        with self.assertRaisesRegex(SchemaError, "remote"):
            validate_schema({}, {"$ref": "https://example.com/schema.json"}, self.registry)
        with self.assertRaisesRegex(SchemaError, "outside"):
            validate_schema({}, {"$ref": "../outside.json"}, self.registry)

    def test_reference_cycles_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.json").write_text(json.dumps({"$ref": "b.json"}), encoding="utf-8")
            (root / "b.json").write_text(json.dumps({"$ref": "a.json"}), encoding="utf-8")
            with self.assertRaisesRegex(SchemaError, "cycle"):
                validate_schema({}, "a.json", SchemaRegistry(root))

    def test_conditionals_oneof_arrays_and_patterns(self) -> None:
        schema = {
            "type": "object",
            "required": ["kind", "items"],
            "properties": {
                "kind": {"enum": ["a", "b"]},
                "items": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"type": "string", "pattern": "^[a-z]+$"}},
                "value": {"oneOf": [{"type": "string"}, {"type": "integer"}]},
            },
            "if": {"properties": {"kind": {"const": "a"}}},
            "then": {"required": ["value"]},
            "additionalProperties": False,
        }
        self.assertEqual(validate_schema({"kind": "a", "items": ["ok"], "value": 2}, schema, self.registry), ())
        diagnostics = validate_schema({"kind": "a", "items": ["bad!", "bad!"], "other": 1}, schema, self.registry)
        self.assertEqual([item.pointer for item in diagnostics], sorted(item.pointer for item in diagnostics))
        self.assertTrue({"schema.required", "schema.pattern", "schema.uniqueItems", "schema.additionalProperties"}.issubset({item.code for item in diagnostics}))


if __name__ == "__main__":
    unittest.main()
