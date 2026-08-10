"""Render each IR family to Mermaid and render-validate the exact output via check.sh.

Mirrors the skill's own hard rule ("validate by rendering") applied to generated, not just
hand-authored, source: a generator that produces syntactically invalid Mermaid is exactly the
kind of caller mistake `check.sh` exists to catch. Coverage here also doubles as the feature-
parity contract for render.py: every branch of every family gets at least one real render.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
CHECK = SKILL_DIR / "scripts" / "check.sh"
SPEC = importlib.util.spec_from_file_location("render", SKILL_DIR / "scripts" / "render.py")
assert SPEC is not None and SPEC.loader is not None
render_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render_module)


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


class GraphFlowchartTests(unittest.TestCase):
    def test_stages_groups_and_shapes_render(self) -> None:
        ir = {
            "diagram": "graph",
            "target": "flowchart",
            "direction": "TD",
            "groups": [{"id": "stage-1", "label": "Stage 1"}, {"id": "stage-2", "label": "Stage 2"}],
            "nodes": [
                {"id": "start", "label": "Begin", "kind": "terminator", "group": "stage-1"},
                {"id": "1.1", "label": "1.1 Session rotation", "kind": "process", "group": "stage-1"},
                {"id": "decide", "label": "Needs review?", "kind": "decision", "group": "stage-1"},
                {"id": "1.3", "label": "1.3 Integration test", "kind": "subprocess", "group": "stage-2"},
                {"id": "log", "label": "Audit log", "kind": "store", "group": "stage-2"},
            ],
            "edges": [
                {"from": "start", "to": "1.1", "kind": "normal"},
                {"from": "1.1", "to": "decide", "kind": "normal"},
                {"from": "decide", "to": "1.3", "kind": "dependency", "label": "yes"},
                {"from": "1.3", "to": "log", "kind": "weak"},
            ],
        }
        source = render_validated(ir)
        self.assertIn("flowchart TD", source)
        self.assertIn("shape: stadium", source)
        self.assertIn("shape: diamond", source)
        self.assertIn("shape: subproc", source)
        self.assertIn("shape: cyl", source)
        self.assertIn("subgraph", source)

    def test_undeclared_edge_target_is_rejected(self) -> None:
        ir = {
            "diagram": "graph", "target": "flowchart",
            "nodes": [{"id": "A", "label": "A"}],
            "edges": [{"from": "A", "to": "B"}],
        }
        with self.assertRaises(ValueError):
            render_module.render(ir)

    def test_status_colors_render_and_only_used_statuses_get_classdefs(self) -> None:
        ir = {
            "diagram": "graph", "target": "flowchart",
            "nodes": [
                {"id": "1.1", "label": "Done task", "status": "done"},
                {"id": "2.1", "label": "Ready task", "status": "ready"},
                {"id": "3.1", "label": "Untracked task"},
            ],
            "edges": [{"from": "1.1", "to": "2.1"}, {"from": "2.1", "to": "3.1"}],
        }
        source = render_validated(ir)
        self.assertIn("classDef done", source)
        self.assertIn("classDef ready", source)
        self.assertNotIn("classDef blocked", source)
        self.assertNotIn("classDef pending", source)
        self.assertIn("class n_1_1 done", source)
        self.assertIn("class n_2_1 ready", source)
        self.assertNotIn("class n_3_1", source)

    def test_unknown_status_is_rejected(self) -> None:
        ir = {
            "diagram": "graph", "target": "flowchart",
            "nodes": [{"id": "A", "label": "A", "status": "in_progress"}],
            "edges": [],
        }
        with self.assertRaises(ValueError):
            render_module.render(ir)

    def test_unknown_direction_is_rejected(self) -> None:
        ir = {"diagram": "graph", "target": "flowchart", "direction": "DIAGONAL", "nodes": [], "edges": []}
        with self.assertRaises(ValueError):
            render_module.render(ir)


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


class StateMachineTests(unittest.TestCase):
    def test_lifecycle_renders(self) -> None:
        ir = {
            "diagram": "state-machine", "target": "stateDiagram-v2",
            "initial": "Draft", "final": ["Rejected"],
            "transitions": [
                {"from": "Draft", "to": "Approved", "label": "user approves"},
                {"from": "Draft", "to": "Rejected", "label": "user rejects"},
            ],
        }
        source = render_validated(ir)
        self.assertIn("[*] --> Draft", source)
        self.assertIn("Rejected --> [*]", source)

    def test_composite_state_and_choice_pseudostate_render(self) -> None:
        ir = {
            "diagram": "state-machine", "target": "stateDiagram-v2", "direction": "LR",
            "initial": "Outer",
            "states": [
                {"id": "Outer", "states": [{"id": "Inner"}], "initial": "Inner", "final": ["Inner"],
                 "transitions": []},
                {"id": "choice1", "kind": "choice"},
            ],
            "transitions": [
                {"from": "Outer", "to": "choice1"},
                {"from": "choice1", "to": "Done", "label": "ok"},
                {"from": "choice1", "to": "Failed", "label": "bad"},
            ],
            "notes": [{"state": "Outer", "side": "right", "text": "entry point"}],
        }
        source = render_validated(ir)
        self.assertIn("direction LR", source)
        self.assertIn("state Outer {", source)
        self.assertIn("<<choice>>", source)
        self.assertIn("note right of Outer", source)

    def test_unknown_kind_is_rejected(self) -> None:
        ir = {
            "diagram": "state-machine", "target": "stateDiagram-v2",
            "states": [{"id": "s1", "kind": "wat"}], "transitions": [],
        }
        with self.assertRaises(ValueError):
            render_module.render(ir)


class SequenceTests(unittest.TestCase):
    def test_message_exchange_renders(self) -> None:
        ir = {
            "diagram": "sequence", "target": "sequenceDiagram",
            "actors": [{"id": "User"}, {"id": "API"}, {"id": "DB", "kind": "actor"}],
            "steps": [
                {"type": "message", "from": "User", "to": "API", "label": "request", "kind": "sync"},
                {"type": "message", "from": "API", "to": "DB", "label": "query", "kind": "sync"},
                {"type": "message", "from": "DB", "to": "API", "label": "result", "kind": "reply"},
            ],
        }
        source = render_validated(ir)
        self.assertIn("sequenceDiagram", source)
        self.assertIn("User->>API: request", source)

    def test_activation_notes_and_control_blocks_render(self) -> None:
        ir = {
            "diagram": "sequence", "target": "sequenceDiagram",
            "actors": [{"id": "User"}, {"id": "API"}],
            "steps": [
                {"type": "activate", "actor": "API"},
                {"type": "loop", "label": "Every retry", "steps": [
                    {"type": "message", "from": "User", "to": "API", "label": "ping", "kind": "async"},
                ]},
                {"type": "alt", "branches": [
                    {"label": "success", "steps": [
                        {"type": "message", "from": "API", "to": "User", "label": "ok", "kind": "reply"},
                    ]},
                    {"label": "failure", "steps": [
                        {"type": "message", "from": "API", "to": "User", "label": "error", "kind": "cross"},
                    ]},
                ]},
                {"type": "note", "position": "right_of", "actors": ["API"], "text": "done"},
                {"type": "deactivate", "actor": "API"},
            ],
        }
        source = render_validated(ir)
        self.assertIn("activate API", source)
        self.assertIn("loop Every retry", source)
        self.assertIn("alt success", source)
        self.assertIn("else failure", source)
        self.assertIn("Note right of API: done", source)
        self.assertIn("deactivate API", source)

    def test_par_rect_and_critical_blocks_render(self) -> None:
        ir = {
            "diagram": "sequence", "target": "sequenceDiagram",
            "actors": [{"id": "Svc"}, {"id": "DB"}, {"id": "Cache"}],
            "steps": [
                {"type": "rect", "color": "rgb(200, 150, 255)", "steps": [
                    {"type": "par", "branches": [
                        {"label": "warm cache", "steps": [
                            {"type": "message", "from": "Svc", "to": "Cache", "label": "warm"},
                        ]},
                        {"label": "log start", "steps": [
                            {"type": "message", "from": "Svc", "to": "DB", "label": "log"},
                        ]},
                    ]},
                ]},
                {"type": "critical", "branches": [
                    {"label": "connect to DB", "steps": [
                        {"type": "message", "from": "Svc", "to": "DB", "label": "connect"},
                    ]},
                    {"label": "network timeout", "steps": [
                        {"type": "message", "from": "Svc", "to": "Svc", "label": "log error"},
                    ]},
                ]},
            ],
        }
        source = render_validated(ir)
        self.assertIn("rect rgb(200, 150, 255)", source)
        self.assertIn("par warm cache", source)
        self.assertIn("and log start", source)
        self.assertIn("critical connect to DB", source)
        self.assertIn("option network timeout", source)

    def test_undeclared_actor_is_rejected(self) -> None:
        ir = {
            "diagram": "sequence", "target": "sequenceDiagram",
            "actors": [{"id": "User"}],
            "steps": [{"type": "message", "from": "User", "to": "Ghost", "label": "hi"}],
        }
        with self.assertRaises(ValueError):
            render_module.render(ir)

    def test_unknown_step_type_is_rejected(self) -> None:
        ir = {
            "diagram": "sequence", "target": "sequenceDiagram",
            "actors": [{"id": "User"}],
            "steps": [{"type": "teleport", "actor": "User"}],
        }
        with self.assertRaises(ValueError):
            render_module.render(ir)


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
                {"from": "grp-1", "to": "f"},
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


class GraphErTests(unittest.TestCase):
    def test_entities_attributes_alias_and_cardinality_render(self) -> None:
        ir = {
            "diagram": "graph", "target": "erDiagram", "direction": "LR",
            "nodes": [
                {"id": "CUSTOMER", "members": ["string name PK", "string sector"]},
                {"id": "ORDER", "members": ['int orderNumber PK "the order number"']},
                {"id": "p", "label": "Customer Account"},
            ],
            "edges": [
                {"from": "CUSTOMER", "to": "ORDER", "label": "places",
                 "left": "exactly_one", "right": "zero_or_more"},
                {"from": "CUSTOMER", "to": "p", "label": "links",
                 "left": "zero_or_more", "right": "zero_or_more", "identifying": False},
            ],
        }
        source = render_validated(ir)
        self.assertIn("erDiagram", source)
        self.assertIn("direction LR", source)
        self.assertIn('p["Customer Account"]', source)
        self.assertIn("CUSTOMER ||--o{ ORDER : places", source)
        self.assertIn("CUSTOMER }o..o{ p : links", source)
        self.assertIn("string name PK", source)

    def test_unknown_cardinality_is_rejected(self) -> None:
        ir = {
            "diagram": "graph", "target": "erDiagram",
            "nodes": [{"id": "A"}, {"id": "B"}],
            "edges": [{"from": "A", "to": "B", "label": "x", "left": "lots", "right": "exactly_one"}],
        }
        with self.assertRaises(ValueError):
            render_module.render(ir)

    def test_undeclared_entity_is_rejected(self) -> None:
        ir = {
            "diagram": "graph", "target": "erDiagram",
            "nodes": [{"id": "A"}],
            "edges": [{"from": "A", "to": "GHOST", "label": "x",
                       "left": "exactly_one", "right": "exactly_one"}],
        }
        with self.assertRaises(ValueError):
            render_module.render(ir)


class GraphClassTests(unittest.TestCase):
    def test_members_annotations_and_relations_render(self) -> None:
        ir = {
            "diagram": "graph", "target": "classDiagram",
            "nodes": [
                {"id": "Animal", "members": ["+int age", "+isMammal()"]},
                {"id": "Duck", "kind": "interface", "members": ["+String beakColor", "+swim()"]},
                {"id": "Customer"},
                {"id": "Ticket"},
            ],
            "edges": [
                {"from": "Animal", "to": "Duck", "kind": "inheritance", "label": "implements"},
                {"from": "Customer", "to": "Ticket", "kind": "association",
                 "from_card": "1", "to_card": "*"},
            ],
        }
        source = render_validated(ir)
        self.assertIn("classDiagram", source)
        self.assertIn("<<Interface>>", source)
        self.assertIn("+isMammal()", source)
        self.assertIn("Animal <|-- Duck : implements", source)
        self.assertIn('Customer "1" --> "*" Ticket', source)

    def test_unknown_edge_kind_is_rejected(self) -> None:
        ir = {
            "diagram": "graph", "target": "classDiagram",
            "nodes": [{"id": "A"}, {"id": "B"}],
            "edges": [{"from": "A", "to": "B", "kind": "orbits"}],
        }
        with self.assertRaises(ValueError):
            render_module.render(ir)

    def test_unknown_node_kind_is_rejected(self) -> None:
        ir = {
            "diagram": "graph", "target": "classDiagram",
            "nodes": [{"id": "A", "kind": "widget"}], "edges": [],
        }
        with self.assertRaises(ValueError):
            render_module.render(ir)


class DispatchTests(unittest.TestCase):
    def test_unknown_family_target_pair_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            render_module.render({"diagram": "graph", "target": "packet", "nodes": [], "edges": []})

    def test_unsupported_backend_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            render_module.render(
                {"diagram": "timeline", "target": "gantt", "dateFormat": "YYYY-MM-DD", "sections": []},
                backend="tikz",
            )


if __name__ == "__main__":
    unittest.main()
