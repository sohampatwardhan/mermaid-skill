"""Target registry extension and dispatch tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from mermaid_ir.registry import TARGETS, TargetSpec, clear_targets, get_target, register_target


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_targets()

    def test_target_registers_without_changing_envelope_contract(self) -> None:
        spec = TargetSpec("fixture", "graph", {}, frozenset(), lambda value: {}, lambda value: (), lambda value: "ok\n")
        register_target(spec)
        self.assertIs(get_target("fixture"), spec)
        self.assertEqual(tuple(TARGETS), ("fixture",))

    def test_duplicate_target_is_rejected(self) -> None:
        spec = TargetSpec("fixture", "graph", {}, frozenset(), lambda value: {}, lambda value: (), lambda value: "ok\n")
        register_target(spec)
        with self.assertRaisesRegex(ValueError, "already registered"):
            register_target(spec)


if __name__ == "__main__":
    unittest.main()
