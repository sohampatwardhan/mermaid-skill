# ELK layout configuration

ELK (Eclipse Layout Kernel) is an alternate layout algorithm to Mermaid's default `dagre`
renderer. As of Mermaid 11.17.x it is supported for **`flowchart`** and **`stateDiagram-v2`**
only; Mermaid's own docs describe "plans to extend support to all diagram types," so re-check
`reference/syntax/flowchart.md` and `reference/syntax/stateDiagram.md` (or query live docs) before
assuming a third diagram type supports it.

## Enabling ELK

```yaml
---
config:
  layout: elk
---
flowchart LR
  A[Start] --> B{Choose Path}
  B -->|Option 1| C[Path 1]
  B -->|Option 2| D[Path 2]
```

`layout: elk` is a top-level `config` key, not nested under `flowchart`/`state` — it switches the
whole diagram's layout engine, distinct from the older, flowchart-only
`config.flowchart.defaultRenderer: "elk"` directive still documented in
`reference/syntax/flowchart.md`. Prefer `layout: elk` for new diagrams.

## Tuning parameters (`config.elk.*`)

| Key | Values | Default | Effect |
|---|---|---|---|
| `mergeEdges` | `true` \| `false` | `false` | Combine parallel edges between the same two nodes into one visual edge. |
| `nodePlacementStrategy` | `SIMPLE`, `NETWORK_SIMPLEX`, `LINEAR_SEGMENTS`, `BRANDES_KOEPF` | `BRANDES_KOEPF` | The node-positioning algorithm ELK uses within a layer. |
| `nodePlacementAlignment` | `NONE`, `LEFTUP`, `LEFTDOWN`, `RIGHTUP`, `RIGHTDOWN`, `BALANCED` | `NONE` | Alignment bias used by the `BRANDES_KOEPF` strategy; ignored for other strategies. |
| `forceNodeModelOrder` | `true` \| `false` | `false` | Keep nodes in the order they were declared in source instead of letting ELK reorder them for layout quality. |
| `considerModelOrder` | `true` \| `false` | `false` | Bias layer assignment toward source declaration order without fully forcing it. |
| `keepEntryNodeOnTop` | `true` \| `false` | `true` | For recursive/nested flows, keep the entry (root) node visually on top rather than letting ELK relayout it into the body. |

```yaml
---
config:
  layout: elk
  elk:
    mergeEdges: true
    nodePlacementStrategy: LINEAR_SEGMENTS
    nodePlacementAlignment: NONE
    forceNodeModelOrder: true
    considerModelOrder: true
    keepEntryNodeOnTop: true
---
flowchart TD
  A --> B --> C
```

## When to reach for ELK

Prefer ELK over the default `dagre` renderer for large or densely cross-connected flowcharts and
state diagrams where `dagre` produces excessive edge crossings or overlap; `dagre` remains the
better default for small, simple diagrams. Render both and compare when it's not obvious which
serves the diagram better — this is a presentational/layout choice, not a syntax choice, so it
never changes what the diagram *says*, only how it's arranged.
