"""Legacy render tests for type group 6 (remaining).

Task 7.6 replaces these with fixtures and tests/test_builders.py, then deletes this file.
"""

from __future__ import annotations

import shutil
import subprocess
import unittest

from skill_docs import CHECK, load_render

render_module = load_render()


def render_validated(ir: dict) -> str:
    """Render the IR and, when a renderer is available, assert it renders cleanly."""
    source = render_module.render(ir)
    if shutil.which("mmdc") or shutil.which("npx"):
        result = subprocess.run(
            ["bash", str(CHECK), "-c", source],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, (
            f"generated Mermaid failed to render:\n{source}\n---\n{result.stdout}\n{result.stderr}"
        )
    return source


class CatalogRenderTests(unittest.TestCase):
    CASES = [   (   {   'diagram': 'tree',
                'target': 'treeView-beta',
                'nodes': [{'name': 'src', 'children': [{'name': 'index.ts'}]}, {'name': 'README.md'}]},
            'treeView-beta',
            'index.ts'),
        (   {   'diagram': 'tree',
                'target': 'ishikawa-beta',
                'effect': 'Blurry Photo',
                'causes': [{'label': 'Process', 'children': [{'label': 'Out of focus'}]}]},
            'ishikawa-beta',
            'Out of focus'),
        (   {   'diagram': 'grammar',
                'target': 'railroad-ebnf-beta',
                'title': 'Digit',
                'rules': ['digit = "0" | "1" ;']},
            'railroad-ebnf-beta',
            'digit = "0" | "1" ;'),
        ({'diagram': 'info', 'target': 'info'}, 'info', 'info')]

    def test_data_diagrams_render(self) -> None:
        for ir, keyword, snippet in self.CASES:
            with self.subTest(target=ir["target"]):
                source = render_validated(ir)
                self.assertIn(keyword, source)
                self.assertIn(snippet, source)

    VARIANTS = [   (   {   'diagram': 'sequence',
                'target': 'zenuml',
                'title': 'Demo',
                'actors': [{'id': 'Alice', 'kind': 'actor'}, {'id': 'John'}],
                'steps': [{'type': 'message', 'from': 'Alice', 'to': 'John', 'label': 'Hello'}]},
            ['@Actor Alice', 'Alice->John: Hello'])]

    def test_variants_render(self) -> None:
        for ir, snippets in self.VARIANTS:
            with self.subTest(target=ir["target"]):
                source = render_validated(ir)
                for snippet in snippets:
                    self.assertIn(snippet, source)

    CLOSED = [   {   'diagram': 'sequence',
            'target': 'zenuml',
            'actors': [{'id': 'A'}],
            'steps': [{'type': 'loop', 'label': 'retry', 'steps': []}]}]

    def test_closed_failures(self) -> None:
        for ir in self.CLOSED:
            with self.subTest(target=ir["target"]):
                with self.assertRaises(ValueError):
                    render_module.render(ir)


if __name__ == "__main__":
    unittest.main()
