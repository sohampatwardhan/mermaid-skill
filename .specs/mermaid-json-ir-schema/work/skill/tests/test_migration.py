"""Legacy-to-canonical migration contract tests."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from mermaid_ir.compiler import _set_target_lookup
from mermaid_ir.migrate import migrate_legacy
from mermaid_ir.model import IRError


class _Spec:
    target = "fixture"
    legacy_fields = frozenset({"nodes", "enabled"})

    @staticmethod
    def migrate_legacy_content(ir: dict) -> dict:
        return {key: copy.deepcopy(ir[key]) for key in ("nodes", "enabled") if key in ir}


class MigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _set_target_lookup(lambda target: _Spec() if target == "fixture" else None)

    def test_documented_legacy_fields_move_to_canonical_content_without_mutation(self) -> None:
        legacy = {"diagram": "graph", "target": "fixture", "nodes": [], "enabled": False, "accTitle": "A"}
        before = copy.deepcopy(legacy)
        result = migrate_legacy(legacy, None)
        self.assertEqual(legacy, before)
        self.assertEqual(result["schemaVersion"], "1.0.0")
        self.assertEqual(result["content"], {"nodes": [], "enabled": False})
        self.assertEqual(result["accessibility"], {"title": "A"})

    def test_unmapped_root_field_fails_at_its_pointer(self) -> None:
        with self.assertRaises(IRError) as raised:
            migrate_legacy({"diagram": "graph", "target": "fixture", "nodes": [], "extra": 1}, None)
        self.assertEqual(raised.exception.diagnostics[0].pointer, "/extra")

    def test_canonical_document_is_copied_and_override_conflict_fails(self) -> None:
        canonical = {"schemaVersion": "1.0.0", "diagram": "graph", "target": "fixture", "content": {"nodes": []}}
        self.assertIsNot(migrate_legacy(canonical, None), canonical)
        with self.assertRaises(IRError):
            migrate_legacy(canonical, "other")


if __name__ == "__main__":
    unittest.main()
