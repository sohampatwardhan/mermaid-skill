"""Public documentation contract checks."""
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]

class DocumentationTests(unittest.TestCase):
    def test_reference_documents_envelope_defaults_migration_and_all_examples(self):
        text = (SKILL / "reference/ir.md").read_text()
        for phrase in ["schemaVersion", "compulsory", "optional", "initialize", "Legacy flat"]:
            self.assertIn(phrase, text)
        for target in (SKILL / "coverage" / "targets").glob("*.json"):
            self.assertTrue((SKILL / "examples" / target.stem / "minimal.json").exists())
            self.assertTrue((SKILL / "examples" / target.stem / "maximal.json").exists())
