# Agentflow

## Keywords

`agentflow-beta`, optionally followed by a direction. Status: beta (Mermaid 12.0.0+).

## When to use

Agentic workflows: which agent (flow) does the work, which tasks and tools it uses, and where
control, references, and failures go. Nearest alternative: `flowchart` (no agent semantics).

## Syntax

```text
agentflow-beta <TB|TD|BT|LR|RL>
id["Label"]@{ shape: <alias or Mermaid shape>, <key>: <value> }
a --> b            %% sequence
a -.- b            %% reference
a --x b            %% failure
a -- label --> b
flow id["Label"]
  ...
end
global
  ...
end
connector id["Label"]
id@{ view: "collapsed" }
```

```mermaid
agentflow-beta LR
  a["Draft"]@{ shape: task } --> b["spell_check"]@{ shape: tool }
```

## Features

| Feature id | Construct | Snippet |
|---|---|---|
| `agentflow.keyword` | diagram keyword | `agentflow-beta` |
| `agentflow.direction-tb` | direction top to bottom | `agentflow-beta TB` |
| `agentflow.direction-td` | direction top-down (same as TB) | `agentflow-beta TD` |
| `agentflow.direction-bt` | direction bottom to top | `agentflow-beta BT` |
| `agentflow.direction-lr` | direction left to right | `agentflow-beta LR` |
| `agentflow.direction-rl` | direction right to left | `agentflow-beta RL` |
| `agentflow.node` | node with id and bracket label | `research["Research the topic"]` |
| `agentflow.shape-task` | `task` alias (roundedRect) | `a["Draft"]@{ shape: task }` |
| `agentflow.shape-tool` | `tool` alias (subroutine) | `t["run_linter"]@{ shape: tool }` |
| `agentflow.shape-input` | `input` alias (lean-right) | `i["Brief"]@{ shape: input }` |
| `agentflow.shape-decision` | `decision` alias (diamond) | `d["OK?"]@{ shape: decision }` |
| `agentflow.shape-refdoc` | `refdoc` alias (lin-doc) | `g["Guide"]@{ shape: refdoc }` |
| `agentflow.shape-action` | `action` alias (hexagon) | `p["Publish"]@{ shape: action }` |
| `agentflow.shape-canonical` | any canonical Mermaid shape name | `r["R"]@{ shape: rounded }` |
| `agentflow.edge-sequence` | sequence edge | `a --> b` |
| `agentflow.edge-reference` | reference edge | `a -.- b` |
| `agentflow.edge-failure` | failure edge | `a --x b` |
| `agentflow.edge-label` | label in the middle of an edge | `ok -- yes --> ship` |
| `agentflow.edge-chain` | chained edges | `a --> b --> c` |
| `agentflow.flow` | container `flow … end` | `flow w["Writer"]` … `end` |
| `agentflow.flow-nested` | nested containers | `flow team["Team"]` / `flow w["W"]` … `end` / `end` |
| `agentflow.flow-endpoint` | a flow id used as an edge endpoint | `researcher --> writer` |
| `agentflow.global` | `global … end` keeps nodes at top level | `global` / `corpus["Corpus"]@{ shape: refdoc }` / `end` |
| `agentflow.view-collapsed` | fold a container to one node | `processing@{ view: "collapsed" }` |
| `agentflow.algorithm` | per-container ELK algorithm | `tools@{ algorithm: "elk.rectpacking" }` |
| `agentflow.metadata-inline` | single-line `@{ … }` metadata | `a@{ model: "m", instruction: "i" }` |
| `agentflow.metadata-block` | multi-line YAML metadata block | `fetch@{` / `shape: tool` / `retry: 2` / `}` |
| `agentflow.meta-label` | `label` overrides the node label | `n@{ label: "Fetch it" }` |
| `agentflow.meta-label-type` | `labelType` sets how the label is parsed | `n@{ labelType: markdown }` |
| `agentflow.edge-curve` | edge interpolation via edge id metadata | `a e1@--> b` / `e1@{ curve: linear }` |
| `agentflow.edge-animate` | edge animation flag | `e1@{ animate: true }` |
| `agentflow.edge-animation` | edge animation speed | `e2@{ animation: slow }` |
| `agentflow.meta-description` | free-text description | `a@{ description: "Drafts copy" }` |
| `agentflow.meta-instruction` | agent standing instruction | `w@{ instruction: "Cite sources." }` |
| `agentflow.meta-model` | model the agent runs on | `w@{ model: "claude-sonnet-4" }` |
| `agentflow.meta-params` | input contract | `t@{ params: "city :: String" }` |
| `agentflow.meta-returns` | output contract | `t@{ returns: "Report" }` |
| `agentflow.meta-value` | concrete value on an input | `c@{ shape: input, value: "Stockholm" }` |
| `agentflow.meta-example` | example value on an input | `c@{ shape: input, example: "Oslo" }` |
| `agentflow.meta-connector-ref` | bind a tool to a connector capability | `t@{ shape: tool, connectorRef: "llm.chat" }` |
| `agentflow.meta-custom` | unknown keys are preserved | `t@{ retry: 2 }` |
| `agentflow.connector` | external-system declaration | `connector llm["LLM API"]` |
| `agentflow.connector-metadata` | connector protocol and endpoint | `llm@{ protocol: "http", endpoint: "https://api.example.com" }` |

## Configuration and theming

Defaults: theme `redux-color`, look `neo`, layout ELK. Set `theme: default`, `look: classic`,
`layout: dagre` in frontmatter for the pre-12 appearance.

| `config.agentflow` key | Default |
|---|---|
| `titleTopMargin` | `25` |
| `diagramPadding` | `8` |
| `nodeSpacing` | `50` |
| `rankSpacing` | `50` |
| `useMaxWidth` | `true` |

themeVariables: `flowContainerStroke` (container border; falls back to `secondaryBorderColor`),
plus the standard node, edge, and cluster variables.

`accTitle:` and `accDescr:` lines render with CLI 12.0.0. A frontmatter `title:` renders.

## Traps

Only the three documented arrows parse. `==>`, `-.->`, `---`, `--o`, and `<-->` all fail:

```text
agentflow-beta LR
  a["A"] ==> b["B"]
  a["A"] -.-> b["B"]
  a["A"] --- b["B"]
```

A dotted edge cannot carry an inline `-. text .-` label. Use the pipe form `a -.-|ref| b`
(renders), or put the label on a `-->` edge.

```text
agentflow-beta LR
  a["A"] -. ref .- b["B"]
```

`subgraph` is not a keyword here; containers are `flow … end`. A `title` statement is
rejected; use frontmatter `title:`.

```text
agentflow-beta LR
  subgraph w["W"]
    a["A"]
  end
  title My flow
```

- The node lexer is the flowchart one, so it is lenient: quoted labels may contain `'`, `(`,
  `)`, `:`, `,`, `#`, `&`; ids may contain `-` and `.`; unquoted `a[A plain]` works.
- Flowchart extras (`classDef`, `class`, `:::`, `style`, `linkStyle`, `click`, `a & b --> c`,
  `(round)` and `{diamond}` brackets) render but are not documented for agentflow; prefer
  `@{ shape: … }` so `getSemanticModel()` stays stable.
- `view`, `class`, `style`, `icon`, `img`, `w`, `h` are presentation-only and stripped from the
  semantic model. `__proto__`, `constructor`, `prototype` keys are dropped from metadata.
- Edge metadata needs an edge id: `a e1@--> b`, then `e1@{ … }` on its own line.

## Complete example

```mermaid
---
title: Content pipeline
config:
  agentflow:
    nodeSpacing: 60
---
agentflow-beta TB
  accTitle: Content pipeline
  accDescr: Agents drafting, checking, and publishing copy
  connector llm["LLM API"]
  llm@{ protocol: "http", endpoint: "https://api.example.com/chat" }
  global
    corpus["Shared corpus"]@{ shape: refdoc }
  end
  brief["Brief"]@{ shape: input, value: "Stockholm", example: "Oslo" }
  flow team["Content Team"]
    flow writer["Writer"]
      draft["Draft copy"]@{ shape: task, description: "Drafts the copy" }
      spell["spell_check"]@{ shape: tool, params: "text :: String", returns: "Report", connectorRef: "llm.chat" }
      ok["Clean?"]@{ shape: decision }
      draft --> spell --> ok
      draft -.- corpus
    end
    writer@{ model: "claude-sonnet-4", instruction: "Draft and cite sources." }
    flow publisher["Publisher"]
      pub["Publish"]@{ shape: action }
      note["Archive"]@{ shape: rounded }
    end
    ok -- yes --> pub
    ok -- no --x draft
    writer --> publisher
  end
  flow tools["Tools"]
    t1["search"]@{ shape: tool }
    t2["fetch"]@{ shape: tool }
  end
  tools@{ algorithm: "elk.rectpacking" }
  flow archive["Archive store"]
    store["Store"]@{ shape: task }
  end
  archive@{ view: "collapsed" }
  fetch@{
    shape: tool
    label: "**Fetch** sources"
    labelType: markdown
    retry: 2
  }
  brief e1@--> team
  e1@{ curve: linear, animate: true }
  pub e2@--> fetch
  e2@{ animation: slow }
  note --> store
  t1 --> t2
```

Covers: every feature id except `agentflow.direction-td`, `agentflow.direction-bt`,
`agentflow.direction-lr`, `agentflow.direction-rl` (one direction per diagram; below).

```mermaid
agentflow-beta TD
  a["A"]@{ shape: task } --> b["B"]@{ shape: action }
```

Covers: `agentflow.direction-td`.

```mermaid
agentflow-beta BT
  a["A"]@{ shape: task } --> b["B"]@{ shape: action }
```

Covers: `agentflow.direction-bt`.

```mermaid
agentflow-beta LR
  a["A"]@{ shape: task } --> b["B"]@{ shape: action }
```

Covers: `agentflow.direction-lr`.

```mermaid
agentflow-beta RL
  a["A"]@{ shape: task } --> b["B"]@{ shape: action }
```

Covers: `agentflow.direction-rl`.

## Builder

`builder`: family `graph`, keyword `agentflow-beta`. Example:
[maximal.json](../../tests/fixtures/agentflow/maximal.json) (plus `maximal.direction-*.json`).

| Key | Type | Meaning |
|---|---|---|
| `direction` | `TB` \| `TD` \| `BT` \| `LR` \| `RL` | after the keyword |
| `title`, `config` | string; object | frontmatter `title` and `config.agentflow` (`titleTopMargin`, `diagramPadding`, `nodeSpacing`, `rankSpacing`, `useMaxWidth`) |
| `accessibility` | `{title, description}` | `accTitle` / `accDescr` |
| `connectors[]` | `{id, label, protocol?, endpoint?, description?, custom?}` | `connector id["label"]` plus an `id@{ ... }` line |
| `flows[]` | `{id, label, parent?, view?, algorithm?, description?, instruction?, model?, params?, returns?, custom?}` | `flow id["label"] ... end`, nested under `parent`; `view: "collapsed"`, `algorithm` an `elk.*` name; metadata after `end` |
| `nodes[]` | `{id, label \| metaLabel, labelType?, shape?, flow?, global?, metadataBlock?, ...}` | `id["label"]@{ shape: task, ... }`; `metaLabel` puts the label in metadata (`labelType`: `markdown`, `string`); `global: true` places it in `global ... end`; `metadataBlock: true` uses the multi-line `id@{` form |
| `nodes[].*` metadata | strings | `description`, `instruction`, `model`, `params`, `returns`, `value`, `example`, `connectorRef` |
| `*.custom` | `{key: string \| number \| boolean}` | extra metadata keys, e.g. `retry: 2` |
| `edges[]` | `{from, to, kind?, label?, id?, curve?, animate?, animation?, then?}` | `kind`: `sequence` `-->` (default), `reference` `-.-`, `failure` `--x`; `from`/`to` name nodes or flows; edge metadata needs `id` |

`shape` is an agentflow alias (`task`, `tool`, `input`, `decision`, `refdoc`, `action`) or a
canonical flowchart shape name. Displayed labels are quoted and entity-encoded. Metadata
values are not displayed, so they are emitted as-is in YAML double quotes: `"`, `\` and
entity-like `#name;` are rejected there. Custom keys cannot reuse a typed key, Mermaid's
presentation keys, or `__proto__`/`constructor`/`prototype`. Flow parents must not form a cycle.
