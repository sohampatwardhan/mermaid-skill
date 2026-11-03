# Mermaid type coverage

One row per diagram type in Mermaid 12.0.0: the cached syntax pages in [syntax/](syntax/)
(except `README.md` and `examples.md`) plus `info`, which has no syntax page. The type id is
the page's file stem and the catalog file's stem. `tests/test_coverage.py` parses this table.

- **Keywords** are the IR `target` values `render.py` accepts for the type (its `BUILDERS`
  and `HAND_AUTHOR_ONLY` keys). Other aliases are listed in the catalog file.
- **Builder** is `builder` (a kept, fully tested IR builder) or `hand-author-only`. A
  `builder` row always has Gaps `—`. `candidate` is transitional: the builder exists but has
  not been through the reliability bar yet.
- **Tests** names the test that covers the type.

CI pins `@mermaid-js/mermaid-cli@12.0.0` with Mermaid `12.0.0` on Node 22.

| Type | Keywords | Catalog | Builder | Tests | Gaps |
|---|---|---|---|---|---|
| `flowchart` | `flowchart`, `graph`, `flowchart-elk` | [flowchart.md](catalog/flowchart.md) | builder | `test_builders.py::flowchart` | — |
| `sequenceDiagram` | `sequenceDiagram` | [sequenceDiagram.md](catalog/sequenceDiagram.md) | builder | `test_builders.py::sequenceDiagram` | — |
| `classDiagram` | `classDiagram` | [classDiagram.md](catalog/classDiagram.md) | builder | `test_builders.py::classDiagram` | — |
| `stateDiagram` | `stateDiagram-v2`, `stateDiagram` | [stateDiagram.md](catalog/stateDiagram.md) | builder | `test_builders.py::stateDiagram` | — |
| `entityRelationshipDiagram` | `erDiagram` | [entityRelationshipDiagram.md](catalog/entityRelationshipDiagram.md) | builder | `test_builders.py::entityRelationshipDiagram` | — |
| `gantt` | `gantt` | [gantt.md](catalog/gantt.md) | builder | `test_builders.py::gantt` | — |
| `timeline` | `timeline` | [timeline.md](catalog/timeline.md) | builder | `test_builders.py::timeline` | — |
| `userJourney` | `journey` | [userJourney.md](catalog/userJourney.md) | builder | `test_builders.py::userJourney` | — |
| `gitgraph` | `gitGraph` | [gitgraph.md](catalog/gitgraph.md) | builder | `test_builders.py::gitgraph` | — |
| `kanban` | `kanban` | [kanban.md](catalog/kanban.md) | builder | `test_builders.py::kanban` | — |
| `mindmap` | `mindmap` | [mindmap.md](catalog/mindmap.md) | builder | `test_builders.py::mindmap` | — |
| `pie` | `pie` | [pie.md](catalog/pie.md) | builder | `test_builders.py::pie` | — |
| `quadrantChart` | `quadrantChart` | [quadrantChart.md](catalog/quadrantChart.md) | builder | `test_builders.py::quadrantChart` | — |
| `xyChart` | `xychart`, `xychart-beta` | [xyChart.md](catalog/xyChart.md) | builder | `test_builders.py::xyChart` | — |
| `sankey` | `sankey`, `sankey-beta` | [sankey.md](catalog/sankey.md) | hand-author-only | `test_catalog.py::sankey` | n/a |
| `radar` | `radar-beta` | [radar.md](catalog/radar.md) | builder | `test_builders.py::radar` | — |
| `treemap` | `treemap-beta`, `treemap` | [treemap.md](catalog/treemap.md) | builder | `test_builders.py::treemap` | — |
| `venn` | `venn-beta` | [venn.md](catalog/venn.md) | builder | `test_builders.py::venn` | — |
| `c4` | `C4Context`, `C4Container`, `C4Component`, `C4Dynamic`, `C4Deployment` | [c4.md](catalog/c4.md) | builder | `test_builders.py::c4` | — |
| `architecture` | `architecture-beta` | [architecture.md](catalog/architecture.md) | builder | `test_builders.py::architecture` | — |
| `block` | `block`, `block-beta` | [block.md](catalog/block.md) | builder | `test_builders.py::block` | — |
| `packet` | `packet`, `packet-beta` | [packet.md](catalog/packet.md) | builder | `test_builders.py::packet` | — |
| `requirementDiagram` | `requirementDiagram` | [requirementDiagram.md](catalog/requirementDiagram.md) | builder | `test_builders.py::requirementDiagram` | — |
| `agentflow` | `agentflow-beta` | [agentflow.md](catalog/agentflow.md) | builder | `test_builders.py::agentflow` | — |
| `usecase` | `usecase-beta` | [usecase.md](catalog/usecase.md) | builder | `test_builders.py::usecase` | — |
| `swimlanes` | `swimlane-beta` | [swimlanes.md](catalog/swimlanes.md) | builder | `test_builders.py::swimlanes` | — |
| `wardley` | `wardley-beta` | [wardley.md](catalog/wardley.md) | builder | `test_builders.py::wardley` | — |
| `cynefin` | `cynefin-beta` | [cynefin.md](catalog/cynefin.md) | builder | `test_builders.py::cynefin` | — |
| `eventmodeling` | `eventmodeling` | [eventmodeling.md](catalog/eventmodeling.md) | builder | `test_builders.py::eventmodeling` | — |
| `ishikawa` | `ishikawa-beta`, `ishikawa` | [ishikawa.md](catalog/ishikawa.md) | builder | `test_builders.py::ishikawa` | — |
| `treeView` | `treeView-beta` | [treeView.md](catalog/treeView.md) | builder | `test_builders.py::treeView` | — |
| `railroad` | `railroad-ebnf-beta`, `railroad-abnf-beta`, `railroad-peg-beta`, `railroad-beta` | [railroad.md](catalog/railroad.md) | builder | `test_builders.py::railroad` | — |
| `zenuml` | `zenuml` | [zenuml.md](catalog/zenuml.md) | hand-author-only | `test_catalog.py::zenuml` | n/a |
| `info` | `info` | [info.md](catalog/info.md) | builder | `test_builders.py::info` | — |

Hand-author anything a `hand-author-only` row covers, and anything in a `candidate` row's gaps.
