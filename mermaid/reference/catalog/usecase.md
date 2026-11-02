# Use case diagram

## Keywords

`usecase-beta`. Status: beta (Mermaid 12.0.0+).

## When to use

UML use case views: actors, the use cases they reach, system boundaries, and include,
extend, and generalization relationships. Nearest alternative: `flowchart` with subgraphs.

## Syntax

```text
usecase-beta
direction <TD|TB|BT|LR|RL>
actor Id
actor Id("Label")@{ type: hollow|awesome, icon: "pack:name", business: true } <<Stereo>>:::cls
Id("Ellipse label")@{ business: true } <<Stereo>>:::cls
Id[Rectangle label]
"Quoted declaration"
systemBoundary id["Title"]@{ type: rect|package }:::cls
  <actor and use case declarations only>
end
A --> B   A <-- B   A -- B   A --o B   A o-- B   A --x B   A x-- B
A -- "label" --> B
A ..> : include B
A ..> : extend B
A --|> B
A edgeId@--> B
note for Id "text"
json Id@{ "key": "value" }:::cls
classDef name prop:val,prop:val
class Id1,Id2 name
style Id prop:val
edgeId@{ animate: true|false, animation: fast|slow }
```

```mermaid
usecase-beta
actor Customer
Customer --> Checkout("Checkout")
```

## Features

| Feature id | Construct | Snippet |
|---|---|---|
| `usecase.keyword` | diagram keyword | `usecase-beta` |
| `usecase.direction-td` | direction top-down | `direction TD` |
| `usecase.direction-tb` | direction top to bottom | `direction TB` |
| `usecase.direction-bt` | direction bottom to top | `direction BT` |
| `usecase.direction-lr` | direction left to right | `direction LR` |
| `usecase.direction-rl` | direction right to left | `direction RL` |
| `usecase.actor` | bare actor (id is label) | `actor Customer` |
| `usecase.actor-label` | actor with id and label | `actor Admin("Main administrator")` |
| `usecase.actor-digit-id` | identifier starting with a digit | `actor 3rd` |
| `usecase.actor-normal` | normal stick actor (default) | `actor Normal("Normal actor")` |
| `usecase.actor-hollow` | hollow actor variant | `actor H("Hollow")@{ type: hollow }` |
| `usecase.actor-awesome` | awesome actor variant | `actor W("Awesome")@{ type: awesome }` |
| `usecase.actor-icon` | icon actor | `actor I("Icon")@{ icon: "fa:user" }` |
| `usecase.business-actor` | business slash on an actor | `actor S("Sales")@{ business: true }` |
| `usecase.business-usecase` | business slash on an ellipse use case | `Quote("Quote")@{ business: true }` |
| `usecase.stereotype` | one visible stereotype | `Quote("Quote") <<Core>>` |
| `usecase.usecase-ellipse` | ellipse use case | `Login("Sign in")` |
| `usecase.usecase-rect` | rectangle use case | `Report[Generate report]` |
| `usecase.usecase-quoted` | quoted declaration, derived id | `"Reset password"` (id `Reset_password`) |
| `usecase.usecase-implicit` | undeclared endpoint becomes an ellipse | `Customer --> Login` |
| `usecase.label-unquoted` | unquoted literal label | `Priced[Costs 19.95 EUR!]` |
| `usecase.label-string` | plain string label | `Literal("**shown literally**")` |
| `usecase.label-markdown` | Markdown string, may span lines | ``F("`**Bold** label`")`` |
| `usecase.label-entity` | entity codes in labels | `R("Refund #40;partial#41;")` |
| `usecase.comment` | whole-line comment | `%% comment` |
| `usecase.boundary` | system boundary block | `systemBoundary sb1["Payment"]` … `end` |
| `usecase.boundary-quoted` | quoted title, derived id | `systemBoundary "Back office"` (id `Back_office`) |
| `usecase.boundary-rect` | default rectangle boundary | `systemBoundary s@{ type: rect }` |
| `usecase.boundary-package` | package boundary with title tab | `systemBoundary s@{ type: package }` |
| `usecase.boundary-metadata-statement` | later metadata statement for a boundary | `Back_office@{ type: package }` |
| `usecase.assoc-point` | association with arrow | `User --> Start` |
| `usecase.assoc-reverse-point` | reversed arrow | `Start <-- Support` |
| `usecase.assoc-plain` | markerless association | `Start -- Finish` |
| `usecase.assoc-circle` | circle marker | `User --o Start` |
| `usecase.assoc-reverse-circle` | reversed circle marker | `Start o-- Support` |
| `usecase.assoc-cross` | cross marker | `User --x Finish` |
| `usecase.assoc-reverse-cross` | reversed cross marker | `Finish x-- Support` |
| `usecase.assoc-label` | labelled association | `User -- "include details" --> Login` |
| `usecase.assoc-label-unquoted` | unquoted association label | `A -- files R&D report --> B` |
| `usecase.assoc-length` | extra dashes request a longer edge | `A ----> B` |
| `usecase.include` | include relationship | `Checkout ..> : include Payment` |
| `usecase.extend` | extend relationship | `ApplyCoupon ..> : extend Checkout` |
| `usecase.generalization` | generalization | `Admin --\|> Person` |
| `usecase.edge-id` | explicit edge id | `Customer opens@--> Checkout` |
| `usecase.edge-animate` | animate on or off | `opens@{ animate: true }` |
| `usecase.edge-animation-fast` | fast animation | `opens@{ animation: fast }` |
| `usecase.edge-animation-slow` | slow animation | `opens@{ animation: slow }` |
| `usecase.note` | note attached to an actor or use case | `note for Login "Needs a session"` |
| `usecase.json` | JSON table node | `json Payload@{ "status": "ok" }` |
| `usecase.classdef` | class definition | `classDef data stroke:#3572a5` |
| `usecase.classdef-default` | default class | `classDef default stroke:#7f8ea3` |
| `usecase.classdef-multi` | several classes in one statement | `classDef a,b stroke-width:3px` |
| `usecase.class` | assign classes to ids | `class Customer,Checkout a,b` |
| `usecase.class-shorthand` | `:::` class suffix | `Checkout("Checkout"):::critical` |
| `usecase.style` | direct style on a node or boundary | `style Checkout stroke:#c33` |
| `usecase.style-edge` | style or class on an edge id | `style opens stroke:#06c` |
| `usecase.acc-title` | accessible title | `accTitle: Account access` |
| `usecase.acc-descr` | single-line accessible description | `accDescr: Sign-in flows` |
| `usecase.acc-descr-block` | multiline accessible description | `accDescr {` … `}` |

## Configuration and theming

Defaults: theme `redux-color`, look `neo`, layout ELK (`theme: default`, `look: classic`,
`layout: dagre` restores the old appearance).

| `config.usecase` key | Default |
|---|---|
| `actorFontSize` | `14` |
| `actorFontFamily` | `"Open Sans", sans-serif` |
| `actorFontWeight` | `normal` |
| `usecaseFontSize` | `12` |
| `usecaseFontFamily` | `"Open Sans", sans-serif` |
| `usecaseFontWeight` | `normal` |
| `nodeSpacing` | `50` |
| `rankSpacing` | `50` |
| `diagramPadding` | `20` |
| `colorScheme` | `role` (or `rotate`: per-element palette slots) |
| `useMaxWidth` | `true` |

themeVariables: `usecaseActorBkg`, `usecaseActorBorder`, `usecaseBkg`, `usecaseBorder`,
`usecaseBoundaryBkg`, `usecaseBoundaryBorder` (fallback when the theme has no palette;
boundaries are numbered like subgraphs), `usecaseIncludeLine`, `usecaseExtendLine`.

`accTitle:`, `accDescr:` and `accDescr { … }` are supported and render. Frontmatter `title:`
renders; a `title` statement does not.

## Traps

One statement per physical line. `;` is not a separator, and trailing tokens are an error.
Chains (`A --> B --> C`) are rejected.

```text
usecase-beta
actor A
A --> B; A --> C
A --> B --> C
```

Identifiers match `[A-Za-z0-9_]+`: `actor my-actor` fails. PlantUML `as` aliases, `title`,
and `//` or `#` comments fail.

```text
usecase-beta
actor my-actor
actor A as Alice
title Hello
// comment
```

Unquoted labels reject `(`, `)`, `[`, `]`, `{`, `}`, `'`, `"`, and `--`. Quote them
(`B["It's here"]`) or use entity codes (`#40;`, `#39;`).

```text
usecase-beta
B[Cost (net)]
C[It's]
D[Read the -- docs]
```

Boundaries are one level deep and hold only actor and use case declarations. A nested
boundary, a relationship, or `direction` inside a boundary fails. An element may belong to
only one boundary.

```text
usecase-beta
actor A
systemBoundary s1
  direction TB
  A --> B
  systemBoundary s2
  end
end
```

Semantic checks that fail the render:

- `include` / `extend` need use case endpoints (`actor A` then `A ..> : include B` fails).
- `--|>` needs actor-actor or usecase-usecase.
- JSON nodes accept only `-->`, `<--`, `--`; `B --o J` fails. A JSON root must be an object.
- Extra dashes work only on `-->`, `<--`, `--`: `A ---o B` fails.
- Actor metadata keys are only `type`, `icon`, `business`; `fillColor` fails. `icon` cannot
  combine with `type: hollow|awesome` or `business: true`. `Rect[..]@{ business: true }` fails.
- `note for A "y" "z"` (multiple texts) fails.
- `..> include B` without the colon fails; the space around `:` is optional (`..>: include`).

Ordering: the suffix order is `<id><label>@{…} <<Stereo>>:::cls`. `B("B"):::c <<S>>` fails.
`direction` may appear after other statements. Actors are never inferred: an undeclared
endpoint is always an ellipse use case. `"Line1\nLine2"` shows a literal `\n`; use a Markdown
string with a real newline. Docs say `;` in a `style` value is rejected, but CLI 12.0.0
renders `style B fill:#fff;stroke:#000`; use commas anyway.

## Complete example

```mermaid
---
config:
  usecase:
    colorScheme: rotate
    nodeSpacing: 60
---
usecase-beta
direction LR
accTitle: Online ordering use cases
accDescr {
  A customer places an order.
  Staff review it and inspect its data.
}
%% Actors are declared explicitly
actor Customer
actor Staff("Order staff")@{ type: hollow, business: true } <<Employee>>
actor Bot("Bot")@{ type: awesome }
actor Normal("Normal actor")
actor Ext("External")@{ icon: "fa:user" }:::external
actor Person
actor 3rd(*Third party*)
systemBoundary ordering["Ordering System"]@{ type: package }:::system
  Browse("Browse products")
  Checkout("Checkout")@{ business: true } <<Core>>:::critical
  Payment("Process payment")
  Review[Review order] <<Record>>
end
systemBoundary "Back office"
  Refund("Refund #40;partial#41;")
  "Reset password"
end
systemBoundary support["Support"]@{ type: rect }
  Ticket("Open ticket")
end
Back_office@{ type: package }
Formatted("`**Formatted**
label`")
Plain("**Literal markers**")
Priced[Costs 19.95 EUR — VAT included!]
json OrderData@{
  "status": "pending",
  "items": [{ "name": "Book" }],
  "total": 29.95
}:::data
note for Checkout "`Validates the **cart**`"
Customer starts@-- "places order" ---> Checkout
Customer --> Browse
Customer --> Undeclared
Browse <-- Staff
Staff -- Review
Staff --o Refund
Refund o-- Bot
Bot --x Reset_password
Reset_password x-- Ext
Normal slow@--> Ticket
Checkout pays@..> : include Payment
Refund ..> : extend Checkout
Staff --|> Person
3rd -- files R&D report --> Priced
3rd --> Formatted
3rd ----> Plain
Review --> OrderData
classDef default stroke:#7f8ea3
classDef system stroke:#c8a02a,stroke-width:2px
classDef critical,external stroke:#c33,stroke-width:3px
classDef data stroke:#3572a5
class starts,pays critical
class Customer,Bot external
style pays stroke:#6b46c1,stroke-width:2px
style ordering stroke:#536878
starts@{ animation: fast }
slow@{ animation: slow }
pays@{ animate: true }
```

Covers: every feature id except `usecase.direction-td`, `usecase.direction-tb`,
`usecase.direction-bt`, `usecase.direction-rl` (one direction per diagram) and
`usecase.acc-descr` (one description form per diagram); see below.

```mermaid
usecase-beta
direction TD
actor A
A --> B
```

Covers: `usecase.direction-td`.

```mermaid
usecase-beta
direction TB
actor A
A --> B
```

Covers: `usecase.direction-tb`.

```mermaid
usecase-beta
direction BT
actor A
A --> B
```

Covers: `usecase.direction-bt`.

```mermaid
usecase-beta
direction RL
accTitle: Sign in
accDescr: A customer signs in
actor A
A --> B
```

Covers: `usecase.direction-rl`, `usecase.acc-descr`.

## Builder

`candidate`: `scripts/render.py` has an IR builder for this type (target keyword(s) `usecase-beta`). It has not been through the reliability bar yet; see [coverage.md](../coverage.md).
