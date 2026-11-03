"""Legacy render tests for type group 3 (chart).

Task 7.3 replaces these with fixtures and tests/test_builders.py, then deletes this file.
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
    CASES = [   (   {   'diagram': 'chart',
                'target': 'pie',
                'title': 'Pets',
                'showData': True,
                'slices': [{'label': 'Dogs', 'value': 40}, {'label': 'Cats', 'value': 20}]},
            'pie showData',
            '"Dogs"'),
        (   {   'diagram': 'chart',
                'target': 'xychart',
                'title': 'Sales',
                'xAxis': ['jan', 'feb', 'mar'],
                'yAxis': {'label': 'Revenue', 'min': 4000, 'max': 11000},
                'bar': [5000, 6000, 7500]},
            'xychart',
            'bar ['),
        (   {'diagram': 'chart', 'target': 'sankey', 'links': [{'from': 'A', 'to': 'B', 'value': 10}]},
            'sankey',
            'A,B,'),
        (   {   'diagram': 'chart',
                'target': 'quadrantChart',
                'title': 'Reach',
                'xAxis': {'left': 'Low', 'right': 'High'},
                'yAxis': {'bottom': 'Low', 'top': 'High'},
                'quadrants': {'1': 'Expand', '2': 'Promote', '3': 'Re', '4': 'Improve'},
                'points': [{'label': 'A', 'x': 0.3, 'y': 0.6}]},
            'quadrantChart',
            'quadrant-1 Expand'),
        (   {   'diagram': 'chart',
                'target': 'radar-beta',
                'axes': [{'id': 'a', 'label': 'Math'}, {'id': 'b', 'label': 'Science'}],
                'curves': [{'id': 'alice', 'label': 'Alice', 'values': [85, 90]}]},
            'radar-beta',
            'curve alice'),
        (   {   'diagram': 'chart',
                'target': 'treemap-beta',
                'nodes': [{'label': 'Category A', 'children': [{'label': 'Item A1', 'value': 10}]}]},
            'treemap-beta',
            '"Item A1"'),
        (   {   'diagram': 'chart',
                'target': 'venn-beta',
                'title': 'Overlap',
                'sets': ['Frontend', {'id': 'Backend', 'label': 'Server'}],
                'unions': [{'sets': ['Frontend', 'Backend'], 'label': 'APIs'}]},
            'venn-beta',
            'union Frontend,Backend')]

    def test_data_diagrams_render(self) -> None:
        for ir, keyword, snippet in self.CASES:
            with self.subTest(target=ir["target"]):
                source = render_validated(ir)
                self.assertIn(keyword, source)
                self.assertIn(snippet, source)

    CLOSED = [{'diagram': 'chart', 'target': 'pie', 'slices': [{'label': 'Dogs', 'value': 0}]}]

    def test_closed_failures(self) -> None:
        for ir in self.CLOSED:
            with self.subTest(target=ir["target"]):
                with self.assertRaises(ValueError):
                    render_module.render(ir)


if __name__ == "__main__":
    unittest.main()
