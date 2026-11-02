"""Contract tests for the wardley-beta target."""

import copy
import json
import unittest
from pathlib import Path

from scripts.mermaid_ir.compiler import compile_ir
from scripts.mermaid_ir.model import IRError
from scripts.mermaid_ir.registry import clear_targets, register_target
from scripts.mermaid_ir.targets.wardley_beta import SPEC

ROOT = Path(__file__).resolve().parents[2]


class WardleyBetaTests(unittest.TestCase):
    def setUp(self):
        clear_targets(); register_target(SPEC)

    def load(self, name):
        return json.loads((ROOT / "examples" / "wardley-beta" / name).read_text())

    def test_minimal(self):
        result = compile_ir(self.load("minimal.json"))
        self.assertTrue(result.source.startswith("wardley-beta"))
        self.assertIn("anchor Business [0.95, 0.63]", result.source)
        self.assertIn('component Cup of Tea [0.79, 0.61]', result.source)
        self.assertIn("evolve Kettle 0.62", result.source)

    def test_maximal_renders_every_construct(self):
        source = compile_ir(self.load("maximal.json")).source
        self.assertIn("size [1100, 800]", source)
        self.assertIn("evolution Genesis@0.25 -> Custom@0.5 -> Product@0.75 -> Commodity@1.0", source)
        self.assertIn('component Mobile App [0.8, 0.85] (build)', source)
        self.assertIn('component Database [0.5, 0.45] (buy) (inertia)', source)
        self.assertIn('component Web App [0.75, 0.8] label [-60, 10] (build)', source)
        self.assertIn('pipeline Database {', source)
        self.assertIn('  component "SQL DB" [0.5]', source)
        self.assertIn('Customer -> Mobile App', source)
        self.assertIn('annotations [0.1, 0.2]', source)
        self.assertIn('annotation 1,[0.78, 0.82] "User touchpoints"', source)
        self.assertIn('accelerator "Cloud Native" [0.2, 0.85]', source)
        self.assertIn('deaccelerator "Legacy Data" [0.45, 0.35]', source)
        self.assertIn('note "Build mobile-first experience" [0.85, 0.9]', source)

    def test_deterministic(self):
        document = self.load("maximal.json")
        before = copy.deepcopy(document)
        self.assertEqual(compile_ir(document).source, compile_ir(document).source)
        self.assertEqual(document, before)

    def test_unknown_content_is_rejected(self):
        document = self.load("minimal.json"); document["content"]["unknown"] = True
        with self.assertRaises(IRError):
            compile_ir(document)

    def test_link_referencing_undeclared_node_is_rejected(self):
        document = self.load("minimal.json")
        document["content"]["links"].append({"from": "Kettle", "to": "missing"})
        with self.assertRaises(IRError):
            compile_ir(document)

    def test_evolve_referencing_undeclared_node_is_rejected(self):
        document = self.load("minimal.json")
        document["content"]["evolve"].append({"id": "missing", "target": 0.5})
        with self.assertRaises(IRError):
            compile_ir(document)

    def test_duplicate_component_id_is_rejected(self):
        document = self.load("minimal.json")
        document["content"]["components"].append(document["content"]["components"][0])
        with self.assertRaises(IRError):
            compile_ir(document)

    def test_visibility_out_of_range_is_rejected(self):
        document = self.load("minimal.json")
        document["content"]["components"][0]["visibility"] = 1.5
        with self.assertRaises(IRError):
            compile_ir(document)


if __name__ == "__main__":
    unittest.main()
