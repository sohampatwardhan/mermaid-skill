"""Contract tests for the ishikawa-beta target."""

import copy
import json
import unittest
from pathlib import Path

from scripts.mermaid_ir.compiler import compile_ir
from scripts.mermaid_ir.model import IRError
from scripts.mermaid_ir.registry import clear_targets, register_target
from scripts.mermaid_ir.targets.ishikawa_beta import SPEC

ROOT = Path(__file__).resolve().parents[2]


class IshikawaBetaTests(unittest.TestCase):
    def setUp(self):
        clear_targets(); register_target(SPEC)

    def load(self, name):
        return json.loads((ROOT / "examples" / "ishikawa-beta" / name).read_text())

    def test_minimal(self):
        result = compile_ir(self.load("minimal.json"))
        self.assertTrue(result.source.startswith("ishikawa-beta"))
        self.assertIn("Blurry Photo", result.source)

    def test_maximal_renders_deeply_nested_causes(self):
        source = compile_ir(self.load("maximal.json")).source
        self.assertIn("    Equipment", source)
        self.assertIn("        LENS", source)
        self.assertIn("            Inappropriate lens", source)

    def test_deterministic(self):
        document = self.load("maximal.json")
        before = copy.deepcopy(document)
        self.assertEqual(compile_ir(document).source, compile_ir(document).source)
        self.assertEqual(document, before)

    def test_unknown_content_is_rejected(self):
        document = self.load("minimal.json"); document["content"]["unknown"] = True
        with self.assertRaises(IRError):
            compile_ir(document)

    def test_unbounded_nesting_is_accepted(self):
        node = {"label": "leaf"}
        for _ in range(6):
            node = {"label": "mid", "causes": [node]}
        document = self.load("minimal.json")
        document["content"]["causes"] = [node]
        source = compile_ir(document).source
        self.assertIn("leaf", source)


if __name__ == "__main__":
    unittest.main()
