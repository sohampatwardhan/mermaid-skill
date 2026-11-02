"""Contract tests for the railroad-beta target."""

import copy
import json
import unittest
from pathlib import Path

from scripts.mermaid_ir.compiler import compile_ir
from scripts.mermaid_ir.model import IRError
from scripts.mermaid_ir.registry import clear_targets, register_target
from scripts.mermaid_ir.targets.railroad_beta import SPEC

ROOT = Path(__file__).resolve().parents[2]


class RailroadBetaTests(unittest.TestCase):
    def setUp(self):
        clear_targets(); register_target(SPEC)

    def load(self, name):
        return json.loads((ROOT / "examples" / "railroad-beta" / name).read_text())

    def test_minimal(self):
        result = compile_ir(self.load("minimal.json"))
        self.assertTrue(result.source.startswith("railroad-beta"))
        self.assertIn('sign = choice(terminal("+"), terminal("-")) ;', result.source)

    def test_maximal_renders_nested_constructors(self):
        source = compile_ir(self.load("maximal.json")).source
        self.assertIn("title Expression Grammar", source)
        self.assertIn('number = oneOrMore(nonterminal("digit")) ;', source)
        self.assertIn('nonterminal("term")', source)
        self.assertIn("zeroOrMore(sequence(", source)

    def test_deterministic(self):
        document = self.load("maximal.json")
        before = copy.deepcopy(document)
        self.assertEqual(compile_ir(document).source, compile_ir(document).source)
        self.assertEqual(document, before)

    def test_unknown_content_is_rejected(self):
        document = self.load("minimal.json"); document["content"]["unknown"] = True
        with self.assertRaises(IRError):
            compile_ir(document)

    def test_nonterminal_referencing_undeclared_rule_is_rejected(self):
        document = self.load("minimal.json")
        document["content"]["rules"][0]["expression"] = {"kind": "nonterminal", "name": "missing"}
        with self.assertRaises(IRError):
            compile_ir(document)

    def test_duplicate_rule_name_is_rejected(self):
        document = self.load("minimal.json")
        document["content"]["rules"].append(copy.deepcopy(document["content"]["rules"][0]))
        with self.assertRaises(IRError):
            compile_ir(document)

    def test_terminal_missing_text_is_rejected(self):
        document = self.load("minimal.json")
        document["content"]["rules"][0]["expression"] = {"kind": "terminal"}
        with self.assertRaises(IRError):
            compile_ir(document)


if __name__ == "__main__":
    unittest.main()
