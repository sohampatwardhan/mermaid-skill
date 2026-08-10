---
name: mermaid
description: Use when creating, editing, validating, rendering, or fixing ANY Mermaid diagram — flowchart, sequence, class, state, ER, gantt, pie, gitGraph, mindmap, timeline, journey, quadrant, requirement, C4, sankey, xychart, block, packet, kanban, architecture, radar, treemap, zenuml — or when a ```mermaid code block fails to render, has a syntax error, or needs to be turned into an SVG/PNG image.
---

# Mermaid

## Overview

Author Mermaid diagrams that render correctly the first time, for **every** diagram type, always against the **current** Mermaid syntax — not stale training data.

**Core principle:** Use the smallest authoritative syntax source sufficient for the diagram, then
verify the exact final source by rendering it. Do not spend a live documentation call on syntax
already covered by the local cache, and do not confuse extra tool calls with stronger validation.

**Two hard rules:**
1. **Know what the type expects before authoring.** Use exactly one initial syntax source: the
  relevant entry in [reference/type-cheatsheets.md](reference/type-cheatsheets.md) for a simple,
  stable diagram; the matching cached [reference/syntax/](reference/syntax/) document for an
  advanced or `-beta` diagram; or live Mermaid documentation when the type or feature is absent,
  version-sensitive, or demonstrably stale. Do not read the cheatsheet and full document by
  default.
2. **Validate by rendering** before presenting (`validate_and_render_mermaid_diagram`, or `scripts/check.sh` when offline). A diagram you did not render is unverified. Do not trust the renderer's process exit code alone: validation must also reject Mermaid's generated error SVG placeholder.

For program, system, or data-processing flowcharts, also follow the
[ISO 5807 flowchart profile](reference/iso-5807-flowcharts.md). It defines semantic shape and
layout conventions; Mermaid rendering validation alone does not establish standards conformance.

## Capability routing

Do not probe, install, authenticate, or reconfigure an MCP server during ordinary diagram work.
Inspect the tools already available in the current host and choose the shortest working route:

- **Mermaid render tool available:** use it for the final render. Query live syntax only when the
  escalation rules below require it.
- **No Mermaid render tool:** use `scripts/check.sh` from this skill directory. It prefers an
  installed `mmdc` and otherwise uses `npx`.
- **Neither route works:** produce the best source supported by the local reference, label it
  unverified, and report the missing capability once.

`scripts/setup-mcp.sh` is an optional Claude Code convenience, not a workflow prerequisite. Run it
only when the user asks to configure Mermaid MCP in Claude Code. It may require a host restart and
is not portable to VS Code or other agents.

## Escalation rules

Start cheap and escalate only on evidence:

1. **Simple stable creation:** read only the relevant cheatsheet entry, author, render once.
2. **Advanced or beta creation:** read only the matching cached full syntax document, author,
   render once.
3. **Repairing existing source:** render the source first. Use the reported line/token for one
   focused repair; consult syntax documentation only if the error is ambiguous or version-sensitive.
4. **Unknown/new feature or stale-cache signal:** query live official Mermaid syntax. Run
   `scripts/refresh.sh` only when the user asks to update the cache or the live docs prove the cache
   is stale; a failed diagram does not by itself justify refreshing every cached type.
5. **Render failure:** never retry unchanged. Make the smallest error-directed fix and re-render.
   If a second focused attempt fails, load the full relevant syntax source or use the repair tool if
   available; do not reread unrelated references.

Within one task, reuse syntax guidance already loaded for the same diagram type. Re-render only
when the Mermaid source changes, and validate the exact source that will be delivered.

## The workflow

```
1. Identify the diagram type from the decision table; ask only when materially ambiguous
2. Select ONE syntax source using the escalation rules
3. Write or repair the Mermaid source
4. Render the exact final source once:
     • validate_and_render_mermaid_diagram(mermaidCode, diagramType, clientName="claude")
     • or scripts/check.sh diagram.mmd   (local, MCP-free fallback)
5. On error, make an error-directed fix and re-render; escalate documentation only as needed
6. Present only the artifacts appropriate to the target surface
```

When using the Mermaid MCP from Claude, pass `clientName="claude"`. For icons
(AWS/Azure/GCP/FontAwesome in `architecture-beta`/flowchart), use `search_mermaid_icons` once per icon
set to get exact prefixed names; do not guess or search separately for repeated icons.

### `architecture-beta` compatibility

The architecture lexer is stricter than flowchart label parsing and may reject punctuation in
group titles even when the title is bracketed. Keep group/container titles to words, digits, and
spaces unless the exact target Mermaid core has rendered the final source. In particular, Mermaid
11.16.1 rejects a title such as `[ESP32-S3 firmware]`; use `[ESP32 S3 firmware]` in the diagram and
retain the exact product spelling in surrounding prose. Service labels can be more descriptive,
but they still require final rendering against the target version.

CLI and Mermaid core versions do not necessarily match. When a failure names a core version,
reproduce with a CLI that embeds that core when practical, and inspect the generated SVG for
`aria-roledescription="error"`. `scripts/check.sh` performs this artifact check automatically.

In this skill, **Mermaid** means the canonical [`mermaid-js/mermaid`](https://github.com/mermaid-js/mermaid)
project, which parses Mermaid definitions and renders SVG. The official
[`mermaid-js/mermaid-cli`](https://github.com/mermaid-js/mermaid-cli) is an export adapter used when
SVG, PNG, or PDF files are required; do not treat the CLI as the canonical language implementation.

## Presenting the result

Match the requested destination; do not generate redundant artifacts:

- **Mermaid-capable chat or Markdown destination:** provide or write the fenced source after
  validation. Do not also create an image or edit link unless requested.
- **Chat that cannot render Mermaid:** show the rendered image and include source when useful.
- **Requested SVG/PNG/PDF:** generate that format and include source only if requested or useful
  for future editing.
- **Requested SVG when the active inspection or presentation surface cannot preview SVG:** preserve
  the validated SVG as the primary artifact and generate a PNG preview from the exact same unchanged
  Mermaid source. Do not substitute PNG for SVG or infer that the application lacks SVG support merely
  because one inspection tool cannot decode it.
- **Existing file edit:** update and validate the file; do not repeat the full source in chat.

An edit link is optional. Create or present one only when the renderer already returns it and it
helps the user's workflow; never make an extra call solely to obtain a link.

## Generating from structured data

If the diagram's content is already fully determined by structured data you have on disk (a
dependency graph, a timing/interval table, a state-transition table, a requirement-traceability
table), generate the source deterministically instead of hand-authoring it:

```bash
scripts/render.py diagram.json -o diagram.mmd   # IR JSON -> Mermaid source
scripts/check.sh diagram.mmd                     # same render-validation as any other diagram
```

Five IR families (`graph`, `timeline`, `state-machine`, `sequence`, `requirement-links`) cover
`flowchart`, `mindmap`, `gantt`, `stateDiagram-v2`, `sequenceDiagram`, and `requirementDiagram`
with real feature parity (composite states, choice/fork/join, gantt tags/milestones/excludes,
sequence activation/notes/loop/alt/par/critical/rect blocks) — see
[reference/ir.md](reference/ir.md) for the schema. Hand-author directly, as in the rest of this
skill, when the diagram synthesizes judgment with no structured source (architecture sketches,
discovery mind maps, hypothesized debugging sequences). Generated source still goes through the
same render-validation as hand-authored source — generation changes how it's authored, not
whether it's verified.

## Choosing a diagram type

| The user wants to show… | Use |
|---|---|
| Steps, decisions, branching logic | ISO 5807-aligned `flowchart` |
| Interactions/messages over time between actors | `sequenceDiagram` |
| Object model, OOP structure | `classDiagram` |
| Lifecycle / status transitions | `stateDiagram-v2` |
| Database entities & relationships | `erDiagram` |
| Dated schedule, dependencies, milestones, and critical work | `gantt` |
| Chronological events without dependencies | `timeline` |
| Proportions of a whole | `pie` |
| Git branching history | `gitGraph` |
| Hierarchy / brainstorm | `mindmap` |
| User experience / satisfaction per step | `journey` |
| 2×2 prioritization | `quadrantChart` |
| Requirements & verification links | `requirementDiagram` |
| System context / containers (C4 model) | `C4Context` / `C4Container` |
| Static composition, nested subsystems, or hardware/software partition | `block` |
| Flow quantities between nodes | `sankey-beta` |
| Line/bar chart from data | `xychart-beta` |
| Cloud/service architecture with icons | `architecture-beta` |
| Board with columns of cards | `kanban` |
| Explicit grid or low-level spatial layout | `block` |
| Network packet byte layout | `packet-beta` |
| Multi-axis comparison | `radar-beta` |
| Nested proportional rectangles | `treemap` |

Full catalog: [reference/diagram-types.md](reference/diagram-types.md). If a needed type is absent,
check live official syntax; refresh the cache only after confirming Mermaid added it.

## Flowcharts: ISO 5807-aligned, not generic boxes

When a flowchart documents executable or operational control flow, read
[reference/iso-5807-flowcharts.md](reference/iso-5807-flowcharts.md) before authoring. Use
terminators for start/end, rectangles for operations, diamonds for decisions, parallelograms for
input/output, and semantically appropriate shapes for subprocesses, documents, stores, and
connectors. Label every decision branch and preserve a clear primary direction. Treat ISO 5807 as
an authoring constraint, not reader-facing copy: explain what the flowchart shows, and mention the
standard only when the user asks for it or it is material to the document's purpose.

Do not force a flowchart where another diagram is more truthful: use a sequence diagram for
messages over time, a state diagram for legal lifecycle transitions, ER for persisted relations,
class diagrams for an object model, and Gantt only for a dated delivery schedule with meaningful
dependencies. Use a block diagram when static parts, grouping, partitioning, and connections are
the point and C4-model or cloud-service semantics would be artificial. A diagram earns its place by answering a
decision or verification question.

## Staying current

This skill is designed to never go stale. Two layers keep it current:

1. **Runtime authority — live official docs.** Treat live official Mermaid syntax as the source of
  truth when local guidance conflicts with it. Query it on escalation, not reflexively.
2. **Local refresh.** The type catalog *and* a full offline copy of the official per-type syntax docs are regenerated directly from the Mermaid source tree (the authoritative set of what exists) on demand:

```bash
scripts/refresh.sh
```

Run `scripts/refresh.sh` when the user asks to update the skill, a live official document proves
the cache stale, or a needed type is absent from both the catalog and cache. Do not run it merely
because time has passed or one diagram failed: it performs a network-wide cache rewrite.

## Beyond authoring: other MCP capabilities

The Mermaid MCP also exposes (some require auth via `authenticate_mermaid_chart` with a token from mermaidchart.com settings):
- **Titles/summaries:** `get_diagram_title`, `get_diagram_summary` — nice for naming/describing a finished diagram.
- **Repair:** `repair_mermaid_chart_diagram` — AI-fix a broken diagram from code + error (auth).
- **Mermaid Chart storage:** `list_/create_/get_/update_mermaid_chart_diagram` (auth).
- **GitHub `.mmd` workflow:** `list_mermaid_files`, `read_mermaid_file`, `create_pr`, `push_file` — find/edit diagram files in a repo and open a PR. These publish/modify content — get the user's explicit OK before creating PRs, pushing files, or creating issues.
- **Notion/Jira/ticket helpers:** `insert_/update_notion_mermaid_diagram`, `generate_ticket_diagram`, etc.

## Common mistakes

| Mistake | Fix |
|---|---|
| Loading cheatsheet + full doc + live doc for one diagram | Start with one source; escalate only on evidence |
| Running MCP setup before every diagram | Route by available tools; setup is explicit and host-specific |
| Writing syntax from memory for a beta/new type | Read its cached full doc or live official syntax first |
| Presenting a diagram you never rendered | Always `validate_and_render` — "looks right" ≠ renders |
| Treating `mmdc` exit 0 as proof of success | Inspect the SVG error sentinel; use `scripts/check.sh`, which fails on Mermaid's error placeholder |
| Treating an SVG inspection failure as an application-wide SVG limitation | Preserve the SVG and, only when needed, render a PNG preview from the identical Mermaid source |
| Guessing icon names in `architecture-beta` | `search_mermaid_icons` for exact `provider:name` |
| Using punctuation in an `architecture-beta` group title | Prefer words, digits, and spaces; verify the exact target core before retaining punctuation |
| Using `stateDiagram` when v2 features are needed | Prefer `stateDiagram-v2` |
| Drawing all flow nodes as generic rectangles | Apply the ISO 5807 profile's semantic shapes and branch labels |
| Special chars/reserved words breaking node labels | Quote labels: `A["text (with) special chars"]` — confirm via the syntax doc |
| Retrying a render unchanged after an error | Read Mermaid's error text; it names the line/token — fix that specifically |
| Emitting code when MCP unavailable without saying so | State that the syntax is unverified and validate with `mmdc` if possible |

## Red flags — STOP

- "I know this syntax, so I need no reference" → use the one minimum sufficient local or live source.
- "I'll just give them the code, they can render it themselves" → validate it yourself first.
- "I'll install or reconfigure MCP just in case" → use available capabilities; setup only on request.
- "More documentation calls must be safer" → one relevant source plus an actual render is the gate.
