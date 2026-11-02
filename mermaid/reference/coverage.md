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
| `flowchart` | `flowchart` | [flowchart.md](catalog/flowchart.md) | candidate | `test_render.py` | Expanded shape names beyond the ISO set; `click` / theme |
| `sequenceDiagram` | `sequenceDiagram` | [sequenceDiagram.md](catalog/sequenceDiagram.md) | candidate | `test_render.py` | Actor boxes, menus, creation/destruction, sequence numbers; ids are not aliased |
| `classDiagram` | `classDiagram` | [classDiagram.md](catalog/classDiagram.md) | candidate | `test_render.py` | Namespaces, cardinality on relations, `cssClass` |
| `stateDiagram` | `stateDiagram-v2` | [stateDiagram.md](catalog/stateDiagram.md) | candidate | `test_render.py` | Legacy `stateDiagram`; concurrency (`--`) |
| `entityRelationshipDiagram` | `erDiagram` | [entityRelationshipDiagram.md](catalog/entityRelationshipDiagram.md) | candidate | `test_render.py` | Attributes as keys beyond the emitted forms |
| `gantt` | `gantt` | [gantt.md](catalog/gantt.md) | candidate | `test_render.py` | `until`, `excludes` weekends only as emitted, tick intervals |
| `timeline` | `timeline` | [timeline.md](catalog/timeline.md) | candidate | `test_render.py` | — |
| `userJourney` | `journey` | [userJourney.md](catalog/userJourney.md) | candidate | `test_render.py` | — |
| `gitgraph` | `gitGraph` | [gitgraph.md](catalog/gitgraph.md) | candidate | `test_render.py` | `cherry-pick`; branch order options |
| `kanban` | `kanban` | [kanban.md](catalog/kanban.md) | candidate | `test_render.py` | `ticketBaseUrl` frontmatter |
| `mindmap` | `mindmap` | [mindmap.md](catalog/mindmap.md) | candidate | `test_render.py` | `::icon()` decorations |
| `pie` | `pie` | [pie.md](catalog/pie.md) | candidate | `test_render.py` | Donut / highlight / legend are frontmatter, not IR |
| `quadrantChart` | `quadrantChart` | [quadrantChart.md](catalog/quadrantChart.md) | candidate | `test_render.py` | Point styling |
| `xyChart` | `xychart` | [xyChart.md](catalog/xyChart.md) | candidate | `test_render.py` | `line` and `bar` together are supported; chart config is not |
| `sankey` | `sankey` | [sankey.md](catalog/sankey.md) | candidate | `test_render.py` | — |
| `radar` | `radar-beta` | [radar.md](catalog/radar.md) | candidate | `test_render.py` | Per-axis range, curve options beyond min/max |
| `treemap` | `treemap-beta` | [treemap.md](catalog/treemap.md) | candidate | `test_render.py` | Class styles on leaves |
| `venn` | `venn-beta` | [venn.md](catalog/venn.md) | candidate | `test_render.py` | — |
| `c4` | `C4Context`, `C4Container`, `C4Component`, `C4Dynamic`, `C4Deployment` | [c4.md](catalog/c4.md) | candidate | `test_render.py` | Sprites, tags, `UpdateElementStyle`, `UpdateRelStyle` |
| `architecture` | `architecture-beta` | [architecture.md](catalog/architecture.md) | candidate | `test_render.py` | Group-edge `{group}` modifier, edge labels |
| `block` | `block` | [block.md](catalog/block.md) | candidate | `test_render.py` | Nested `block` groups, `blockArrow`, columns only as a top-level int |
| `packet` | `packet` | [packet.md](catalog/packet.md) | candidate | `test_render.py` | Byte-vs-bit display config |
| `requirementDiagram` | `requirementDiagram` | [requirementDiagram.md](catalog/requirementDiagram.md) | candidate | `test_render.py` | — |
| `agentflow` | `agentflow-beta` | [agentflow.md](catalog/agentflow.md) | candidate | `test_render.py` | Metadata, `connector`, `global`, collapsed `view` |
| `usecase` | `usecase-beta` | [usecase.md](catalog/usecase.md) | candidate | `test_render.py` | Notes, JSON tables, stereotypes, actor type/icon, package boundaries |
| `swimlanes` | `swimlane-beta` | [swimlanes.md](catalog/swimlanes.md) | candidate | `test_render.py` | Lane-only features beyond flowchart subgraphs |
| `wardley` | `wardley-beta` | [wardley.md](catalog/wardley.md) | candidate | `test_render.py` | Evolution axis, `size`, label offsets, `(build)`/`(buy)`/`(inertia)` |
| `cynefin` | `cynefin-beta` | [cynefin.md](catalog/cynefin.md) | candidate | `test_render.py` | Self-loops are rejected because Mermaid ignores them |
| `eventmodeling` | `eventmodeling` | [eventmodeling.md](catalog/eventmodeling.md) | candidate | `test_render.py` | `rf` rows, long kind names, data blocks, link chains |
| `ishikawa` | `ishikawa-beta` | [ishikawa.md](catalog/ishikawa.md) | candidate | `test_render.py` | — |
| `treeView` | `treeView-beta` | [treeView.md](catalog/treeView.md) | candidate | `test_render.py` | Box-drawing input, `icon()`, `##` annotations, `:::` classes |
| `railroad` | `railroad-ebnf-beta` | [railroad.md](catalog/railroad.md) | candidate | `test_render.py` | Rules are verbatim strings, not a grammar AST |
| `zenuml` | `zenuml` | [zenuml.md](catalog/zenuml.md) | candidate | `test_render.py` | `if` / `while` / `try` / `par` / `opt` / `new` / aliases. External diagram; `mmdc` loads it |
| `info` | `info` | [info.md](catalog/info.md) | candidate | `test_render.py` | — |

Hand-author anything a `hand-author-only` row covers, and anything in a `candidate` row's gaps.
