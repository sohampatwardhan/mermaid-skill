"""Contract tests for the cynefin-beta target."""

import copy
import json
import unittest
from pathlib import Path

from scripts.mermaid_ir.compiler import compile_ir
from scripts.mermaid_ir.model import IRError
from scripts.mermaid_ir.registry import clear_targets, register_target
from scripts.mermaid_ir.targets.cynefin_beta import SPEC

ROOT = Path(__file__).resolve().parents[2]


class CynefinBetaTests(unittest.TestCase):
    def setUp(self):
        clear_targets(); register_target(SPEC)

    def load(self, name):
        return json.loads((ROOT / "examples" / "cynefin-beta" / name).read_text())

    def test_minimal(self):
        result = compile_ir(self.load("minimal.json"))
        self.assertTrue(result.source.startswith("cynefin-beta"))

    def test_maximal_renders_domains_items_and_transitions(self):
        source = compile_ir(self.load("maximal.json")).source
        self.assertIn("title Incident Response", source)
        self.assertIn("accTitle: Cynefin framework for software delivery decisions", source)
        self.assertIn("complex", source)
        self.assertIn('"Investigate root cause"', source)
        self.assertIn('complex --> complicated : "Pattern identified"', source)

    def test_deterministic(self):
        document = self.load("maximal.json")
        before = copy.deepcopy(document)
        self.assertEqual(compile_ir(document).source, compile_ir(document).source)
        self.assertEqual(document, before)

    def test_unknown_content_is_rejected(self):
        document = self.load("minimal.json"); document["content"]["unknown"] = True
        with self.assertRaises(IRError):
            compile_ir(document)

    def test_unknown_domain_name_is_rejected(self):
        document = self.load("minimal.json")
        document["content"]["domains"] = [{"domain": "bogus"}]
        with self.assertRaises(IRError):
            compile_ir(document)

    def test_duplicate_domain_is_rejected(self):
        document = self.load("minimal.json")
        document["content"]["domains"] = [{"domain": "complex"}, {"domain": "complex"}]
        with self.assertRaises(IRError):
            compile_ir(document)

    def test_unknown_transition_domain_is_rejected(self):
        document = self.load("minimal.json")
        document["content"]["transitions"] = [{"from": "complex", "to": "bogus"}]
        with self.assertRaises(IRError):
            compile_ir(document)


if __name__ == "__main__":
    unittest.main()
