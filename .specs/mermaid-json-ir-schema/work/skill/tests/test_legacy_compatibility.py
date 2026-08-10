"""Complete legacy corpus parity tests for the production facade."""
import json
import unittest
from pathlib import Path
from scripts.render import render

SKILL = Path(__file__).resolve().parents[1]

class LegacyCompatibilityTests(unittest.TestCase):
    def test_all_valid_goldens(self):
        root = SKILL / "tests" / "fixtures" / "legacy"
        for source in sorted(root.glob("*.mmd")):
            with self.subTest(target=source.stem):
                self.assertEqual(render(json.loads(source.with_suffix('.json').read_text())), source.read_text())
