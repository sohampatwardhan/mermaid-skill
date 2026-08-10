"""Registry extension boundary tests."""
import unittest
from scripts.mermaid_ir.registry import TARGETS, clear_targets
from scripts.mermaid_ir.targets import ALL_TARGETS, register_all

class ExtensibilityTests(unittest.TestCase):
    def test_all_production_targets_register(self):
        clear_targets(); register_all()
        self.assertEqual(set(TARGETS), {spec.target for spec in ALL_TARGETS})
