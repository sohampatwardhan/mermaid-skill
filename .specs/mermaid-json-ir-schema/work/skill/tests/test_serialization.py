"""Shared semantic and deterministic serialization utility tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from mermaid_ir.semantic import duplicate_id_diagnostics, reference_diagnostics
from mermaid_ir.serialization import IdentifierTable, emit_preamble, quote_text


class SerializationTests(unittest.TestCase):
    def test_identifier_collisions_resolve_reproducibly(self) -> None:
        first = IdentifierTable()
        second = IdentifierTable()
        values = ["1.1", "1_1", "1.1"]
        self.assertEqual([first.safe(value) for value in values], [second.safe(value) for value in values])
        self.assertEqual(first.safe("1.1"), "n_1_1")
        self.assertEqual(first.safe("1_1"), "n_1_1_1")

    def test_text_quoting_flattens_newlines_and_escapes_quotes(self) -> None:
        self.assertEqual(quote_text('a\n"b"'), '"a #quot;b#quot;"')

    def test_preamble_orders_frontmatter_declaration_accessibility_and_title(self) -> None:
        document = {
            "target": "flowchart",
            "accessibility": {"description": "Desc", "title": "Accessible"},
            "source": {"title": "Visible"},
            "renderer": {"frontmatter": {"config": {"theme": "neutral", "flowchart": {"curve": "basis"}}}},
        }
        lines = emit_preamble(document, "flowchart TD")
        self.assertEqual(lines[0], "---")
        self.assertLess(lines.index("flowchart TD"), lines.index("accTitle: Accessible"))
        self.assertLess(lines.index("accDescr: Desc"), lines.index("title Visible"))
        self.assertIn('config: {"flowchart":{"curve":"basis"},"theme":"neutral"}', lines)

    def test_duplicate_and_reference_diagnostics_name_both_locations(self) -> None:
        items = [{"id": "a"}, {"id": "a"}]
        duplicate = duplicate_id_diagnostics(items, "/content/nodes")
        self.assertEqual(duplicate[0].pointer, "/content/nodes/1/id")
        self.assertEqual(duplicate[0].related_pointers, ("/content/nodes/0/id",))
        dangling = reference_diagnostics([{"from": "a", "to": "b"}], {"a"}, "/content/edges", ("from", "to"))
        self.assertEqual(dangling[0].pointer, "/content/edges/0/to")


if __name__ == "__main__":
    unittest.main()
