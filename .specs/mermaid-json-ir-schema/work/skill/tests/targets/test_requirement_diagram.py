"""Contract tests for the requirementDiagram target."""

import copy
import json
import unittest
from pathlib import Path

from scripts.mermaid_ir.compiler import compile_ir
from scripts.mermaid_ir.model import IRError
from scripts.mermaid_ir.registry import clear_targets, register_target
from scripts.mermaid_ir.targets.requirement_diagram import SPEC

ROOT = Path(__file__).resolve().parents[2]

class RequirementDiagramTests(unittest.TestCase):
    def setUp(self):
        clear_targets(); register_target(SPEC)

    def load(self, name):
        return json.loads((ROOT / "examples" / 'requirementDiagram' / name).read_text())

    def test_minimal(self):
        result = compile_ir(self.load("minimal.json"))
        self.assertTrue(result.source.startswith('requirementDiagram'))

    def test_deterministic(self):
        document = self.load("maximal.json")
        before = copy.deepcopy(document)
        self.assertEqual(compile_ir(document).source, compile_ir(document).source)
        self.assertEqual(document, before)

    def test_unknown_content_is_rejected(self):
        document = self.load("minimal.json"); document["content"]["unknown"] = True
        with self.assertRaises(IRError): compile_ir(document)

    def test_legacy_golden(self):
        legacy = json.loads((ROOT / "tests" / "fixtures" / "legacy" / 'requirementDiagram').with_suffix(".json").read_text())
        expected = (ROOT / "tests" / "fixtures" / "legacy" / 'requirementDiagram').with_suffix(".mmd").read_text()
        self.assertEqual(compile_ir(legacy).source, expected)

if __name__ == "__main__": unittest.main()
