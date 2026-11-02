"""Contract tests for the cross-cutting ELK layout renderer configuration.

`renderer.frontmatter.config.layout`/`.elk` is envelope-level (schema/config.schema.json), not
per-target, because it configures the rendering engine rather than diagram content — see
reference/elk-layout.md. Mermaid documents ELK as supported only for flowchart and
stateDiagram-v2 today, so compile_ir must fail closed for every other target.
"""

import json
import unittest
from pathlib import Path

from scripts.mermaid_ir.compiler import compile_ir
from scripts.mermaid_ir.model import IRError
from scripts.mermaid_ir.registry import clear_targets, register_target
from scripts.mermaid_ir.targets.flowchart import SPEC as FLOWCHART_SPEC
from scripts.mermaid_ir.targets.gantt import SPEC as GANTT_SPEC

ROOT = Path(__file__).resolve().parents[1]


class ElkLayoutTests(unittest.TestCase):
    def setUp(self):
        clear_targets()
        register_target(FLOWCHART_SPEC)
        register_target(GANTT_SPEC)

    def load_flowchart(self, name):
        return json.loads((ROOT / "examples" / "flowchart" / name).read_text())

    def test_elk_config_renders_into_frontmatter(self):
        document = self.load_flowchart("minimal.json")
        document["renderer"] = {
            "frontmatter": {
                "config": {
                    "layout": "elk",
                    "elk": {
                        "mergeEdges": True,
                        "nodePlacementStrategy": "LINEAR_SEGMENTS",
                        "keepEntryNodeOnTop": True,
                    },
                }
            }
        }
        source = compile_ir(document).source
        self.assertIn('"layout":"elk"', source.replace(" ", ""))
        self.assertIn('"mergeEdges":true', source.replace(" ", ""))
        self.assertTrue(source.splitlines()[0] == "---")

    def test_invalid_node_placement_strategy_is_rejected(self):
        document = self.load_flowchart("minimal.json")
        document["renderer"] = {
            "frontmatter": {"config": {"layout": "elk", "elk": {"nodePlacementStrategy": "BOGUS"}}}
        }
        with self.assertRaises(IRError):
            compile_ir(document)

    def test_elk_layout_rejected_for_unsupported_target(self):
        document = {
            "schemaVersion": "1.0.0", "diagram": "timeline", "target": "gantt",
            "content": {"dateFormat": "YYYY-MM-DD", "sections": []},
            "renderer": {"frontmatter": {"config": {"layout": "elk"}}},
        }
        with self.assertRaises(IRError) as ctx:
            compile_ir(document)
        self.assertIn("elk", str(ctx.exception).lower())

    def test_dagre_layout_is_unrestricted(self):
        document = self.load_flowchart("minimal.json")
        document["renderer"] = {"frontmatter": {"config": {"layout": "dagre"}}}
        compile_ir(document)  # must not raise


if __name__ == "__main__":
    unittest.main()
