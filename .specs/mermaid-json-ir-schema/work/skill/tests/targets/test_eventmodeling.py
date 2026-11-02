"""Contract tests for the eventmodeling target."""

import copy
import json
import unittest
from pathlib import Path

from scripts.mermaid_ir.compiler import compile_ir
from scripts.mermaid_ir.model import IRError
from scripts.mermaid_ir.registry import clear_targets, register_target
from scripts.mermaid_ir.targets.eventmodeling import SPEC

ROOT = Path(__file__).resolve().parents[2]


class EventModelingTests(unittest.TestCase):
    def setUp(self):
        clear_targets(); register_target(SPEC)

    def load(self, name):
        return json.loads((ROOT / "examples" / "eventmodeling" / name).read_text())

    def test_minimal(self):
        result = compile_ir(self.load("minimal.json"))
        self.assertTrue(result.source.startswith("eventmodeling"))
        self.assertIn("tf 01 ui CartUI", result.source)
        self.assertIn("tf 03 evt ItemAdded", result.source)

    def test_maximal_renders_reset_frames_data_and_relations(self):
        source = compile_ir(self.load("maximal.json")).source
        self.assertIn("tf 02 cmd AddItem `json`{ description: string }", source)
        self.assertIn("tf 03 evt ItemAdded [[ItemAdded]]", source)
        self.assertIn("rf 06 evt External.InventoryChanged", source)
        self.assertIn("tf 10 rmo CartUI ->> 03 ->> 05 ->> 09", source)
        self.assertIn("data AddItem02 {", source)
        self.assertIn("  description: 'jack'", source)
        self.assertIn("  price: 12.5", source)
        self.assertNotIn("accTitle", source)

    def test_deterministic(self):
        document = self.load("maximal.json")
        before = copy.deepcopy(document)
        self.assertEqual(compile_ir(document).source, compile_ir(document).source)
        self.assertEqual(document, before)

    def test_unknown_content_is_rejected(self):
        document = self.load("minimal.json"); document["content"]["unknown"] = True
        with self.assertRaises(IRError):
            compile_ir(document)

    def test_duplicate_timeframe_number_is_rejected(self):
        document = self.load("minimal.json")
        document["content"]["timeframes"].append({"number": "01", "type": "evt", "entity": "X"})
        with self.assertRaises(IRError):
            compile_ir(document)

    def test_dataref_to_unknown_block_is_rejected(self):
        document = self.load("minimal.json")
        document["content"]["timeframes"][0]["dataRef"] = "missing"
        with self.assertRaises(IRError):
            compile_ir(document)

    def test_relation_to_unknown_timeframe_is_rejected(self):
        document = self.load("minimal.json")
        document["content"]["timeframes"][0]["relations"] = ["99"]
        with self.assertRaises(IRError):
            compile_ir(document)

    def test_data_and_dataref_together_is_rejected(self):
        document = self.load("minimal.json")
        document["content"]["timeframes"][0]["data"] = [{"key": "a", "value": "b"}]
        document["content"]["timeframes"][0]["dataRef"] = "x"
        with self.assertRaises(IRError):
            compile_ir(document)


if __name__ == "__main__":
    unittest.main()
