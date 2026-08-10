"""Default materialization and normalization invariant tests."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from mermaid_ir.compiler import _set_target_lookup
from mermaid_ir.normalize import normalize


SCHEMA = {
    "type": "object",
    "required": ["schemaVersion", "diagram", "target", "content"],
    "properties": {
        "schemaVersion": {"const": "1.0.0"},
        "diagram": {"const": "graph"},
        "target": {"const": "fixture"},
        "content": {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean", "default": True},
                "label": {"type": "string"},
            },
            "additionalProperties": False,
        },
        "renderer": {
            "type": "object",
            "default": {},
            "properties": {"deterministic": {"type": "boolean", "default": True}},
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}


class _Spec:
    target = "fixture"
    schema = SCHEMA
    legacy_fields = frozenset({"enabled", "label"})

    @staticmethod
    def migrate_legacy_content(ir: dict) -> dict:
        return {key: copy.deepcopy(ir[key]) for key in ("enabled", "label") if key in ir}


class NormalizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _set_target_lookup(lambda target: _Spec() if target == "fixture" else None)

    def test_defaults_are_materialized_idempotently_without_mutating_input(self) -> None:
        value = {"schemaVersion": "1.0.0", "diagram": "graph", "target": "fixture", "content": {}}
        before = copy.deepcopy(value)
        first = normalize(value)
        second = normalize(first)
        self.assertEqual(value, before)
        self.assertEqual(first, second)
        self.assertEqual(first["content"]["enabled"], True)
        self.assertEqual(first["renderer"]["deterministic"], True)

    def test_optional_field_without_default_remains_absent(self) -> None:
        value = normalize({"schemaVersion": "1.0.0", "diagram": "graph", "target": "fixture", "content": {}})
        self.assertNotIn("label", value["content"])


if __name__ == "__main__":
    unittest.main()
