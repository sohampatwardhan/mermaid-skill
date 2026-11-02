"""Contract tests for the treeView-beta target."""

import copy
import json
import unittest
from pathlib import Path

from scripts.mermaid_ir.compiler import compile_ir
from scripts.mermaid_ir.model import IRError
from scripts.mermaid_ir.registry import clear_targets, register_target
from scripts.mermaid_ir.targets.treeview_beta import SPEC

ROOT = Path(__file__).resolve().parents[2]


class TreeViewBetaTests(unittest.TestCase):
    def setUp(self):
        clear_targets(); register_target(SPEC)

    def load(self, name):
        return json.loads((ROOT / "examples" / "treeView-beta" / name).read_text())

    def test_minimal(self):
        result = compile_ir(self.load("minimal.json"))
        self.assertTrue(result.source.startswith("treeView-beta"))
        self.assertIn('"README.md"', result.source)

    def test_maximal_renders_directories_and_descriptions(self):
        source = compile_ir(self.load("maximal.json")).source
        self.assertIn('"my-project/"', source)
        self.assertIn('"src/"', source)
        self.assertIn('"index.js" ## app entry point', source)
        self.assertIn('"package.json" ## project manifest', source)

    def test_deterministic(self):
        document = self.load("maximal.json")
        before = copy.deepcopy(document)
        self.assertEqual(compile_ir(document).source, compile_ir(document).source)
        self.assertEqual(document, before)

    def test_unknown_content_is_rejected(self):
        document = self.load("minimal.json"); document["content"]["unknown"] = True
        with self.assertRaises(IRError):
            compile_ir(document)


if __name__ == "__main__":
    unittest.main()
