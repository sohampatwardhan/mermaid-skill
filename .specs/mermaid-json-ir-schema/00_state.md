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
| Execution | in_progress | Run `run-20260810T004517Z`; preflight and Stage 1 active |

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
