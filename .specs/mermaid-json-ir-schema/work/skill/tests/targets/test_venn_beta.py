"""Contract tests for the venn-beta target."""

import copy
import json
import unittest
from pathlib import Path

from scripts.mermaid_ir.compiler import compile_ir
from scripts.mermaid_ir.model import IRError
from scripts.mermaid_ir.registry import clear_targets, register_target
from scripts.mermaid_ir.targets.venn_beta import SPEC

ROOT = Path(__file__).resolve().parents[2]


class VennBetaTests(unittest.TestCase):
    def setUp(self):
        clear_targets(); register_target(SPEC)

    def load(self, name):
        return json.loads((ROOT / "examples" / "venn-beta" / name).read_text())

    def test_minimal(self):
        result = compile_ir(self.load("minimal.json"))
        self.assertTrue(result.source.startswith("venn-beta"))
        self.assertIn("set A", result.source)
        self.assertIn("set B", result.source)

    def test_maximal_renders_labels_sizes_texts_and_unions(self):
        source = compile_ir(self.load("maximal.json")).source
        self.assertIn('set A["Frontend"]:20', source)
        self.assertIn('text A1["React"]', source)
        self.assertIn('union A,B["Shared"]:3', source)
        self.assertIn('union A,B,C["Innovation"]', source)
        self.assertIn("title Team overlap", source)

    def test_deterministic(self):
        document = self.load("maximal.json")
        before = copy.deepcopy(document)
        self.assertEqual(compile_ir(document).source, compile_ir(document).source)
        self.assertEqual(document, before)

    def test_unknown_content_is_rejected(self):
        document = self.load("minimal.json"); document["content"]["unknown"] = True
        with self.assertRaises(IRError):
            compile_ir(document)

    def test_union_referencing_undeclared_set_is_rejected(self):
        document = self.load("minimal.json")
        document["content"]["unions"] = [{"ids": ["A", "missing"]}]
        with self.assertRaises(IRError):
            compile_ir(document)

    def test_duplicate_set_id_is_rejected(self):
        document = self.load("minimal.json")
        document["content"]["sets"].append({"id": "A"})
        with self.assertRaises(IRError):
            compile_ir(document)


if __name__ == "__main__":
    unittest.main()
