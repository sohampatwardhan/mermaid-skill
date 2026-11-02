# Railroad

## Keywords
`railroad-ebnf-beta` (EBNF, W3C and ISO 14977 styles). Same diagram family, other notations:
`railroad-abnf-beta` (ABNF, RFC 5234), `railroad-peg-beta` (PEG), `railroad-beta` (Mermaid's IR constructors).
Keywords must be lowercase: detection is case-insensitive but the 12.0.0 parsers are not, so `RAILROAD-EBNF-BETA` fails. Status: beta.

## When to use
Syntax (railroad) diagrams of a context-free grammar: one track per rule, with branches for choices and loops for repetition.
Nearest alternative: `flowchart` for a state-machine style picture of a parser.

## Syntax
Outer structure (all four keywords):

```text
railroad-ebnf-beta
title "<text>"
accTitle: <text>
accDescr: <text>
<rule> = <definition> ;
```

EBNF rule forms:

```text
name = definition ;
name ::= definition ;
```

ABNF and PEG rules:

```text
name = A / B ;
Name <- A / B ;
```

IR rule:

```text
name = sequence(terminal("a"), nonterminal("b")) ;
```

## Features
| Feature id | Construct | Snippet |
|---|---|---|
| `railroad.ebnf-keyword` | EBNF diagram keyword | `railroad-ebnf-beta` |
| `railroad.title` | title statement (parsed, not drawn in 12.0.0) | `title "Digit Definition"` |
| `railroad.acc-title` | accessible title | `accTitle: Grammar` |
| `railroad.acc-descr` | accessible description, one line | `accDescr: Expression rules` |
| `railroad.acc-descr-block` | accessible description, block | `accDescr { ... }` |
| `railroad.mermaid-comment` | `%%` line comment (not on the page) | `%% note` |
| `railroad.ebnf-rule` | rule with `=` ended by `;` | `digit = "0" \| "1" ;` |
| `railroad.ebnf-rule-colon-colon-eq` | rule with `::=` | `digit ::= "0" ;` |
| `railroad.ebnf-terminal-double` | terminal, double quotes | `"text"` |
| `railroad.ebnf-terminal-single` | terminal, single quotes | `'text'` |
| `railroad.ebnf-nonterminal` | non-terminal (rule reference) | `letter` |
| `railroad.ebnf-sequence-w3c` | sequence, W3C whitespace | `A B C` |
| `railroad.ebnf-sequence-iso` | sequence, ISO comma | `A , B , C` |
| `railroad.ebnf-choice` | choice | `"+" \| "-"` |
| `railroad.ebnf-optional-w3c` | optional, W3C postfix | `sign?` |
| `railroad.ebnf-optional-iso` | optional, ISO brackets | `[ sign ]` |
| `railroad.ebnf-zero-or-more-w3c` | zero or more, W3C postfix | `digit*` |
| `railroad.ebnf-zero-or-more-iso` | zero or more, ISO braces | `{ digit }` |
| `railroad.ebnf-one-or-more` | one or more, W3C postfix | `digit+` |
| `railroad.ebnf-grouping` | grouping | `( "+" \| "-" ) term` |
| `railroad.ebnf-comment-w3c` | W3C comment | `/* comment */` |
| `railroad.ebnf-comment-iso` | ISO comment | `(* comment *)` |
| `railroad.ebnf-special` | ISO special sequence | `? any character ?` |
| `railroad.ebnf-exception` | exception | `letter - "x"` |
| `railroad.abnf-keyword` | ABNF diagram keyword | `railroad-abnf-beta` |
| `railroad.abnf-alternation` | ABNF alternation | `ALPHA / DIGIT` |
| `railroad.abnf-concatenation` | ABNF concatenation | `label "." label` |
| `railroad.abnf-zero-or-more` | ABNF `*` prefix | `*( "." label )` |
| `railroad.abnf-one-or-more` | ABNF `1*` prefix | `1*DIGIT` |
| `railroad.abnf-bounded-repeat` | ABNF `n*m` prefix | `2*4ALPHA` |
| `railroad.abnf-exact-repeat` | ABNF `n` prefix | `3DIGIT` |
| `railroad.abnf-grouping` | ABNF grouping | `( ALPHA / "-" )` |
| `railroad.abnf-optional` | ABNF optional | `[ "+" country ]` |
| `railroad.abnf-terminal` | ABNF quoted terminal | `"@"` |
| `railroad.abnf-num-hex` | ABNF hex value | `%x41` |
| `railroad.abnf-num-dec` | ABNF decimal value | `%d65` |
| `railroad.abnf-num-bin` | ABNF binary value | `%b1000001` |
| `railroad.abnf-num-range` | ABNF value range | `%x30-39` |
| `railroad.abnf-comment` | ABNF comment to end of line | `; comment` |
| `railroad.peg-keyword` | PEG diagram keyword | `railroad-peg-beta` |
| `railroad.peg-rule` | PEG rule with `<-` | `Digit <- "0" / "1" ;` |
| `railroad.peg-ordered-choice` | PEG ordered choice | `A / B` |
| `railroad.peg-sequence` | PEG sequence | `A B` |
| `railroad.peg-optional` | PEG optional | `A?` |
| `railroad.peg-zero-or-more` | PEG zero or more | `A*` |
| `railroad.peg-one-or-more` | PEG one or more | `A+` |
| `railroad.peg-and-predicate` | PEG and-predicate | `&A` |
| `railroad.peg-not-predicate` | PEG not-predicate | `!Keyword` |
| `railroad.peg-grouping` | PEG grouping | `( "+" / "-" )` |
| `railroad.peg-any-char` | PEG any character | `.` |
| `railroad.peg-terminal` | PEG terminal, either quotes | `"if"`, `'else'` |
| `railroad.peg-comment` | PEG comment to end of line | `# comment` |
| `railroad.ir-keyword` | IR diagram keyword | `railroad-beta` |
| `railroad.ir-terminal` | IR terminal | `terminal("+")` |
| `railroad.ir-nonterminal` | IR non-terminal | `nonterminal("term")` |
| `railroad.ir-sequence` | IR sequence | `sequence(a, b)` |
| `railroad.ir-choice` | IR choice | `choice(a, b)` |
| `railroad.ir-optional` | IR optional | `optional(a)` |
| `railroad.ir-zero-or-more` | IR zero or more | `zeroOrMore(a)` |
| `railroad.ir-one-or-more` | IR one or more | `oneOrMore(a)` |
| `railroad.ir-special` | IR special sequence | `special("text")` |

## Configuration and theming
Frontmatter `config.railroad` keys. The page documents none by name; these are the 12.0.0 schema and renderer
defaults. Colors and typography default to the active theme; the values below apply only when the theme gives none.

| Key | Default | Key | Default |
|---|---|---|---|
| `compactMode` | false | `nonTerminalFill` | `#FFFFFF` |
| `padding` | 10 | `nonTerminalStroke` | `#000000` |
| `verticalSeparation` | 8 | `nonTerminalTextColor` | `#000000` |
| `horizontalSeparation` | 10 | `lineColor` | `#000000` |
| `arcRadius` | 10 | `strokeWidth` | 2 |
| `fontSize` | 14 (theme) | `markerFill` | `#000000` |
| `fontFamily` | monospace (theme) | `commentFill` / `commentStroke` / `commentTextColor` | `#E8E8E8` / `#888888` / `#666666` |
| `terminalFill` | `#FFFFC0` | `specialFill` / `specialStroke` | `#F0E0FF` / `#8800CC` |
| `terminalStroke` | `#000000` | `ruleNameColor` | `#000066` |
| `terminalTextColor` | `#000000` | `showMarkers` / `markerRadius` | true / 5 |
| `useMaxWidth` | true | | |

Overrides apply (checked: `terminalFill`, `terminalStroke`, `fontSize` reach the SVG CSS). Color values must look like
a hex, `rgb()`/`hsl()`-style function, or a color name, and `fontFamily` must be plain text; others are dropped.
No railroad-specific themeVariables. The page says `look: handDrawn` is not supported; with 12.0.0 it renders without error.
`accTitle` and `accDescr` (both forms) are supported: the 12.0.0 SVG gets `<title>` and `<desc>`.

## Traps
Every rule needs the terminating `;`. A missing one is a parse error:

```text
railroad-ebnf-beta
digit = "0" | "1"
```

`title` is parsed and stored but NOT drawn in 12.0.0 (neither quoted nor bare). Use `accTitle` for a label.

Empty alternatives are a parse error (`a = "x" | ;`). Write `a = [ "x" ] ;` instead.
Rule names may contain `-` (`local-part`) but not `.` (`a.b = ...` fails).

The exception `A - B` is drawn as a plain sequence `A`, terminal `-`, `B`, not as a distinct exclusion shape.
PEG `&A`, `!A` and `.` render as special-sequence boxes (`? !Keyword ?`, `? . ?`).
ABNF bounded and exact repeats (`2*4A`, `3A`) render as repetition loops with no visible count.

Rules can span lines; a definition may break before `|`. Comments of the notation's own style are dropped.
A wrong-notation operator is an error (`/` in EBNF, `|` in ABNF or PEG, `=` in PEG); keep one notation per diagram.

## Complete example

```mermaid
railroad-ebnf-beta
title "Expression Grammar"
accTitle: Expression grammar
accDescr: EBNF rules for signed numbers and expressions
%% one rule per statement, each ends with ;
/* W3C style comment */
(* ISO style comment *)
expression = term ( ( "+" | "-" ) term )* ;
term ::= factor , { ( '*' | '/' ) , factor } ;
factor = number | "(" expression ")" | ? any constant ? ;
number = sign? digit+ [ "." digit+ ] ;
sign = "+" | "-" ;
digit = "0" | "1" | "2" | "3" | "4" | "5" | "6" | "7" | "8" | "9" ;
letter = "a" | "b" | "c" ;
name = letter - "x" ;
```

Covers: every `railroad.ebnf-*` feature id, plus `railroad.title`, `railroad.acc-title`, `railroad.acc-descr`, `railroad.mermaid-comment`.

```mermaid
railroad-ebnf-beta
accDescr {
  A single rule with a block description
}
digit = "0" | "1" ;
```

Covers: `railroad.acc-descr-block`, `railroad.ebnf-keyword`, `railroad.ebnf-rule`, `railroad.ebnf-choice`.

```mermaid
railroad-abnf-beta
title "Address"
; ABNF comment
address = [ "+" code ] local-part "@" domain ;
code = 1*DIGIT ;
local-part = 1*( ALPHA / DIGIT / "." / "-" ) ;
domain = label *( "." label ) ;
label = 2*4ALPHA 3DIGIT ;
hex = %x30-39 / %d65 / %b1000001 / %x41 ;
```

Covers: every `railroad.abnf-*` feature id.

```mermaid
railroad-peg-beta
title "Identifiers"
# PEG comment
Identifier <- !Keyword &Letter Letter Letter* Digit? ;
Keyword <- "if" / 'else' / "while" ;
Letter <- "a" / "b" / ( "c" "_" ) / . ;
Digit <- "0" / "1" ;
Number <- Digit+ ;
```

Covers: every `railroad.peg-*` feature id.

```mermaid
railroad-beta
title Expression Grammar
expression = sequence(
    nonterminal("term"),
    zeroOrMore(sequence(choice(terminal("+"), terminal("-")), nonterminal("term")))
) ;
term = sequence(optional(terminal("-")), oneOrMore(nonterminal("digit")), special("any")) ;
```

Covers: every `railroad.ir-*` feature id.

## Builder
`candidate`: `scripts/render.py` has an IR builder for this type (target keyword(s) `railroad-ebnf-beta`). It has not been through the reliability bar yet; see [coverage.md](../coverage.md).
