# Swimlanes diagram

## Keywords

`swimlane-beta`, optionally followed by a direction (default `TB`). Status: beta (v11.16.0+).

## When to use

A process split by ownership: each top-level `subgraph` is a lane (team, system, phase) and
arrows show handoffs. Nearest alternative: `flowchart` when ownership does not matter.

## Syntax

```text
swimlane-beta [TB|TD|BT|LR|RL]
subgraph Lane
  id[Text]
end
subgraph laneId [Lane label]
  ...
end
A --> B
A -->|Label| B
```

```mermaid
swimlane-beta LR
  subgraph Customer
    request[Request]
  end
  subgraph Support
    triage[Triage]
  end
  request --> triage
```

## Features

| Feature id | Construct | Snippet |
|---|---|---|
| `swimlanes.keyword` | diagram keyword, default direction TB | `swimlane-beta` |
| `swimlanes.direction-tb` | top to bottom | `swimlane-beta TB` |
| `swimlanes.direction-td` | top down (same as TB) | `swimlane-beta TD` |
| `swimlanes.direction-bt` | bottom to top | `swimlane-beta BT` |
| `swimlanes.direction-lr` | left to right | `swimlane-beta LR` |
| `swimlanes.direction-rl` | right to left | `swimlane-beta RL` |
| `swimlanes.lane` | lane as a top-level subgraph | `subgraph Sales` … `end` |
| `swimlanes.lane-id-label` | lane with id and display label | `subgraph sales [Sales team]` |
| `swimlanes.node-rect` | rectangle node | `task[Do work]` |
| `swimlanes.node-rounded` | rounded rectangle | `step(Receive update)` |
| `swimlanes.node-stadium` | stadium | `start([Start])` |
| `swimlanes.node-decision` | decision (rhombus) | `decision{Ready?}` |
| `swimlanes.node-circle` | circle | `done((Done))` |
| `swimlanes.node-shape-metadata` | flowchart `@{ shape }` node | `doc@{ shape: doc, label: "Notes" }` |
| `swimlanes.markdown-string` | Markdown string label | ``md["`**Bold** step`"]`` |
| `swimlanes.edge-arrow` | arrow | `A --> B` |
| `swimlanes.edge-line` | line without arrowhead | `A --- B` |
| `swimlanes.edge-label` | arrow with label | `A -->\|Label\| B` |
| `swimlanes.edge-dotted` | dotted arrow | `A -.-> B` |
| `swimlanes.edge-thick` | thick arrow | `A ==> B` |
| `swimlanes.edge-chain` | chained edges | `lead --> quote --> review` |
| `swimlanes.edge-cross-lane` | edge between lanes | `request --> triage` |
| `swimlanes.classdef` | class definition | `classDef attention fill:#fff2cc,stroke:#d6a500;` |
| `swimlanes.class` | assign a class | `class review attention;` |
| `swimlanes.acc-title` | accessible title | `accTitle: Support escalation` |
| `swimlanes.acc-descr` | accessible description | `accDescr: A request is triaged` |

## Configuration and theming

The syntax page documents no `config.swimlane` keys and no type-specific themeVariables.
Defaults are theme `redux-color` and look `neo`; set `theme: default` and `look: classic`
in frontmatter (or `mermaid.initialize({ swimlane: { … } })`) for the old appearance.
Standard flowchart node, edge, and cluster theme variables apply.

`accTitle:` and `accDescr:` are documented and render with CLI 12.0.0.

## Traps

The grammar is the flowchart one, so the flowchart lexer limits apply. An unquoted label
cannot contain `(` or `)`; quote it. A `'` in an unquoted label is fine.

```text
swimlane-beta LR
  subgraph A
    a[Cost (net)]
  end
```

Use `a["Cost (net): #1"]` instead (renders).

`title` is not a statement, and agentflow's `flow … end` is not a lane keyword:

```text
swimlane-beta LR
  title Hi
  flow A
    a[x]
  end
```

- Only top-level subgraphs become lanes. A nested `subgraph` inside a lane parses and
  renders, but it is not a lane.
- Nodes outside any subgraph render outside the lanes.
- Unquoted lane names with spaces (`subgraph My Lane`) render, but use `subgraph id [Label]`
  for a stable id.
- Flowchart extras not listed on the swimlane page also render with CLI 12.0.0: `%%`
  comments, `:::`, `style`, `linkStyle`, `click`, `--x`, `--o`, `<-->`, `~~~`, `--->`, and
  `-- text -->`. See the flowchart catalog for their semantics.

## Complete example

```mermaid
swimlane-beta LR
  accTitle: Support escalation
  accDescr: A request starts with the customer, is triaged by support, and may reach engineering.
  subgraph Customer
    request([Request service])
    receive(Receive update)
  end
  subgraph support [Support team]
    triage{Known issue?}
    answer[Send answer]
  end
  subgraph Engineering
    investigate[Investigate issue]
    fix((Fix))
    notes@{ shape: doc, label: "Fix notes" }
    md["`**Release** fix`"]
  end
  request --> triage
  triage -->|Known issue| answer
  triage -->|Needs code change| investigate
  investigate --> fix --> md
  fix -.-> notes
  md ==> answer
  answer --- receive
  classDef attention fill:#fff2cc,stroke:#d6a500,color:#111;
  class triage attention;
```

Covers: every feature id except `swimlanes.keyword` (no direction),
`swimlanes.direction-tb`, `swimlanes.direction-td`, `swimlanes.direction-bt`,
`swimlanes.direction-rl` (one direction per diagram; below).

```mermaid
swimlane-beta
  subgraph Sales
    lead[Qualify lead]
  end
  subgraph Finance
    approve[Approve]
  end
  lead --> approve
```

Covers: `swimlanes.keyword`.

```mermaid
swimlane-beta TB
  subgraph Sales
    lead[Qualify lead]
  end
  subgraph Finance
    approve[Approve]
  end
  lead --> approve
```

Covers: `swimlanes.direction-tb`.

```mermaid
swimlane-beta TD
  subgraph Sales
    lead[Qualify lead]
  end
  subgraph Finance
    approve[Approve]
  end
  lead --> approve
```

Covers: `swimlanes.direction-td`.

```mermaid
swimlane-beta BT
  subgraph Sales
    lead[Qualify lead]
  end
  subgraph Finance
    approve[Approve]
  end
  lead --> approve
```

Covers: `swimlanes.direction-bt`.

```mermaid
swimlane-beta RL
  subgraph Sales
    lead[Qualify lead]
  end
  subgraph Finance
    approve[Approve]
  end
  lead --> approve
```

Covers: `swimlanes.direction-rl`.

## Builder

`builder`: family `graph`, keyword `swimlane-beta`. Example:
[maximal.json](../../tests/fixtures/swimlanes/maximal.json) (plus one `maximal.direction-*.json` per direction).

| Key | Type | Meaning |
|---|---|---|
| `direction` | `TB` \| `TD` \| `BT` \| `LR` \| `RL` | after the keyword; omit for the default (TB) |
| `accessibility`, `comment` | | `accTitle` / `accDescr`; `%%` line |
| `groups[]` | `{id, label?}` | lane: `subgraph id ["label"]` (bare `subgraph id` without label) |
| `nodes[]` | `{id, label \| markdown, kind? \| shape?, group?, class?}` | node in its lane; `kind`: `rect` (default), `round`, `stadium`, `decision`, `circle`; `shape`: a flowchart `@{ shape }` name |
| `edges[]` | `{from, to, kind?, label?, then?}` | `kind`: `arrow` `-->` (default), `line` `---`, `dotted` `-.->`, `thick` `==>`; `then: [{to, kind?, label?}]` continues a chain |
| `classDefs[]` | `{name, style}` | `classDef name ...;`; `style` keys `fill`, `stroke`, `color` (`#hex` or a CSS name), `strokeWidth` (`2px`), `strokeDasharray` (`5 5`) |

Labels are quoted and entity-encoded; `markdown` text keeps `*` and `_` as Markdown. Ids are
letters, digits and `_` and cannot be flowchart keywords (`end`, `subgraph`, `class`, ...).
Set exactly one of `label`/`markdown` and at most one of `kind`/`shape`. Raw CSS is rejected.
