# Diagram IR — shared rules

`scripts/render.py` turns a JSON document (the **IR**) into Mermaid source. Same JSON in, same
text out; it does not render. Pipe the output through `scripts/check.sh` before use. The IR is
an optional fast path for structured content — a type has a builder only where it is 100%
reliable. Per-type keys, with a worked `maximal.json`, are in each `reference/catalog/<type>.md`
Builder section. Which types have a builder is [coverage.md](coverage.md). This file is the rules
common to all of them.

## Document shape

```jsonc
{ "diagram": "<family>", "target": "<keyword>", /* type-specific keys */ }
```

- `diagram` is the family and `target` is the keyword. `--target` overrides `target`.
- `target` must be a key of `render.BUILDERS`. A `HAND_AUTHOR_ONLY` target (for example
  `zenuml`, `sankey`) is refused with a pointer to its catalog file; hand-author those.
- `diagram` must be the builder's family for that target.

| Family | Targets |
|---|---|
| `graph` | `flowchart`, `classDiagram`, `erDiagram`, `mindmap`, `block`, `architecture-beta`, `swimlane-beta`, `wardley-beta`, `agentflow-beta`, `C4Context`, `C4Container`, `C4Component`, `C4Dynamic`, `C4Deployment` |
| `sequence` | `sequenceDiagram` |
| `state-machine` | `stateDiagram-v2` |
| `requirement-links` | `requirementDiagram` |
| `timeline` | `gantt`, `timeline` |
| `journey` | `journey` |
| `git` | `gitGraph` |
| `board` | `kanban` |
| `chart` | `pie`, `quadrantChart`, `xychart`, `radar-beta`, `treemap-beta`, `venn-beta` |
| `packet` | `packet` |
| `tree` | `ishikawa-beta`, `treeView-beta` |
| `grammar` | `railroad-ebnf-beta`, `railroad-abnf-beta`, `railroad-peg-beta`, `railroad-beta` |
| `cynefin` | `cynefin-beta` |
| `eventmodeling` | `eventmodeling` |
| `usecase` | `usecase-beta` |
| `info` | `info` |

Alias keywords (`graph`, `block-beta`, `packet-beta`, `xychart-beta`, `treemap`, `stateDiagram`,
`ishikawa`) are accepted as `target` values only where the builder emits them unchanged; each
is listed in its catalog file.

## Strict keys and values

Every builder reads its input through a shared validator. It fails closed:

- **Unknown keys.** Any key an object does not document, at any depth, is an error at that key's
  JSON Pointer. Nothing is ignored.
- **Values that cannot be represented.** A wrong type, `true`/`false` where a number is expected,
  an unknown enum value, a reference to an id that was never declared, or a character the target
  context cannot carry, is an error at the value's pointer with the reason.
- **No guessing, no silent drops.** The builder never drops, truncates, or rewrites a supplied
  value to make it render (Requirement 4.4). Free text is encoded with Mermaid entity codes only
  where the type renders them back to the original character; otherwise it is rejected.
- **No raw Mermaid.** No IR field carries verbatim Mermaid source. Styles, config, and the like
  are typed objects with validated values, emitted as frontmatter or the type's own syntax.
- **Deterministic output.** The same IR renders byte-identical source every run, ending in one
  newline, keeping the order of every input array. Validation runs before any line is emitted, so
  a rejected document produces no partial source.

## Errors and exit codes

An `IRError` carries `target`, a JSON Pointer `path` (`/` is the document), and a `reason`.
`str(err)` is `<target>: <path>: <reason>`, for example
`flowchart: /nodes/2/label: character '"' cannot be represented in flowchart.label`.

`render.py` exits:

| Exit | When | Output |
|---|---|---|
| 0 | the IR rendered | source to stdout, or to `-o` |
| 1 | `IRError` | `ERROR: <target>: <path>: <reason>` on stderr; no `-o` file written |
| 2 | missing file, unreadable file, or invalid JSON | `ERROR: ...` on stderr; no `-o` file written |

`render.py` runs offline and uses only the Python standard library.
