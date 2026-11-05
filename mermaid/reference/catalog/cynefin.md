# Cynefin framework

## Keywords

`cynefin-beta`. Status: beta (v11.16.0+).

## When to use

Sorting problems or tasks into the five Cynefin domains and showing how items move between
them. Nearest alternative: `quadrantChart` (free axes, no fixed domains or transitions).

## Syntax

```text
cynefin-beta
title Text
<complex|complicated|clear|chaotic|confusion>
  "Item label"
<domain> --> <other domain> : "Label"
```

```mermaid
cynefin-beta
  complex
    "Investigate root cause"
  clear
    "Restart service"
```

## Features

| Feature id | Construct | Snippet |
|---|---|---|
| `cynefin.keyword` | diagram keyword | `cynefin-beta` |
| `cynefin.title` | diagram title | `title Incident Response` |
| `cynefin.domain-complex` | Complex domain block (top-left) | `complex` |
| `cynefin.domain-complicated` | Complicated domain block (top-right) | `complicated` |
| `cynefin.domain-clear` | Clear domain block (bottom-right) | `clear` |
| `cynefin.domain-chaotic` | Chaotic domain block (bottom-left) | `chaotic` |
| `cynefin.domain-confusion` | Confusion centre ellipse (max 3 shown, then `+N more`) | `confusion` |
| `cynefin.domain-empty` | domain with no items | `complicated` |
| `cynefin.item` | quoted item badge inside a domain | `"Run chaos experiment"` |
| `cynefin.transition` | transition between domains | `chaotic --> complex` |
| `cynefin.transition-label` | labelled transition | `complex --> complicated : "Pattern identified"` |
| `cynefin.acc-title` | accessible title | `accTitle: Cynefin map` |
| `cynefin.acc-descr` | accessible description | `accDescr: Tasks by domain` |

## Configuration and theming

| `config.cynefin` key | Default |
|---|---|
| `width` | `800` |
| `height` | `600` |
| `padding` | `40` |
| `showDomainDescriptions` | `true` (decision-model and practice subtitles) |
| `boundaryAmplitude` | `8` (`0` gives straight lines) |
| `seed` | `0` (hash of the SVG id; set non-zero for stable visual tests) |

themeVariables, nested under `themeVariables.cynefin`: `complexBg`, `complicatedBg`,
`clearBg`, `chaoticBg`, `confusionBg`, `boundaryColor`, `boundaryWidth`, `cliffColor`,
`cliffWidth`, `arrowColor`, `arrowWidth`, `labelColor`, `textColor`, `domainFontSize`,
`itemFontSize`. Hand-drawn look is not supported.

`accTitle:`, `accDescr:` and the `accDescr { … }` block render with CLI 12.0.0.

## Traps

Parse errors make the CLI exit 0 with an error SVG, so `check.sh` reports
`FAIL line unknown`. Bisect by deleting lines.

Items must be quoted (double or single quotes). A bare item fails:

```text
cynefin-beta
complex
Investigate
```

Domain names are fixed lowercase keywords. `Complex` and `disorder` fail:

```text
cynefin-beta
Complex
"a"
disorder
"b"
```

Transitions use `-->` only, and the label after `:` must be quoted:

```text
cynefin-beta
complex
"a"
complex -> complicated
complex --> complicated : Unquoted label
```

- Inside a quoted item, `'`, `:`, `(`, `)`, `#`, `&`, `<`, `>`, and `--` are fine.
- An item may sit on the same line as its domain (`complex "a"`), but keep one per line.
- A domain may be opened twice; transitions may precede the domain blocks.
- `complex --> complex` parses and is silently ignored.
- Domain position is fixed; declaration order does not move a domain.
- Keep item lists short: the four quadrants do not clip and can overflow.

## Complete example

```mermaid
---
config:
  cynefin:
    seed: 42
    boundaryAmplitude: 6
---
cynefin-beta
  title Incident Response
  accTitle: Cynefin map for incidents
  accDescr: Incident tasks sorted by complexity domain
  complex
    "Investigate root cause"
    "Run chaos experiment"
  complicated
  clear
    "Restart service"
  chaotic
    "Page on-call"
  confusion
    "Unknown failure mode"
    "Flaky alert"
    "Odd latency"
    "Missing logs"
  complex --> complicated : "Pattern identified"
  clear --> chaotic : "Complacency"
  chaotic --> complex
```

Covers: every feature id.

## Builder

`builder`: family `cynefin`, keyword `cynefin-beta`. Example:
[maximal.json](../../tests/fixtures/cynefin/maximal.json) (plus `maximal.empty-domain.json`).

| Key | Type | Meaning |
|---|---|---|
| `title` | string | `title` statement |
| `accessibility` | `{title, description}` | `accTitle` / `accDescr` (a multi-line description uses the block form) |
| `config` | object | frontmatter `config.cynefin`: `width`, `height`, `padding`, `showDomainDescriptions`, `boundaryAmplitude`, `seed` (integer) |
| `domains[]` | `{domain, items?}` | domain block in array order; `domain` is one of the five keywords; `items: []` gives an empty domain |
| `domains[].items[]` | string | quoted item badge |
| `transitions[]` | `{from, to, label?}` | `from --> to : "label"` |

Every text is entity-encoded (`"` becomes `#quot;`, `#` becomes `#35;`, ...), so any one-line
text works. A domain may appear once. A self-transition (`from` equal to `to`) is rejected,
because Mermaid silently ignores it.
