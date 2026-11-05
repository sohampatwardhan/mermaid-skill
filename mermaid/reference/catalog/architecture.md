# Architecture diagram

## Keywords
`architecture-beta` (no alias). Status: beta.

## When to use
Cloud or CI/CD topology: services and resources with icons, grouped into boundaries, connected by side-anchored edges. Nearest alternative: `C4Context` / `C4Container` for C4-level modelling, or `flowchart` for free-form boxes and arrows.

## Syntax
Group (optional icon, optional parent):

```text
group {id}({icon})[{title}] (in {parentId})?
```

Service:

```text
service {id}({icon})[{title}] (in {groupId})?
```

Junction (4-way split point):

```text
junction {id} (in {groupId})?
```

Edge (sides `T`, `B`, `L`, `R`; optional `<` and `>` arrowheads; optional `{group}` modifier):

```text
{id}{{group}}?:{T|B|L|R} {<}?--{>}? {T|B|L|R}:{id}{{group}}?
```

Alignment (v11.16.0+, at least two declared members):

```text
align row {idA} {idB} ...
align column {idA} {idB} ...
```

## Features
| Feature id | Construct | Snippet |
|---|---|---|
| `architecture.keyword` | opener | `architecture-beta` |
| `architecture.group` | group with icon and title | `group api(cloud)[API]` |
| `architecture.group-nested` | group inside a group | `group priv(cloud)[Private] in api` |
| `architecture.group-no-icon` | group without an icon | `group zone[Zone]` |
| `architecture.service` | service with icon and title | `service db(database)[Database]` |
| `architecture.service-in-group` | service placed in a group | `service db(database)[Database] in api` |
| `architecture.service-no-icon` | service without an icon | `service server[Server] in groupOne` |
| `architecture.junction` | junction node | `junction jc` |
| `architecture.junction-in-group` | junction placed in a group | `junction jg in api` |
| `architecture.edge` | plain edge, no arrowheads | `db:L -- R:server` |
| `architecture.side-left` | leave / enter on the left | `a:L -- R:b` |
| `architecture.side-right` | leave / enter on the right | `a:R -- L:b` |
| `architecture.side-top` | leave / enter on the top | `a:T -- B:b` |
| `architecture.side-bottom` | leave / enter on the bottom | `a:B -- T:b` |
| `architecture.edge-right-angle` | 90 degree edge from mixed sides | `db:T -- L:server` |
| `architecture.arrow-right` | arrowhead into the right-hand node | `subnet:R --> L:gateway` |
| `architecture.arrow-left` | arrowhead into the left-hand node | `subnet:R <-- L:gateway` |
| `architecture.arrow-both` | arrowheads on both ends | `subnet:R <--> L:gateway` |
| `architecture.edge-group-modifier` | edge leaves / enters the service's group | `server{group}:B --> T:subnet{group}` |
| `architecture.align-row` | members share a row (same y) | `align row src1 src2 src3` |
| `architecture.align-column` | members share a column (same x) | `align column db1 db2 db3` |
| `architecture.icon-cloud` | built-in icon | `(cloud)` |
| `architecture.icon-database` | built-in icon | `(database)` |
| `architecture.icon-disk` | built-in icon | `(disk)` |
| `architecture.icon-internet` | built-in icon | `(internet)` |
| `architecture.icon-server` | built-in icon | `(server)` |
| `architecture.icon-pack` | registered icon pack, `pack:name` form | `service ec2(logos:aws-ec2)[EC2]` |
| `architecture.acc-title` | accessible title | `accTitle: Platform` |
| `architecture.acc-descr` | accessible description | `accDescr: API and storage` |
| `architecture.comment` | line comment | `%% note` |

## Configuration and theming
Frontmatter `config.architecture` keys (12.0.0 defaults):

| Key | Default | Notes |
|---|---|---|
| `padding` | `40` | |
| `iconSize` | `80` | also scales ideal edge length |
| `fontSize` | `16` | |
| `randomize` | `false` | randomize start positions (v11.14.0+) |
| `nodeSeparation` | `75` | fcose pass-through (v11.15.0+) |
| `idealEdgeLengthMultiplier` | `1.5` | same-group edges; also the gap between aligned members |
| `edgeElasticity` | `0.45` | same-group edges |
| `numIter` | `2500` | fcose iterations |
| `seed` | `1` | `0` = native `Math.random`; other numbers pick a reproducible layout |
| `useMaxWidth` | `true` | |

```yaml
---
config:
  architecture:
    iconSize: 60
    idealEdgeLengthMultiplier: 3
---
```

themeVariables: `archEdgeColor`, `archEdgeArrowColor`, `archEdgeWidth`, `archGroupBorderColor`, `archGroupBorderWidth` (read by the 12.0.0 styles; not listed on the syntax page). `accTitle` and `accDescr` (single line and `accDescr { }`) are supported: the SVG gets `<title>` and `<desc>`.

Icons: built-ins are `cloud`, `database`, `disk`, `internet`, `server`. Anything else uses `pack:name` (for example `logos:aws-ec2`) after the pack is registered (`mermaid.registerIconPacks(...)` in a page, `mmdc --iconPacks @iconify-json/logos` on the CLI).

## Traps
- An unregistered icon (bare `foo` or `logos:aws-ec2` without `--iconPacks`) does not fail: it renders a blue `?` placeholder. `check.sh` passes it, so look at the SVG.
- Two edges with the same endpoints in the same order fail: `a:R -- L:b` then `a:T -- B:b` gives "Can not create second element with ID `a-b`". Reverse the order (`b:B -- T:a`) or route one through a junction.
- A group id cannot be an edge endpoint (`a:R -- L:g` crashes with `TypeError`); use `service{group}` on a service inside the group.
- `{group}` only works on a service that is inside a group.
- `in parent` must name a group declared on an earlier line; otherwise "parent does not exist".
- `title` and edge labels `a:R -[label]-> L:b` parse in 12.0.0 but are not drawn and are not on the syntax page. Do not rely on them.
- Upstream says `align` order must not contradict edge directions between its members (the layout can fail); keep `align row` order consistent with `L`/`R` edges.
- Mermaid 11.16 rejected punctuation in bracket titles; 12.0.0 accepts `[A: colon, comma]` and quoted `["Title"]`.

```text
architecture-beta
    service a(server)[A]
    service b(server)[B]
    a:R -- L:b
    a:T -- B:b
```

## Complete example

```mermaid
architecture-beta
    accTitle: Platform topology
    accDescr: Public API, private services and storage
    %% groups
    group api(cloud)[Public API]
    group priv(cloud)[Private API] in api
    group store[Storage]

    service gw(internet)[Gateway] in api
    service srv(server)[Server] in priv
    service db(database)[Database] in priv
    service disk1(disk)[Disk One] in store
    service disk2(disk)[Disk Two] in store
    service logs[Logs] in store
    service ec2(logos:aws-ec2)[EC2]
    junction jc
    junction jg in api

    gw:B -- T:jg
    jg:R --> L:srv
    srv:L -- R:db
    db:T -- L:ec2
    srv{group}:B --> T:disk1{group}
    disk2:B <-- T:logs
    jc:R <--> L:disk2
    disk1:R -- L:jc

    align row disk1 jc disk2
    align column disk2 logs
```

Covers: every feature id. `architecture.icon-pack` renders as a `?` placeholder unless the `logos` pack is registered.

## Builder
`builder`: family `graph`, keyword `architecture-beta`.

| Key | Type | Meaning |
|---|---|---|
| `groups[]` | `{id, label, icon?, group?}` | `group id(icon)[label] in parent`; a parent group must come earlier in the array |
| `nodes[]` | `{id, kind?, label?, icon?, group?}` | `kind` `service` (default, needs `label`) or `junction` (no label or icon) |
| `icon` | enum or `pack:name` | `cloud`, `database`, `disk`, `internet`, `server`, or a registered pack icon such as `logos:aws-ec2` |
| `label` | text | bracket title; a title with `[` or `]` uses the quoted `["..."]` form |
| `edges[]` | `{from, from_side, to, to_side, arrow?, from_group?, to_group?}` | sides `T`, `B`, `L`, `R`; `arrow` `none`, `forward`, `backward`, `both`; `*_group` adds `{group}` |
| `alignments[]` | `{axis, members[]}` | `align row` / `align column` with two or more declared nodes |
| `config` | object | typed `config.architecture`: `padding`, `iconSize`, `fontSize`, `randomize`, `nodeSeparation`, `idealEdgeLengthMultiplier`, `edgeElasticity`, `numIter`, `seed`, `useMaxWidth` |
| `accessibility`, `comment` | | `accTitle` / `accDescr`, `%%` line |

Rejected: ids that start with `L`, `R`, `T`, `B` or `title`, or equal a keyword (`service`, `group`, `junction`, `in`, `align`, `row`, `column`, ...); a group as an edge end; a second edge with the same `from` and `to`; `{group}` on a node outside a group; titles with `*`, `_`, `~`, `` ` ``, a backslash before punctuation, entity codes or repeated spaces (Markdown or entities would change them), and `"` in a bracketed title. Architecture draws no title, so the IR has none. Example: [maximal.json](../../tests/fixtures/architecture/maximal.json).
