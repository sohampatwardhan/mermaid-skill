# Spec State: Mermaid JSON IR Schema

<!-- spec-nav:start -->
**Spec navigation:** [State](00_state.md) · [Discovery](01_discovery.md) · [Requirements](02_requirements.md) · [Design](03_design.md) · [Tasks](04_tasks.md) · [Execution](05_execution.md)
<!-- spec-nav:end -->

| Gate | Status | Evidence |
|---|---|---|
| Discovery | approved | Rebased to the current 12-target source snapshot and approved by the user on 2026-08-09 |
| Requirements | approved | Revised 12-target requirements approved by the user on 2026-08-09 |
| Design | approved | Approved by the user on 2026-08-09 |
| Tasks | approved | Approved by the user on 2026-08-09 with authorization to execute all tasks |
| Audit | not_run | Optional quality gate not selected |
| Execution | in_progress | Run `run-20260810T004517Z` completed Stages 1–8 (12 targets); a second, user-directed increment on 2026-08-31/09-01 added 8 more targets and 2 engine fixes outside the original 12-target Requirements/Design/Tasks gates — see Change Control. Task 8.1 (install to `~/.agents/skills/mermaid/` and `~/.codex/skills/mermaid/`) remains not started; the user explicitly held it for a later session. |

## Change Control

- The earlier exploratory design is background evidence only. This spec-driven artifact chain is
  authoritative for scope, approval, traceability, implementation, and verification.
- A material change to target coverage, compatibility policy, strictness, or deterministic-output
  guarantees returns the feature to Discovery and invalidates downstream approvals.
- Discovery was approved without changes on 2026-08-09; Requirements may now proceed.
- On 2026-08-09, current source inspection found six additional implemented targets: `block`,
  `C4Context`, `C4Container`, `architecture-beta`, `erDiagram`, and `classDiagram`. This materially
  changes the meaning of "existing targets," so Discovery and Requirements require revision and
  re-approval before Design or Tasks.
- The user approved rebasing phase one to all 12 targets on 2026-08-09. The planning baseline is
  Mermaid skill tree SHA-256 `b82d695a14f4ab0e6867808cd40d798cea55c4a39470a62d00cf16c532f8af22`;
  subsequent source edits do not alter this spec unless the user explicitly requests a rebase.
- The revised 74-criterion Requirements gate was approved by the user on 2026-08-09; Design may
  proceed against the pinned source snapshot.
- The user explicitly approved [Design](03_design.md) on 2026-08-09; Tasks may proceed against the
  pinned source snapshot.
- The user approved [Tasks](04_tasks.md) and authorized execution of all tasks on 2026-08-09.
- On 2026-08-31/09-01, the user asked for a review of newly shipped Mermaid diagram types and
  directed "implement all requested changes and fix all bugs... ensure this skill works
  flawlessly" / "do everything now in this session," explicitly authorizing work ahead of a formal
  Discovery/Requirements/Design/Tasks revision for the added scope below. This is a material target
  coverage change under this file's own Change Control rule; it is recorded here as a factual
  record of what was executed, not as a substitute for that revision. A future session should
  still run Discovery→Tasks for this increment before treating it as equally load-bearing as the
  original 12-target contract, and before task 8.1 installs either increment to a live location.
  Work done, all verified by the full test suite (`pytest tests`, 182 passed) and by real
  `mermaid-cli 11.16.1` rendering of every new example via `scripts/check.sh`:
  - Added 8 new targets, each with its own schema, deterministic serializer, semantic validation
    (where meaningful), minimal/maximal examples, and contract tests: `swimlane-beta` (`graph`
    family), `cynefin-beta`, `eventmodeling`, `venn-beta`, `ishikawa-beta`, `treeView-beta`,
    `railroad-beta`, `wardley-beta` (each its own family) — see [reference/ir.md](work/skill/reference/ir.md#families).
    Unlike the original 12, these were not run through the construct-by-construct inventory audit
    against a pinned Mermaid source snapshot; they were built and verified directly against
    reference/syntax/*.md and real renders instead.
  - Fixed a real `$ref` root-tracking bug in `scripts/mermaid_ir/schema_runtime.py` and
    `normalize.py`: a local (`#/...`) fragment ref incorrectly re-rooted at the fragment itself
    whenever the containing schema had no file path (true for every target schema, since
    `load_target_schema` reads them directly rather than through the registry), which broke any
    second-level or recursive local `$ref` — the reason none of the original 12 target schemas
    used `$ref`/`$defs` despite the engine supporting it. Also fixed the `$ref` cycle-detection
    guard, which could not distinguish a true infinite schema cycle from ordinary recursive data
    (a step containing a branch containing another step); it now resets per instance descent.
  - Rewrote `schema/targets/sequenceDiagram.schema.json`'s step/branch shape to use a single
    recursive `$defs` entry instead of a manually-unrolled fixed-depth copy, fixing a real bug
    where a 4th level of nested control blocks (e.g. `critical` → branch → `par` → branch → `alt`)
    failed schema validation; added the missing `actor` field used by `activate`/`deactivate`
    steps, uncovered by the same fix. Regression test:
    `SequenceTests.test_control_blocks_nest_beyond_three_levels`.
  - Extended `targets/_base.py`'s shared `graph_semantics` validator to check that a node's
    `group` (if set) references a declared group id — previously only edge `from`/`to` references
    were checked, so an undeclared `group` on any `graph`-family target (flowchart, mindmap,
    block, C4Context, C4Container, architecture-beta, erDiagram, classDiagram, swimlane-beta)
    fell through to whatever ad hoc runtime check that target's own serializer happened to have,
    if any.
  - Added ELK layout as an envelope-level, cross-cutting `renderer.frontmatter.config.layout`/
    `.elk` structure (`schema/config.schema.json`), validated by real enum values from Mermaid's
    documented ELK options, with `compile_ir` rejecting `layout: elk` for any target other than
    `flowchart`/`stateDiagram-v2` (the only two Mermaid currently documents it for). See
    `tests/test_elk_layout.py` and [reference/elk-layout.md](work/skill/reference/elk-layout.md).
  - Refreshed [`mermaid/reference/diagram-types.md`](../../mermaid/reference/diagram-types.md) and `mermaid/reference/syntax/*.md` from the
    live `mermaid-js/mermaid` source via `scripts/refresh.sh`, which also surfaced two more brand
    new diagram types not yet in any tagged release at investigation time: `agentflow-beta` and
    `usecase-beta`. Updated both [`mermaid/SKILL.md`](../../mermaid/SKILL.md) and this work tree's `SKILL.md` frontmatter
    `description` to name every new type plus a generic "any other current or future" clause, so
    routing does not go stale the next time Mermaid ships a type.
