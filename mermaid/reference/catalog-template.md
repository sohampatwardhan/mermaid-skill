# Catalog file template

Every `catalog/<type>.md` uses these H2 sections in this order. `tests/test_catalog.py`
enforces the order, the Features table, and that every `mermaid` fence passes `check.sh`.
The file stem is the type id (the stem of its `syntax/` page, or `info`).

````text
# <Type name>

## Keywords
`flowchart` (alias `graph`). Status: stable | beta.

## When to use
One or two sentences, plus the nearest alternative type.

## Syntax
Statement forms, one short block each.

## Features
| Feature id | Construct | Snippet |
|---|---|---|
| `flowchart.subgraph-direction` | direction inside a subgraph | `direction LR` |

## Configuration and theming
Frontmatter `config.<namespace>` keys with defaults, themeVariables, accTitle and accDescr support.

## Traps
Parser and lexer pitfalls seen with CLI 12.0.0. Invalid samples use text fences.

## Complete example
One mermaid fence with every coexisting feature, plus one fence per exclusive group.

## Builder
`builder`: family, keywords, IR keys, link to tests/fixtures/<type>/maximal.json.
or `hand-author-only`: one sentence on why.
````

Rules:

- Feature ids are `<type>.<kebab-name>`, unique in the file, and stable once published.
- Write a `|` inside a table cell as `\|`.
- Syntax that does not render goes in a `text` fence, never a `mermaid` fence.
- Only column-0 ```` ```mermaid ```` fences are checked; every one must render with CLI 12.0.0.
