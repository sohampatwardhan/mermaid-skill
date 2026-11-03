"""Legacy render tests for type group 5 (Mermaid 12 and beta).

Task 7.5 replaces these with fixtures and tests/test_builders.py, then deletes this file.
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
    CASES = [   (   {   'diagram': 'cynefin',
                'target': 'cynefin-beta',
                'title': 'Incident',
                'domains': {'complex': ['Investigate'], 'complicated': ['Analyze']},
                'transitions': [{'from': 'complex', 'to': 'complicated', 'label': 'Pattern'}]},
            'cynefin-beta',
            'complex --> complicated'),
        (   {   'diagram': 'eventmodeling',
                'target': 'eventmodeling',
                'frames': [   {'n': 1, 'kind': 'ui', 'name': 'CartUI'},
                              {'n': 2, 'kind': 'cmd', 'name': 'AddItem'}]},
            'eventmodeling',
            'tf 02 cmd AddItem')]

    def test_data_diagrams_render(self) -> None:
        for ir, keyword, snippet in self.CASES:
            with self.subTest(target=ir["target"]):
                source = render_validated(ir)
                self.assertIn(keyword, source)
                self.assertIn(snippet, source)

    VARIANTS = [   (   {   'diagram': 'graph',
                'target': 'swimlane-beta',
                'direction': 'LR',
                'groups': [   {'id': 'customer', 'label': 'Customer'},
                              {'id': 'support', 'label': 'Support'}],
                'nodes': [   {   'id': 'request',
                                 'label': 'Request',
                                 'kind': 'terminator',
                                 'group': 'customer'},
                             {'id': 'triage', 'label': 'Triage', 'group': 'support'}],
                'edges': [{'from': 'request', 'to': 'triage', 'label': 'handoff'}]},
            ['swimlane-beta LR']),
        (   {   'diagram': 'graph',
                'target': 'agentflow-beta',
                'direction': 'LR',
                'groups': [{'id': 'main', 'label': 'Main'}, {'id': 'review', 'label': 'Review'}],
                'nodes': [   {'id': 'research', 'label': 'Research', 'kind': 'task', 'group': 'main'},
                             {'id': 'write', 'label': 'Write', 'kind': 'action', 'group': 'review'}],
                'edges': [   {'from': 'research', 'to': 'write', 'kind': 'sequence', 'label': 'then'},
                             {'from': 'main', 'to': 'review', 'kind': 'sequence'}]},
            ['agentflow-beta LR', 'shape: task', 'main --> review']),
        (   {   'diagram': 'graph',
                'target': 'wardley-beta',
                'title': 'Tea',
                'nodes': [   {   'id': 'Business',
                                 'kind': 'anchor',
                                 'visibility': 0.95,
                                 'evolution': 0.63},
                             {   'id': 'CupOfTea',
                                 'kind': 'component',
                                 'visibility': 0.79,
                                 'evolution': 0.61}],
                'edges': [{'from': 'Business', 'to': 'CupOfTea'}]},
            ['wardley-beta', 'Business -> CupOfTea']),
        (   {   'diagram': 'usecase',
                'target': 'usecase-beta',
                'direction': 'LR',
                'actors': [{'id': 'User', 'label': 'Customer'}],
                'usecases': [   {'id': 'Login', 'label': 'Sign in', 'group': 'bank'},
                                {'id': 'Audit', 'label': 'Audit trail'}],
                'groups': [{'id': 'bank', 'label': 'Bank'}],
                'edges': [   {'from': 'User', 'to': 'Login', 'label': 'uses'},
                             {'from': 'Login', 'to': 'Audit', 'kind': 'include'}]},
            ['usecase-beta', '..> : include'])]

    def test_variants_render(self) -> None:
        for ir, snippets in self.VARIANTS:
            with self.subTest(target=ir["target"]):
                source = render_validated(ir)
                for snippet in snippets:
                    self.assertIn(snippet, source)


if __name__ == "__main__":
    unittest.main()
