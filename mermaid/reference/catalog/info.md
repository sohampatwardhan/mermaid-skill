# Info

## Keywords
`info`. No upstream syntax page. Status: stable (a built-in diagnostic diagram).

## When to use
A smoke test that prints the running Mermaid version (`v12.0.0` with CLI 12.0.0) as a single line of text.
Use it to confirm which Mermaid a renderer embeds. There is no nearest alternative; for content use any real type.

## Syntax
The keyword alone:

```text
info
```

With the optional `showInfo` flag, on the same line or the next:

```text
info showInfo
```

## Features
| Feature id | Construct | Snippet |
|---|---|---|
| `info.keyword` | print the Mermaid version | `info` |
| `info.show-info` | optional `showInfo` flag (accepted; same output in 12.0.0) | `info showInfo` |
| `info.comment` | `%%` comment line | `%% version check` |

## Configuration and theming
There is no `config.info` namespace and no themeVariables of its own. The renderer draws one `<text class="version">`
at font size 32, centered in a 400 px wide SVG; global `theme`, `fontFamily` and `themeCSS` apply.
`accTitle`, `accDescr` and `title` are accepted by the parser but ignored: the 12.0.0 SVG has no `<title>`, `<desc>`
or title text.

## Traps
Anything other than `showInfo` after the keyword is a parse error:

```text
info foo
```

`showInfo` changes nothing in 12.0.0; the output is the same `v12.0.0` text with or without it.

The detector is `/^\s*info/`, so any diagram text starting with `info` (for example a mistyped `infographic`)
is routed to this parser and fails there with a parse error, not "unknown diagram".

## Complete example

```mermaid
%% version check
info showInfo
```

Covers: every feature id.

## Builder
`builder`: family `info`, keyword `info`.

| Key | Type | Meaning |
|---|---|---|
| `showInfo` | boolean | `true` writes `info showInfo` |
| `comment` | string | one `%%` line after the keyword (must not contain `%%`) |

Unknown keys fail at their JSON path. Example: [maximal.json](../../tests/fixtures/info/maximal.json).
