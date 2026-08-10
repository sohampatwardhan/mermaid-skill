"""CLI status and atomic output tests."""
import tempfile
import unittest
from pathlib import Path
from scripts.mermaid_ir.cli import main

SKILL = Path(__file__).resolve().parents[1]

class CliTests(unittest.TestCase):
    def test_validate_normalize_and_config_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); norm = root / "n.json"; config = root / "c.json"
            code = main([str(SKILL / "examples/flowchart/minimal.json"), "--validate-only",
                         "--normalize-out", str(norm), "--initialize-config-out", str(config)])
            self.assertEqual(code, 0); self.assertTrue(norm.exists()); self.assertTrue(config.exists())

    def test_invalid_json_is_status_two_without_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); bad = root / "bad.json"; bad.write_text("{"); out = root / "out.mmd"
            self.assertEqual(main([str(bad), "-o", str(out)]), 2); self.assertFalse(out.exists())
