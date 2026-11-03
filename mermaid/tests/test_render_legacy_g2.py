"""Legacy render tests for type group 2 (time and tree).

Task 7.2 replaces these with fixtures and tests/test_builders.py, then deletes this file.
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


class GraphMindmapTests(unittest.TestCase):
    def test_tree_with_shape_kinds_renders(self) -> None:
        ir = {
            "diagram": "graph", "target": "mindmap", "root": "root",
            "nodes": [
                {"id": "root", "label": "Duplicate detector"},
                {"id": "a", "label": "Approach A: embeddings", "kind": "square"},
                {"id": "b", "label": "Approach B: hashing", "kind": "cloud"},
                {"id": "c", "label": "Risk: false positives", "kind": "bang"},
            ],
            "edges": [{"from": "root", "to": "a"}, {"from": "root", "to": "b"}, {"from": "a", "to": "c"}],
        }
        source = render_validated(ir)
        self.assertIn("mindmap", source)
        self.assertIn("((Duplicate detector))", source)

    def test_unreachable_node_is_rejected(self) -> None:
        ir = {
            "diagram": "graph", "target": "mindmap", "root": "root",
            "nodes": [
                {"id": "root", "label": "Root"},
                {"id": "a", "label": "A"},
                {"id": "orphan", "label": "Dropped before"},
            ],
            "edges": [{"from": "root", "to": "a"}],
        }
        with self.assertRaises(ValueError):
            render_module.render(ir)

    def test_edge_to_undeclared_node_is_rejected(self) -> None:
        ir = {
            "diagram": "graph", "target": "mindmap", "root": "root",
            "nodes": [{"id": "root", "label": "Root"}],
            "edges": [{"from": "ghost", "to": "root"}],
        }
        with self.assertRaises(ValueError):
            render_module.render(ir)

    def test_cycle_is_rejected(self) -> None:
        ir = {
            "diagram": "graph", "target": "mindmap", "root": "a",
            "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}],
        }
        with self.assertRaises(ValueError):
            render_module.render(ir)


class TimelineGanttTests(unittest.TestCase):
    def test_tags_milestone_and_excludes_render(self) -> None:
        ir = {
            "diagram": "timeline", "target": "gantt",
            "dateFormat": "YYYY-MM-DDTHH:mm:ss", "axisFormat": "%m-%d %H:%M",
            "title": "Execution", "excludes": ["weekends"],
            "sections": [{
                "name": "Stage 1",
                "bars": [
                    {"id": "t1_1", "label": "1.1 (verified)", "start": "2026-08-09T10:00:00",
                     "end": "2026-08-09T10:14:00", "tags": ["done"]},
                    {"id": "t1_2", "label": "1.2 (critical, active)", "start": "2026-08-09T10:14:00",
                     "end": "2026-08-09T10:20:00", "tags": ["crit", "active"]},
                    {"id": "t1_3", "label": "Checkpoint reached", "start": "2026-08-09T10:20:00",
                     "end": "2026-08-09T10:20:00", "tags": ["milestone"]},
                ],
            }],
        }
        source = render_validated(ir)
        self.assertIn("excludes weekends", source)
        self.assertIn("crit, active", source)
        self.assertIn("milestone", source)

    def test_unknown_tag_is_rejected(self) -> None:
        ir = {
            "diagram": "timeline", "target": "gantt", "dateFormat": "YYYY-MM-DD",
            "sections": [{"name": "S", "bars": [
                {"id": "t1", "label": "T1", "start": "2026-01-01", "end": "2026-01-02", "tags": ["urgent"]}
            ]}],
        }
        with self.assertRaises(ValueError):
            render_module.render(ir)

    def test_colon_in_label_is_rejected(self) -> None:
        ir = {
            "diagram": "timeline", "target": "gantt", "dateFormat": "YYYY-MM-DD",
            "sections": [{"name": "S", "bars": [
                {"id": "t1", "label": "Review: security", "start": "2026-01-01", "end": "2026-01-02"}
            ]}],
        }
        with self.assertRaises(ValueError):
            render_module.render(ir)

    def test_conflicting_tags_are_rejected(self) -> None:
        ir = {
            "diagram": "timeline", "target": "gantt", "dateFormat": "YYYY-MM-DD",
            "sections": [{"name": "S", "bars": [
                {"id": "t1", "label": "T1", "start": "2026-01-01", "end": "2026-01-02",
                 "tags": ["active", "done"]}
            ]}],
        }
        with self.assertRaises(ValueError):
            render_module.render(ir)


class CatalogRenderTests(unittest.TestCase):
    CASES = [   (   {   'diagram': 'timeline',
                'target': 'timeline',
                'title': 'History',
                'sections': [   {   'name': 'Early',
                                    'events': [   {'period': '2002', 'text': ['LinkedIn']},
                                                  {   'period': '2004',
                                                      'text': ['Facebook', 'Google']}]}]},
            'timeline',
            '2004 : Facebook : Google'),
        (   {   'diagram': 'board',
                'target': 'kanban',
                'columns': [   {   'id': 'todo',
                                   'label': 'To Do',
                                   'cards': [   {   'id': 't1',
                                                    'label': 'Write spec',
                                                    'priority': 'High'}]}]},
            'kanban',
            'priority:'),
        (   {   'diagram': 'journey',
                'target': 'journey',
                'title': 'My day',
                'sections': [   {   'name': 'Work',
                                    'tasks': [{'name': 'Make tea', 'score': 5, 'actors': ['Me']}]}]},
            'journey',
            'Make tea: 5: Me'),
        (   {   'diagram': 'git',
                'target': 'gitGraph',
                'ops': [   {'type': 'commit'},
                           {'type': 'branch', 'name': 'develop'},
                           {'type': 'checkout', 'name': 'develop'},
                           {'type': 'commit'},
                           {'type': 'checkout', 'name': 'main'},
                           {'type': 'merge', 'name': 'develop'}]},
            'gitGraph',
            'merge develop')]

    def test_data_diagrams_render(self) -> None:
        for ir, keyword, snippet in self.CASES:
            with self.subTest(target=ir["target"]):
                source = render_validated(ir)
                self.assertIn(keyword, source)
                self.assertIn(snippet, source)

    CLOSED = [{'diagram': 'timeline', 'target': 'timeline', 'events': [{'period': '2004', 'text': ['A: B']}]}]

    def test_closed_failures(self) -> None:
        for ir in self.CLOSED:
            with self.subTest(target=ir["target"]):
                with self.assertRaises(ValueError):
                    render_module.render(ir)


if __name__ == "__main__":
    unittest.main()
