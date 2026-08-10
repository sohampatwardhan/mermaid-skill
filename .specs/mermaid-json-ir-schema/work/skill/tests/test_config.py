"""Renderer source/initialization separation and determinism tests."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from mermaid_ir.config import effective_configuration
from mermaid_ir.model import IRError


class ConfigTests(unittest.TestCase):
    def test_deterministic_settings_are_stable_and_initialize_stays_separate(self) -> None:
        document = {
            "target": "flowchart", "content": {"nodes": []},
            "renderer": {"initialize": {"theme": "dark", "flowchart": {"curve": "basis"}}},
        }
        before = copy.deepcopy(document)
        first = effective_configuration(document)
        second = effective_configuration(document)
        self.assertEqual(document, before)
        self.assertEqual(first, second)
        self.assertTrue(first["initialize"]["deterministicIds"])
        self.assertEqual(len(first["initialize"]["deterministicIDSeed"]), 64)
        self.assertNotIn("initialize", first["frontmatter"])

    def test_false_deterministic_id_setting_conflicts(self) -> None:
        with self.assertRaises(IRError):
            effective_configuration({"target": "flowchart", "content": {}, "renderer": {"initialize": {"deterministicIds": False}}})

    def test_secure_frontmatter_and_wrong_version_are_rejected(self) -> None:
        with self.assertRaises(IRError):
            effective_configuration({"target": "flowchart", "content": {}, "renderer": {"frontmatter": {"config": {"securityLevel": "loose"}}}})
        with self.assertRaises(IRError):
            effective_configuration({"target": "flowchart", "content": {}, "renderer": {"mermaidVersion": "10.0.0"}})

    def test_unrelated_diagram_namespace_is_rejected(self) -> None:
        with self.assertRaises(IRError):
            effective_configuration({"target": "flowchart", "content": {}, "renderer": {"initialize": {"sequence": {"wrap": True}}}})


if __name__ == "__main__":
    unittest.main()
