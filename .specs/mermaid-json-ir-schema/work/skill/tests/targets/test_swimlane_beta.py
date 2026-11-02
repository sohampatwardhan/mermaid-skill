"""Contract tests for the swimlane-beta target."""

import copy
import json
import unittest
from pathlib import Path

from scripts.mermaid_ir.compiler import compile_ir
from scripts.mermaid_ir.model import IRError
from scripts.mermaid_ir.registry import clear_targets, register_target
from scripts.mermaid_ir.targets.swimlane_beta import SPEC

ROOT = Path(__file__).resolve().parents[2]


class SwimlaneBetaTests(unittest.TestCase):
    def setUp(self):
        clear_targets(); register_target(SPEC)

    def load(self, name):
        return json.loads((ROOT / "examples" / "swimlane-beta" / name).read_text())

    def test_minimal(self):
        result = compile_ir(self.load("minimal.json"))
        self.assertTrue(result.source.startswith("swimlane-beta TB"))

    def test_maximal_renders_lanes_shapes_and_edges(self):
        source = compile_ir(self.load("maximal.json")).source
        self.assertIn("swimlane-beta LR", source)
        self.assertIn('subgraph customer ["Customer"]', source)
        self.assertIn('request(["Request service"])', source)
        self.assertIn('ready{"Ready to answer?"}', source)
        self.assertIn('marker(("Escalation point"))', source)
        self.assertIn("triage ---", source)
        self.assertIn('|"Known issue"|', source)
        self.assertIn("investigate ==> fix", source)
        self.assertIn("accTitle: Support escalation", source)

    def test_deterministic(self):
        document = self.load("maximal.json")
        before = copy.deepcopy(document)
        self.assertEqual(compile_ir(document).source, compile_ir(document).source)
        self.assertEqual(document, before)

    def test_unknown_content_is_rejected(self):
        document = self.load("minimal.json"); document["content"]["unknown"] = True
        with self.assertRaises(IRError):
            compile_ir(document)

    def test_edge_referencing_undeclared_node_is_rejected(self):
        document = self.load("minimal.json")
        document["content"]["nodes"] = [{"id": "a", "label": "A"}]
        document["content"]["edges"] = [{"from": "a", "to": "missing"}]
        with self.assertRaises(IRError):
            compile_ir(document)

    def test_node_referencing_undeclared_group_is_rejected(self):
        document = self.load("minimal.json")
        document["content"]["nodes"] = [{"id": "a", "label": "A", "group": "missing"}]
        with self.assertRaises(IRError):
            compile_ir(document)


if __name__ == "__main__":
    unittest.main()
