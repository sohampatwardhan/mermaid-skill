"""Legacy render tests for type group 4 (structure).

Task 7.4 replaces these with fixtures and tests/test_builders.py, then deletes this file.
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


class RequirementLinksTests(unittest.TestCase):
    def test_traceability_renders(self) -> None:
        ir = {
            "diagram": "requirement-links", "target": "requirementDiagram", "direction": "LR",
            "requirements": [
                {"id": "req_1_1", "text": "the system shall rotate tokens", "risk": "high",
                 "verify_method": "test", "type": "functionalRequirement"},
            ],
            "elements": [{"id": "session_module", "type": "component"}],
            "links": [{"from": "session_module", "to": "req_1_1", "kind": "satisfies"}],
        }
        source = render_validated(ir)
        self.assertIn("requirementDiagram", source)
        self.assertIn("direction LR", source)
        self.assertIn("satisfies", source)

    def test_unknown_link_kind_is_rejected(self) -> None:
        ir = {
            "diagram": "requirement-links", "target": "requirementDiagram",
            "requirements": [{"id": "r1", "text": "text"}],
            "elements": [{"id": "e1", "type": "component"}],
            "links": [{"from": "e1", "to": "r1", "kind": "implies"}],
        }
        with self.assertRaises(ValueError):
            render_module.render(ir)


class GraphBlockTests(unittest.TestCase):
    def test_shapes_group_and_edges_render(self) -> None:
        ir = {
            "diagram": "graph", "target": "block", "columns": 3,
            "groups": [{"id": "grp-1", "label": "Group One"}],
            "nodes": [
                {"id": "a", "label": "process", "kind": "process"},
                {"id": "b", "label": "terminator", "kind": "terminator"},
                {"id": "c", "label": "decision", "kind": "decision"},
                {"id": "d", "label": "subprocess", "kind": "subprocess", "group": "grp-1"},
                {"id": "e", "label": "store", "kind": "store", "group": "grp-1"},
                {"id": "f", "label": "connector", "kind": "connector"},
                {"id": "g", "label": "io", "kind": "io"},
            ],
            "edges": [
                {"from": "a", "to": "b", "label": "next"},
                {"from": "grp-1", "to": "f", "kind": "dependency"},
            ],
        }
        source = render_validated(ir)
        self.assertIn("block", source)
        self.assertIn("columns 3", source)
        self.assertIn("block:n_grp_1", source)
        self.assertIn('-- "next" -->', source)

    def test_unknown_kind_is_rejected(self) -> None:
        ir = {
            "diagram": "graph", "target": "block",
            "nodes": [{"id": "a", "label": "A", "kind": "wat"}], "edges": [],
        }
        with self.assertRaises(ValueError):
            render_module.render(ir)

    def test_unknown_edge_kind_is_rejected(self) -> None:
        ir = {
            "diagram": "graph", "target": "block",
            "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "edges": [{"from": "a", "to": "b", "kind": "strong"}],
        }
        with self.assertRaises(ValueError):
            render_module.render(ir)

    def test_undeclared_edge_target_is_rejected(self) -> None:
        ir = {
            "diagram": "graph", "target": "block",
            "nodes": [{"id": "a", "label": "A"}],
            "edges": [{"from": "a", "to": "ghost"}],
        }
        with self.assertRaises(ValueError):
            render_module.render(ir)


class GraphC4Tests(unittest.TestCase):
    def test_context_boundaries_and_rels_render(self) -> None:
        ir = {
            "diagram": "graph", "target": "C4Context", "title": "Banking System",
            "groups": [{"id": "b0", "label": "Bank Boundary", "kind": "enterprise_boundary"}],
            "nodes": [
                {"id": "customerA", "label": "Customer A", "kind": "person",
                 "description": "A bank customer", "group": "b0"},
                {"id": "customerC", "label": "Customer C", "kind": "person_ext", "group": "b0"},
                {"id": "sysAA", "label": "Banking System", "kind": "system",
                 "description": "Core system"},
                {"id": "sysDb", "label": "Mainframe", "kind": "system_db_ext"},
            ],
            "edges": [
                {"from": "customerA", "to": "sysAA", "label": "Uses", "kind": "birel"},
                {"from": "sysAA", "to": "sysDb", "label": "Reads", "technology": "SOAP"},
            ],
        }
        source = render_validated(ir)
        self.assertIn("C4Context", source)
        self.assertIn("Enterprise_Boundary(b0,", source)
        self.assertIn("Person(customerA,", source)
        self.assertIn("Person_Ext(customerC,", source)
        self.assertIn("BiRel(customerA, sysAA,", source)

    def test_container_diagram_renders(self) -> None:
        ir = {
            "diagram": "graph", "target": "C4Container",
            "nodes": [
                {"id": "customer", "label": "Customer", "kind": "person"},
                {"id": "spa", "label": "SPA", "kind": "container", "technology": "JS",
                 "description": "Web UI", "group": "c1"},
                {"id": "db", "label": "Database", "kind": "container_db", "technology": "SQL",
                 "group": "c1"},
            ],
            "groups": [{"id": "c1", "label": "Internet Banking", "kind": "container_boundary"}],
            "edges": [
                {"from": "customer", "to": "spa", "label": "Uses", "technology": "HTTPS"},
                {"from": "spa", "to": "db", "label": "Reads/Writes"},
            ],
        }
        source = render_validated(ir)
        self.assertIn("C4Container", source)
        self.assertIn("Container_Boundary(c1,", source)
        self.assertIn("Container(spa, \"SPA\", \"JS\", \"Web UI\")", source)

    def test_container_kind_in_context_is_rejected(self) -> None:
        ir = {
            "diagram": "graph", "target": "C4Context",
            "nodes": [{"id": "spa", "label": "SPA", "kind": "container"}], "edges": [],
        }
        with self.assertRaises(ValueError):
            render_module.render(ir)

    def test_undeclared_target_is_rejected(self) -> None:
        ir = {
            "diagram": "graph",
            "nodes": [{"id": "a", "label": "A", "kind": "system"}], "edges": [],
        }
        with self.assertRaises(ValueError):
            render_module.render(ir)


class GraphArchitectureTests(unittest.TestCase):
    def test_groups_services_junction_and_edges_render(self) -> None:
        ir = {
            "diagram": "graph", "target": "architecture-beta",
            "groups": [{"id": "api", "label": "API", "icon": "cloud"}],
            "nodes": [
                {"id": "db", "label": "Database", "kind": "service", "icon": "database", "group": "api"},
                {"id": "server", "label": "Server", "kind": "service", "icon": "server", "group": "api"},
                {"id": "disk1", "label": "Storage", "kind": "service", "icon": "disk"},
                {"id": "j1", "kind": "junction"},
            ],
            "edges": [
                {"from": "db", "to": "server", "from_side": "L", "to_side": "R"},
                {"from": "disk1", "to": "j1", "from_side": "T", "to_side": "B", "arrow": "forward"},
            ],
        }
        source = render_validated(ir)
        self.assertIn("architecture-beta", source)
        self.assertIn("group api(cloud)", source)
        self.assertIn("service db(database)", source)
        self.assertIn("junction j1", source)
        self.assertIn("db:L -- R:server", source)
        self.assertIn("disk1:T -->", source)

    def test_custom_icon_pack_is_allowed(self) -> None:
        ir = {
            "diagram": "graph", "target": "architecture-beta",
            "nodes": [
                {"id": "a", "label": "A", "icon": "logos:aws-lambda"},
                {"id": "b", "label": "B", "icon": "logos:aws-s3"},
            ],
            "edges": [{"from": "a", "to": "b", "from_side": "R", "to_side": "L"}],
        }
        source = render_validated(ir)
        self.assertIn("logos:aws-lambda", source)

    def test_unknown_icon_is_rejected(self) -> None:
        ir = {
            "diagram": "graph", "target": "architecture-beta",
            "nodes": [{"id": "a", "label": "A", "icon": "made-up-icon"}], "edges": [],
        }
        with self.assertRaises(ValueError):
            render_module.render(ir)

    def test_junction_with_label_is_rejected(self) -> None:
        ir = {
            "diagram": "graph", "target": "architecture-beta",
            "nodes": [{"id": "j1", "kind": "junction", "label": "nope"}], "edges": [],
        }
        with self.assertRaises(ValueError):
            render_module.render(ir)

    def test_undeclared_edge_side_is_rejected(self) -> None:
        ir = {
            "diagram": "graph", "target": "architecture-beta",
            "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "edges": [{"from": "a", "to": "b", "from_side": "NE", "to_side": "L"}],
        }
        with self.assertRaises(ValueError):
            render_module.render(ir)


class C4VariantTests(unittest.TestCase):
    def test_component_and_deployment_render(self) -> None:
        component = {
            "diagram": "graph", "target": "C4Component", "title": "API",
            "groups": [{"id": "api", "label": "API", "kind": "container_boundary"}],
            "nodes": [{
                "id": "sign", "label": "Sign In", "kind": "component",
                "technology": "MVC", "description": "Auth", "group": "api",
            }],
            "edges": [],
        }
        source = render_validated(component)
        self.assertIn("C4Component", source)
        self.assertIn("Component(sign, \"Sign In\", \"MVC\", \"Auth\")", source)
        dynamic = {
            "diagram": "graph", "target": "C4Dynamic",
            "nodes": [
                {"id": "c1", "label": "SPA", "kind": "container", "technology": "JS", "description": "UI"},
                {"id": "c2", "label": "Auth", "kind": "component", "technology": "Spring", "description": "Checks"},
            ],
            "edges": [{"from": "c1", "to": "c2", "label": "Calls", "kind": "rel_index", "index": 1}],
        }
        source = render_validated(dynamic)
        self.assertIn("RelIndex(1, c1, c2,", source)
        deployment = {
            "diagram": "graph", "target": "C4Deployment", "title": "Live",
            "groups": [{
                "id": "mob", "label": "Phone", "kind": "deployment_node", "technology": "iOS",
            }],
            "nodes": [{
                "id": "app", "label": "App", "kind": "container", "technology": "Xamarin",
                "description": "Mobile", "group": "mob",
            }],
            "edges": [],
        }
        source = render_validated(deployment)
        self.assertIn("Deployment_Node(mob, \"Phone\", \"iOS\")", source)


class CatalogRenderTests(unittest.TestCase):
    CASES = [   (   {   'diagram': 'packet',
                'target': 'packet',
                'fields': [   {'start': 0, 'end': 15, 'label': 'Source Port'},
                              {'start': 16, 'end': 31, 'label': 'Destination Port'}]},
            'packet',
            '0-15:')]

    def test_data_diagrams_render(self) -> None:
        for ir, keyword, snippet in self.CASES:
            with self.subTest(target=ir["target"]):
                source = render_validated(ir)
                self.assertIn(keyword, source)
                self.assertIn(snippet, source)

    CLOSED = [   {   'diagram': 'packet',
            'target': 'packet',
            'fields': [{'start': 0, 'end': 7, 'label': 'A'}, {'start': 16, 'end': 31, 'label': 'B'}]},
        {'diagram': 'packet', 'target': 'packet', 'fields': [{'start': 8, 'end': 15, 'label': 'A'}]}]

    def test_closed_failures(self) -> None:
        for ir in self.CLOSED:
            with self.subTest(target=ir["target"]):
                with self.assertRaises(ValueError):
                    render_module.render(ir)


if __name__ == "__main__":
    unittest.main()
