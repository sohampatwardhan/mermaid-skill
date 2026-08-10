"""Checker contract tests that avoid external package acquisition."""
import unittest
from pathlib import Path

class RenderVerificationTests(unittest.TestCase):
    def test_checker_pins_cli_and_core_and_rejects_error_svg(self):
        text = (Path(__file__).resolve().parents[1] / "scripts/check.sh").read_text()
        self.assertIn("@mermaid-js/mermaid-cli@11.16.0", text)
        self.assertIn("11.16.1", text)
        self.assertIn("Syntax error in text", text)
