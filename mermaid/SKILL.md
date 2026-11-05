---
name: mermaid
description: Produce validated Mermaid for a Markdown note. Use when choosing a diagram type or writing a ```mermaid block for any open-source Mermaid 12 type — graph types (flowchart, sequence, class, state, ER), time and tree types (gantt, timeline, journey, gitGraph, kanban, mindmap), charts (pie, quadrant, xy, radar, treemap, venn), structure (C4, architecture, block, packet, requirement), and the Mermaid 12 betas (agentflow, usecase, swimlanes, wardley, cynefin, event modeling, ishikawa, treeView, railroad). Validate every diagram with scripts/check.sh, which parses the source with the pinned Mermaid 12.0.0 — no browser or render.
metadata:
  author: sohampatwardhan
  version: "2.0.0"
---

# Mermaid

Produce Mermaid source for a Markdown ` ```mermaid ` fence. Mermaid lives in Markdown; whatever viewer shows the note renders it. Done means the exact source you insert has passed `scripts/check.sh` (it prints `PASS`), which confirms the source parses with the pinned Mermaid 12.0.0. Run commands from this skill directory.

## Route

1. Pick one type from the index below and open only that catalog file, `reference/catalog/<type>.md`. It has the syntax, every feature, config and theming, traps, a complete example, and the builder status. Load nothing else up front.
2. If the content is already structured data and the catalog's Builder section says `builder`, write the IR JSON and run `scripts/render.py`. Otherwise hand-author from the catalog file. A `hand-author-only` type has no builder.
3. Run `scripts/check.sh` on the exact final source. Fix the reported line and re-run. Do not re-check unchanged source.
4. Put the fenced source in the note. An image is not needed — the viewer renders the fence. Only when the user explicitly wants a standalone SVG/PNG/PDF, use a separate render tool (a host Mermaid render tool, or `mmdc`); `check.sh` does not render.

```bash
scripts/render.py diagram.json -o diagram.mmd   # optional, builder types only
scripts/check.sh diagram.mmd                     # always, on the exact final source
scripts/check.sh --markdown note.md              # validate every mermaid fence in a file
```

## Check

`check.sh` validates by **parsing** the source with the pinned Mermaid 12.0.0 — no browser, no render. It runs `scripts/mermaid-parse.mjs`, which loads `mermaid@12.0.0` (with `jsdom`, and the zenuml plugin for that one type) under Node 22+ and calls `mermaid.parse()` on each diagram. A diagram is valid when `mermaid.parse()` accepts it. On a parse error it prints `FAIL line N: <source line>` (exit 1), or `FAIL line unknown` with the parser message. Exit 2 is a bad input (missing file, empty diagram); exit 3 means no usable parser (needs Node and `mermaid@12.0.0` + `jsdom`, which `check.sh` installs once with `npm` or reads from `MERMAID_PARSE_NODE_MODULES`). If `check.sh` cannot run, deliver the source and say once that it is unverified.

## Builders

The IR builders in `scripts/render.py` are an optional fast path, not a requirement. A type has one only where it is 100% reliable: accepted IR always parses with the pinned Mermaid 12.0.0, and anything it cannot represent is rejected with a JSON Pointer rather than guessed or dropped. [reference/coverage.md](reference/coverage.md) says which types have a `builder` and which are `hand-author-only`; the shared IR rules and exit codes are in [reference/ir.md](reference/ir.md). `render.py` exits 0 on success, 1 on an `IRError`, 2 on a bad input file, and uses only the Python standard library.

## Index

Pick a type, then open its catalog file.

| Type | Keywords | Use for | Catalog |
|---|---|---|---|
| flowchart | `flowchart`, `graph` | steps, decisions, any boxes-and-arrows graph (ISO 5807 for control flow) | [flowchart.md](reference/catalog/flowchart.md) |
| sequenceDiagram | `sequenceDiagram` | message order between participants over time | [sequenceDiagram.md](reference/catalog/sequenceDiagram.md) |
| classDiagram | `classDiagram` | UML static structure: classes, members, relationships | [classDiagram.md](reference/catalog/classDiagram.md) |
| stateDiagram | `stateDiagram-v2` | states and transitions, composites, concurrency | [stateDiagram.md](reference/catalog/stateDiagram.md) |
| entityRelationshipDiagram | `erDiagram` | entities, attributes, crow's-foot cardinality | [entityRelationshipDiagram.md](reference/catalog/entityRelationshipDiagram.md) |
| gantt | `gantt` | a dated schedule with dependencies and milestones | [gantt.md](reference/catalog/gantt.md) |
| timeline | `timeline` | a chronology of events with no durations | [timeline.md](reference/catalog/timeline.md) |
| userJourney | `journey` | steps of a task with a 1-5 satisfaction score | [userJourney.md](reference/catalog/userJourney.md) |
| gitgraph | `gitGraph` | a branching strategy: commits, branches, merges | [gitgraph.md](reference/catalog/gitgraph.md) |
| kanban | `kanban` | a board of cards in workflow columns | [kanban.md](reference/catalog/kanban.md) |
| mindmap | `mindmap` | a hierarchy of ideas around one centre | [mindmap.md](reference/catalog/mindmap.md) |
| pie | `pie` | proportions of one whole | [pie.md](reference/catalog/pie.md) |
| quadrantChart | `quadrantChart` | items on a two-criteria 2x2 grid | [quadrantChart.md](reference/catalog/quadrantChart.md) |
| xyChart | `xychart` | bar and line charts over x values | [xyChart.md](reference/catalog/xyChart.md) |
| sankey | `sankey` | quantities flowing from sources to targets | [sankey.md](reference/catalog/sankey.md) |
| radar | `radar-beta` | a few entities across shared dimensions | [radar.md](reference/catalog/radar.md) |
| treemap | `treemap-beta` | a sized hierarchy as nested rectangles | [treemap.md](reference/catalog/treemap.md) |
| venn | `venn-beta` | overlap between a few sets | [venn.md](reference/catalog/venn.md) |
| c4 | `C4Context` … `C4Deployment` | software architecture at one C4 level | [c4.md](reference/catalog/c4.md) |
| architecture | `architecture-beta` | cloud or CI/CD topology with icons | [architecture.md](reference/catalog/architecture.md) |
| block | `block` | a hand-placed box grid | [block.md](reference/catalog/block.md) |
| packet | `packet` | bit-level layout of a packet or header | [packet.md](reference/catalog/packet.md) |
| requirementDiagram | `requirementDiagram` | SysML requirements and their links | [requirementDiagram.md](reference/catalog/requirementDiagram.md) |
| agentflow | `agentflow-beta` | an agentic workflow of tasks and tools | [agentflow.md](reference/catalog/agentflow.md) |
| usecase | `usecase-beta` | UML use cases, actors, boundaries | [usecase.md](reference/catalog/usecase.md) |
| swimlanes | `swimlane-beta` | a process split into ownership lanes | [swimlanes.md](reference/catalog/swimlanes.md) |
| wardley | `wardley-beta` | a strategy value chain by visibility and evolution | [wardley.md](reference/catalog/wardley.md) |
| cynefin | `cynefin-beta` | problems sorted into the five Cynefin domains | [cynefin.md](reference/catalog/cynefin.md) |
| eventmodeling | `eventmodeling` | Event Modeling timeline frames | [eventmodeling.md](reference/catalog/eventmodeling.md) |
| ishikawa | `ishikawa-beta` | a fishbone cause-and-effect diagram | [ishikawa.md](reference/catalog/ishikawa.md) |
| treeView | `treeView-beta` | a directory-like tree | [treeView.md](reference/catalog/treeView.md) |
| railroad | `railroad-ebnf-beta` | a grammar railroad diagram (EBNF/ABNF/PEG) | [railroad.md](reference/catalog/railroad.md) |
| zenuml | `zenuml` | a code-like sequence diagram (hand-author-only) | [zenuml.md](reference/catalog/zenuml.md) |
| info | `info` | the running Mermaid version (a smoke test) | [info.md](reference/catalog/info.md) |

The checked matrix of types, keywords, builders, and tests is [reference/coverage.md](reference/coverage.md).

## Repair and cache

`scripts/refresh.sh` rewrites `reference/diagram-types.md` and `reference/syntax/` from the pinned `mermaid@12.0.0` tag (`MERMAID_REF` overrides it). Run it when the user asks, or when a live doc shows the cache is missing a type; a single failed diagram is not a reason to refresh.

`scripts/setup-mcp.sh` configures Mermaid MCP for Claude Code, only when the user asks. A host with its own Mermaid render tool may use it to produce an image; `check.sh` is the parse-based validation path this package tests.
