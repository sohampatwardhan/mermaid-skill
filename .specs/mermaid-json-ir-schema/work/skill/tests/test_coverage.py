"""Coverage equality tests."""
import json
import tempfile
import unittest
from pathlib import Path
from scripts.mermaid_ir.coverage import check_coverage

SKILL = Path(__file__).resolve().parents[1]
INVENTORY = SKILL.parent / "inventory" / "mermaid-11.16.1"

class CoverageTests(unittest.TestCase):
    def test_inventory_and_coverage_are_exact(self):
        self.assertEqual(len(check_coverage(INVENTORY, SKILL / "coverage" / "targets")), 12)

    def test_missing_entries_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            inv = Path(temp) / "i"; cov = Path(temp) / "c"; inv.mkdir(); cov.mkdir()
            (inv / "x.json").write_text(json.dumps({"target":"x","constructs":["a"]}))
            (cov / "x.json").write_text(json.dumps({"entries":[]}))
            with self.assertRaises(ValueError): check_coverage(inv, cov)
