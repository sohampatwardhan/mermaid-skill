---
name: mermaid
description: Produce validated Mermaid for a Markdown note. Use when choosing a diagram type or writing a ```mermaid block — flowchart, sequence, class, state, ER, gantt, mindmap, timeline, journey, quadrant, requirement, C4, sankey, xychart, block, packet, kanban, architecture, radar, treemap, gitGraph, pie, or Mermaid 12 agentflow-beta/usecase-beta. Prefer scripts/render.py when the content is structured data; validate every diagram with scripts/check.sh, which also rejects Mermaid error-placeholder SVGs.
---

# Mermaid

Produce Mermaid source for a Markdown ` ```mermaid ` fence. Done means the exact source you insert has passed `scripts/check.sh` (it prints `PASS`).

Run commands from this skill directory.

## Route

1. Pick a type from the table below.
2. **Structured content** (nodes, edges, tables, transitions, messages, requirements you already have) **and** the type is in the IR table: write JSON and generate. Schema: [reference/ir.md](reference/ir.md). Hand-writing that Mermaid is the wrong path.
3. **Anything else:** hand-author from the one matching heading in [reference/type-cheatsheets.md](reference/type-cheatsheets.md). Open a single file under [reference/syntax/](reference/syntax/) only for a `-beta` keyword, a construct the cheatsheet does not show, or a second failed render. Do not open the cheatsheet and the syntax doc up front.
4. Validate, then put the fenced source in the note. Add an image only when the user asks for SVG, PNG, or PDF (`scripts/check.sh diagram.mmd -o out.svg`).

```bash
scripts/render.py diagram.json -o diagram.mmd   # IR only
scripts/check.sh diagram.mmd                     # always, on the exact final source
```

`check.sh` uses an installed `mmdc`, otherwise `npx @mermaid-js/mermaid-cli`. A clean result is exit 0 **and** an SVG without Mermaid's error placeholder (`aria-roledescription="error"`, `class="error-icon"`, or `Syntax error in text`). The CLI can exit 0 while writing that placeholder; `check.sh` fails the run when it sees one. On failure, change the reported line and re-run. Do not re-render unchanged source.

If `check.sh` cannot run, deliver the source and say once that it is unverified.

Control-flow flowcharts use ISO 5807 shapes (terminator, process, decision, I/O, subprocess, document, store, connector). IR flowchart `kind` values are those shapes. When hand-authoring, follow [reference/iso-5807-flowcharts.md](reference/iso-5807-flowcharts.md).

## IR targets

| Family | `target` | Diagram |
|---|---|---|
| `graph` | `flowchart` | steps, decisions, dependencies |
| `graph` | `mindmap` | tree (one parent per node) |
| `graph` | `block` | static parts and groups |
| `graph` | `C4Context`, `C4Container` | C4 context or containers |
| `graph` | `architecture-beta` | services, groups, icons |
| `graph` | `erDiagram` | entities and cardinality |
| `graph` | `classDiagram` | classes and UML relations |
| `timeline` | `gantt` | dated bars, milestones, excludes |
| `state-machine` | `stateDiagram-v2` | lifecycle |
| `sequence` | `sequenceDiagram` | messages over time |
| `requirement-links` | `requirementDiagram` | traceability |

`render.py` fails closed (unknown kinds, undeclared endpoints, a mindmap that is not a tree, a gantt label that contains `:`). It does not render. `check.sh` is still required. There is no serializer for the mermaid `timeline` keyword, pie, gitGraph, quadrant, sankey, xy, kanban, packet, radar, treemap, journey, or other catalog types.

## Choosing a type

| The note needs to show… | Keyword |
|---|---|
| Steps, decisions, branching | `flowchart` (ISO 5807 when it is control flow) |
| Messages between actors | `sequenceDiagram` |
| Object model | `classDiagram` |
| Lifecycle transitions | `stateDiagram-v2` |
| Entities and relationships | `erDiagram` |
| Dated schedule with dependencies | `gantt` |
| Events over time, no dependencies | `timeline` |
| Proportions | `pie` |
| Git history | `gitGraph` |
| Hierarchy | `mindmap` |
| Satisfaction per step | `journey` |
| 2×2 priority | `quadrantChart` |
| Requirements and links | `requirementDiagram` |
| C4 context or containers | `C4Context` / `C4Container` |
| Static composition or a grid | `block` |
| Quantities between nodes | `sankey-beta` |
| Line or bar chart | `xychart-beta` |
| Services with icons | `architecture-beta` |
| Columns of cards | `kanban` |
| Packet layout | `packet-beta` |
| Multi-axis comparison | `radar-beta` |
| Nested proportions | `treemap` |
| Agent flow (Mermaid 12) | `agentflow-beta` |
| Use cases (Mermaid 12) | `usecase-beta` |

`reference/diagram-types.md` is the cached directory list (stamp at the top). It omits `common` and `error` (shared code and the syntax-error renderer). `check.sh` uses the installed CLI, which may be newer than that stamp. `agentflow-beta` and `usecase-beta` are in Mermaid 12 and are not in the cached syntax docs. Read live docs or run `scripts/refresh.sh`, then validate. Do not invent their syntax from the keyword.

## Hand-author traps

- The first line is the diagram keyword. Quote labels that contain punctuation: `A["Order (paid)"]`.
- Gantt: the first `:` on a task line starts metadata. A colon inside the title (`Review: security :done, ...`) makes the renderer throw `TypeError` rather than a line error. Keep titles free of `:`. The IR generator rejects those labels.
- `architecture-beta` titles that the lexer rejects often come back as an error-placeholder SVG. Mermaid 11.16 rejected punctuation such as `[ESP32-S3 firmware]`; Mermaid 12 accepts it. Keep the real spelling and let `check.sh` decide.
- Built-in architecture icons: `cloud`, `database`, `disk`, `internet`, `server`. Other icons need a `pack:name` id.
- Prefer `stateDiagram-v2` when you need composites, notes, or choice/fork/join.

## Repair and cache

Render the broken source once, then fix the line or token in the error. Open syntax docs only if that error is ambiguous. A second failure is the point to load the one cached syntax file for that type.

`scripts/refresh.sh` rewrites `reference/diagram-types.md` and `reference/syntax/` from mermaid-js. Run it when the user asks, or when a live doc shows the cache is missing a type. A single failed diagram is not a reason to refresh.

`scripts/setup-mcp.sh` only configures Mermaid MCP for Claude Code, and only when the user asks. A host that already has a Mermaid render tool may use it for the final render; still reject an error-placeholder SVG. `check.sh` is the path this package tests.
