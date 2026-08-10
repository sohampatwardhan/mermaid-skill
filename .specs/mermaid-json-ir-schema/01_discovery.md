# Discovery: Mermaid JSON IR Schema

<!-- spec-nav:start -->
**Spec navigation:** [State](00_state.md) · [Discovery](01_discovery.md) · [Requirements](02_requirements.md) · [Design](03_design.md) · [Tasks](04_tasks.md) · [Execution](05_execution.md)
<!-- spec-nav:end -->

## Problem and Outcome

The Mermaid skill can deterministically serialize a small JSON intermediate representation (IR),
but its contract is prose-defined, covers only selected structural features, applies some defaults
imperatively, and intentionally omits presentation and renderer configuration. Callers therefore
cannot address every supported Mermaid parameter through JSON or validate compulsory and optional
fields before serialization.

The desired outcome is a versioned, machine-readable JSON contract in which every supported
Mermaid construct has an explicit address, type, required/optional classification, and default
policy. Normalized JSON must produce byte-identical Mermaid source, and the generated source must
remain subject to real Mermaid render validation.

## Users and Current Workaround

The primary users are agents, scripts, and developers that generate, audit, store, or transform
Mermaid diagrams. Today they either hand-author Mermaid source, depend on undocumented renderer
defaults, or use the existing IR and post-process the generated text for unsupported features.
Those workarounds weaken reproducibility, make field-level updates unsafe, and prevent complete
schema validation.

## Scope and Non-Goals

This feature is the first independently shippable increment of the full Mermaid JSON roadmap.

In scope:

- a stable version-one document envelope;
- strict modular JSON Schemas with compulsory, optional, and default semantics;
- normalization and migration for previously valid flat IR documents;
- structural, semantic, and determinism validation;
- complete JSON addressability for the 12 implemented targets: `flowchart`, `mindmap`, `block`,
  `C4Context`, `C4Container`, `architecture-beta`, `erDiagram`, `classDiagram`, `gantt`,
  `stateDiagram-v2`, `sequenceDiagram`, and `requirementDiagram`;
- source-level accessibility, styling, interaction, and target options supported by those targets;
- separation of per-diagram frontmatter from host/site Mermaid initialization configuration;
- deterministic serialization, stable diagnostics, a coverage manifest, documentation, and tests;
- an extension contract that does not disable strict validation.

Out of scope for this increment:

- serializers for Mermaid diagram types beyond the 12 named targets;
- non-Mermaid output backends;
- executing arbitrary callback code or trusting unsafe links during validation;
- visual redesign of Mermaid's rendered SVG;
- silently accepting raw Mermaid fragments as an escape hatch;
- installing or configuring Mermaid infrastructure outside the skill's established validation
  workflow.

The remaining Mermaid diagram types will be delivered as later target modules using the same
envelope, validation contract, coverage manifest, and acceptance pattern. This decomposition keeps
the first increment independently testable without weakening the all-types end state.

## Constraints and Success Measures

Constraints:

- Existing valid IR inputs must continue to serialize through explicit legacy normalization.
- Unknown ordinary fields must fail validation; forward-compatible values belong only under a
  namespaced `extensions` object.
- JSON Schema defaults are annotations, so runtime normalization must apply the same declared
  defaults exactly once.
- Source syntax and renderer/site configuration must remain distinct because Mermaid applies
  defaults, initialization settings, and per-diagram frontmatter as separate layers.
- The renderer must fail closed on unknown targets, invalid references, incompatible combinations,
  and explicitly nondeterministic settings.
- The implementation must remain usable offline except for optional documentation refreshes or a
  renderer fallback that already requires network access.

Success measures:

- Every supported construct and configuration field for the 12 targets has a documented JSON
  Pointer, requirement status, default policy, serializer mapping, and test evidence.
- Minimal and maximal canonical documents validate for every target.
- Every compulsory-field omission and unknown ordinary field fails with a stable JSON Pointer
  diagnostic.
- Previously valid legacy fixtures normalize and render successfully.
- Repeated serialization of the same normalized document is byte-identical.
- Representative generated diagrams pass the existing Mermaid render-validation gate.
- Adding a seventh target does not require changing the canonical document envelope.

## Approaches Considered

| Approach | Benefits | Costs / risks | Reversibility | Decision |
|---|---|---|---|---|
| Modular discriminated JSON Schema | Precise validation, isolated target evolution, useful errors, and a clear route to all diagram types | Requires shared definitions, schema resolution, and disciplined coverage tracking | High; modules can evolve behind schema versions | **Selected** |
| One monolithic JSON Schema | Simple initial distribution and one schema entry point | Becomes difficult to maintain; conditional errors degrade as target count grows | Medium; later splitting would disturb references and tooling | Rejected |
| Generic Mermaid grammar AST | Can represent source tokens with near-total syntax parity | Couples durable data to parser details and weakens semantic reuse and future backends | Low; consumers would depend on Mermaid grammar structure | Rejected |

## Chosen Direction

Use a shared canonical envelope with `schemaVersion`, `diagram`, `target`, and target-specific
`content` as compulsory fields. Optional `accessibility`, `source`, `renderer`, and `extensions`
sections address cross-cutting concerns without mixing semantic content with Mermaid-specific
presentation or host configuration.

The root schema dispatches to one target module. Ordinary object boundaries are strict. Optional
fields either have a declared deterministic default or emit no source. A normalization layer
upgrades legacy input and materializes defaults before semantic validation. A namespaced extension
object preserves future data, but a serializer emits an extension only when it explicitly supports
that namespace.

This increment completes the 12 implemented targets and establishes the repeatable process for each
remaining Mermaid type: inventory the pinned grammar and configuration, add a schema module,
implement semantic validation and serialization, complete the coverage manifest, and verify
minimal, maximal, negative, deterministic, and real-render cases.

## Architecture and Flow Outline

The increment has seven bounded responsibilities:

1. A schema loader resolves bundled shared, configuration, and target schemas offline.
2. A legacy migrator converts existing flat documents into the canonical envelope.
3. A normalizer applies only version-declared defaults and canonicalizes unordered maps.
4. Structural validation checks presence, types, enums, conditions, and unknown fields.
5. Target semantic validators check identifiers, references, graph rules, and cross-field
   invariants that JSON Schema cannot express clearly.
6. Pure serializers emit Mermaid source in a documented statement order.
7. The established render-validation path checks the exact emitted source against Mermaid.

The coverage manifest connects upstream Mermaid constructs to JSON Pointers, requirement status,
defaults, serializer support, and tests. It is the completeness contract for phase one and the
template for subsequent targets.

## Failure and Verification Strategy

Malformed JSON, schema violations, semantic violations, determinism conflicts, serialization
errors, and Mermaid parser failures remain distinct error classes. Structural errors are reported
together in stable JSON Pointer order. Serialization does not begin after structural or semantic
failure, and the system never drops unknown fields or guesses missing semantic content.

Verification combines schema tests, migration fixtures, property-oriented invariant tests,
deterministic source snapshots, repeat-run equality checks, coverage-manifest completeness checks,
and representative real renders. The exact Mermaid version and configuration contract will be
pinned during design using current official Mermaid evidence.

## Open Decisions

- Requirements must define the externally observable compatibility window for legacy documents.
- Design must select the exact pinned Mermaid version and decide whether schema validation uses a
  bundled standards-compliant dependency or a constrained in-project validator.
- Design must classify renderer settings that affect SVG output but not Mermaid source so the CLI
  can expose them without contaminating the pure source serializer.

None of these decisions changes the selected modular-schema boundary.

## Planning Baseline

This discovery is pinned to the Mermaid skill tree with SHA-256
`b82d695a14f4ab0e6867808cd40d798cea55c4a39470a62d00cf16c532f8af22`. Its renderer source was
last modified at `2026-08-09 20:00:44 EDT` when the snapshot was recorded. Ongoing edits to the
live skill do not change this approved boundary unless the user explicitly requests a rebase.

## Approval

> [!IMPORTANT]
> Approve this discovery boundary before requirements are drafted.

Status: **Approved on 2026-08-09 for the pinned 12-target snapshot**
