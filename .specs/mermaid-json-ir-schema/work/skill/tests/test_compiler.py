"""Pure compiler orchestration tests using a private fixture target."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mermaid_ir.compiler import _set_target_lookup, compile_ir
from mermaid_ir.model import Diagnostic, IRError
from test_normalize import _Spec as BaseSpec


class _Spec(BaseSpec):
    calls = 0

    @classmethod
    def validate_semantics(cls, document: dict):
        if document["content"].get("label") == "bad":
            return (Diagnostic("semantic.fixture", "/content/label", "bad label"),)
        return ()

    @classmethod
    def serialize(cls, document: dict) -> str:
        cls.calls += 1
        return f"flowchart TD\n  A[\"{document['content'].get('label', 'ok')}\"]\n"


class CompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        _Spec.calls = 0
        _set_target_lookup(lambda target: _Spec() if target == "fixture" else None)

    def test_compile_returns_stable_source_and_separate_initialize_config(self) -> None:
        value = {
            "schemaVersion": "1.0.0", "diagram": "graph", "target": "fixture",
            "content": {"label": "same"}, "renderer": {"deterministic": True},
        }
        first = compile_ir(value)
        second = compile_ir(value)
        self.assertEqual(first.source, second.source)
        self.assertTrue(first.initialize_config["deterministicIds"])
        self.assertEqual(len(first.initialize_config["deterministicIDSeed"]), 64)
        self.assertEqual(first.mermaid_version, "11.16.1")

    def test_structural_and_semantic_failures_do_not_serialize(self) -> None:
        with self.assertRaises(IRError):
            compile_ir({"schemaVersion": "1.0.0", "diagram": "graph", "target": "fixture", "content": {"unknown": 1}})
        with self.assertRaises(IRError):
            compile_ir({"schemaVersion": "1.0.0", "diagram": "graph", "target": "fixture", "content": {"label": "bad"}})
        self.assertEqual(_Spec.calls, 0)

    def test_unknown_target_and_backend_fail_closed(self) -> None:
        with self.assertRaises(IRError):
            compile_ir({"schemaVersion": "1.0.0", "diagram": "graph", "target": "missing", "content": {}})
        with self.assertRaises(IRError):
            compile_ir({"schemaVersion": "1.0.0", "diagram": "graph", "target": "fixture", "content": {}}, backend="tikz")


if __name__ == "__main__":
    unittest.main()
