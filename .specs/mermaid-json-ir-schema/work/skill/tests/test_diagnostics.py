"""Contract tests for stable machine-readable diagnostics."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from mermaid_ir.diagnostics import escape_pointer_token, join_pointer, sort_diagnostics
from mermaid_ir.model import Diagnostic, IRError


class DiagnosticTests(unittest.TestCase):
    def test_pointer_tokens_follow_rfc6901(self) -> None:
        self.assertEqual(escape_pointer_token("a~/b"), "a~0~1b")
        self.assertEqual(join_pointer("/content", "a/b"), "/content/a~1b")

    def test_diagnostics_sort_by_pointer_code_and_message(self) -> None:
        values = (
            Diagnostic("schema.type", "/z", "second"),
            Diagnostic("schema.required", "/a", "missing"),
            Diagnostic("schema.type", "/a", "wrong"),
        )
        self.assertEqual([item.code for item in sort_diagnostics(values)], ["schema.required", "schema.type", "schema.type"])

    def test_irerror_keeps_structured_diagnostics(self) -> None:
        diagnostics = (Diagnostic("schema.required", "/target", "required"),)
        error = IRError(diagnostics)
        self.assertEqual(error.diagnostics, diagnostics)
        self.assertIn("/target", str(error))


if __name__ == "__main__":
    unittest.main()
