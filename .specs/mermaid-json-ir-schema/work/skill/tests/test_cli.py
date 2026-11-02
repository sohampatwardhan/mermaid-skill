"""CLI status and atomic output tests."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from scripts.mermaid_ir.cli import main

SKILL = Path(__file__).resolve().parents[1]

class CliTests(unittest.TestCase):
    def test_materializes_feature_bearing_canonical_example(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "sequence.json"
            self.assertEqual(main(["--example", "sequenceDiagram", "-o", str(output)]), 0)
            example = json.loads(output.read_text())
            self.assertEqual(example["schemaVersion"], "1.0.0")
            self.assertTrue(example["content"]["actors"])
            self.assertTrue(example["content"]["steps"])

    def test_json_diagnostics_point_to_invalid_field(self):
        with tempfile.TemporaryDirectory() as temp:
            invalid = Path(temp) / "invalid.json"
            document = json.loads((SKILL / "examples/flowchart/minimal.json").read_text())
            document["content"]["unknown"] = True
            invalid.write_text(json.dumps(document))
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                code = main([str(invalid), "--diagnostics-format", "json"])
            self.assertEqual(code, 1)
            payload = json.loads(errors.getvalue())
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["diagnostics"][0]["pointer"], "/content/unknown")

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
