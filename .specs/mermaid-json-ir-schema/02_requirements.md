# Requirements: Mermaid JSON IR Schema

<!-- spec-nav:start -->
**Spec navigation:** [State](00_state.md) · [Discovery](01_discovery.md) · [Requirements](02_requirements.md) · [Design](03_design.md) · [Tasks](04_tasks.md) · [Execution](05_execution.md)
<!-- spec-nav:end -->

## Introduction

This increment turns the Mermaid diagram intermediate representation (IR) into a versioned,
strict, deterministic JSON contract. It completes field-addressable coverage for the 12 implemented
targets while preserving valid legacy documents and establishing the compatibility boundary for
future Mermaid target modules.

> [!IMPORTANT]
> Approval gate: approve these requirements before work begins on [Design](03_design.md).

## Domain Terms

- **Canonical document:** A versioned JSON document using the new envelope.
- **Legacy document:** A previously valid flat JSON IR document without `schemaVersion`.
- **Normalized document:** A canonical document after migration and declared defaults have been
  applied.
- **Source configuration:** Options serialized into one diagram's Mermaid source or frontmatter.
- **Initialization configuration:** Host/site options supplied to the Mermaid renderer rather than
  emitted as diagram statements.
- **Coverage manifest:** The field-level record connecting Mermaid constructs to JSON addresses,
  requirement status, defaults, serialization, and verification.

## Requirements

### Requirement 1: Canonical document contract

**User Story:** As a diagram producer, I want a versioned canonical JSON envelope, so that every diagram can be interpreted against an explicit contract.

#### Acceptance Criteria

1. **R1.1** THE Mermaid_IR_Tool SHALL require `schemaVersion`, `diagram`, `target`, and `content` in every canonical document.
2. **R1.2** WHEN a canonical document names one of the 12 supported targets, THE Mermaid_IR_Tool SHALL validate it against that target's contract.
3. **R1.3** IF a compulsory field is absent, THEN THE Mermaid_IR_Tool SHALL reject the document with a diagnostic identifying the field's JSON Pointer.
4. **R1.4** IF an ordinary object contains an unknown field, THEN THE Mermaid_IR_Tool SHALL reject the document with a diagnostic identifying that field's JSON Pointer.
5. **R1.5** WHERE namespaced extensions are included, THE Mermaid_IR_Tool SHALL preserve their JSON values through normalization.
6. **R1.6** IF an extension key is not namespaced, THEN THE Mermaid_IR_Tool SHALL reject the extension with a diagnostic identifying its JSON Pointer.

### Requirement 2: Optional fields and defaults

**User Story:** As a diagram producer, I want optional fields and defaults to have explicit behavior, so that omitted data never causes hidden or changing output.

#### Acceptance Criteria

1. **R2.1** WHEN an optional field with a declared default is absent, THE Mermaid_IR_Tool SHALL materialize that declared default in the normalized document.
2. **R2.2** WHEN an optional field without a declared default is absent, THE Mermaid_IR_Tool SHALL leave that field absent from the normalized document.
3. **R2.3** WHEN a normalized document is normalized again, THE Mermaid_IR_Tool SHALL return an equivalent document.
4. **R2.4** WHEN normalization completes, THE Mermaid_IR_Tool SHALL leave the caller's input document unchanged.
5. **R2.5** IF a supplied value conflicts with its field contract, THEN THE Mermaid_IR_Tool SHALL reject the value instead of substituting a default.

### Requirement 3: Legacy compatibility and migration

**User Story:** As an existing IR consumer, I want valid legacy documents to migrate predictably, so that adopting the schema does not break existing diagram generation.

#### Acceptance Criteria

1. **R3.1** WHEN a previously valid legacy document is received, THE Mermaid_IR_Tool SHALL convert it into an equivalent canonical document.
2. **R3.2** WHEN a legacy document is migrated, THE Mermaid_IR_Tool SHALL preserve its previously generated diagram meaning.
3. **R3.3** WHEN canonical output is requested for a legacy document, THE Mermaid_IR_Tool SHALL emit the versioned canonical shape.
4. **R3.4** IF a legacy document was invalid under the previous contract, THEN THE Mermaid_IR_Tool SHALL reject it without guessing missing semantic content.
5. **R3.5** IF a legacy field has no canonical equivalent, THEN THE Mermaid_IR_Tool SHALL reject migration with a diagnostic identifying the unmapped field.

### Requirement 4: Complete implemented-target addressability

**User Story:** As a diagram producer, I want every supported Mermaid parameter represented in JSON, so that diagrams can be created and updated without editing generated Mermaid text.

#### Acceptance Criteria

1. **R4.1** THE Mermaid_IR_Tool SHALL provide a JSON address for every supported `flowchart` source construct and configuration field in the selected Mermaid version.
2. **R4.2** THE Mermaid_IR_Tool SHALL provide a JSON address for every supported `mindmap` source construct and configuration field in the selected Mermaid version.
3. **R4.3** THE Mermaid_IR_Tool SHALL provide a JSON address for every supported `gantt` source construct and configuration field in the selected Mermaid version.
4. **R4.4** THE Mermaid_IR_Tool SHALL provide a JSON address for every supported `stateDiagram-v2` source construct and configuration field in the selected Mermaid version.
5. **R4.5** THE Mermaid_IR_Tool SHALL provide a JSON address for every supported `sequenceDiagram` source construct and configuration field in the selected Mermaid version.
6. **R4.6** THE Mermaid_IR_Tool SHALL provide a JSON address for every supported `requirementDiagram` source construct and configuration field in the selected Mermaid version.
7. **R4.7** THE Mermaid_IR_Tool SHALL provide a JSON address for every supported `block` source construct and configuration field in the selected Mermaid version.
8. **R4.8** THE Mermaid_IR_Tool SHALL provide a JSON address for every supported `C4Context` source construct and configuration field in the selected Mermaid version.
9. **R4.9** THE Mermaid_IR_Tool SHALL provide a JSON address for every supported `C4Container` source construct and configuration field in the selected Mermaid version.
10. **R4.10** THE Mermaid_IR_Tool SHALL provide a JSON address for every supported `architecture-beta` source construct and configuration field in the selected Mermaid version.
11. **R4.11** THE Mermaid_IR_Tool SHALL provide a JSON address for every supported `erDiagram` source construct and configuration field in the selected Mermaid version.
12. **R4.12** THE Mermaid_IR_Tool SHALL provide a JSON address for every supported `classDiagram` source construct and configuration field in the selected Mermaid version.
13. **R4.13** IF a caller supplies a raw Mermaid fragment outside a declared extension contract, THEN THE Mermaid_IR_Tool SHALL reject the fragment.
14. **R4.14** WHEN a supported field is supplied, THE Mermaid_IR_Tool SHALL serialize its value without silently dropping it.

### Requirement 5: Configuration and accessibility scopes

**User Story:** As a renderer integrator, I want diagram source settings separated from host settings, so that the same content can be rendered reproducibly in different environments.

#### Acceptance Criteria

1. **R5.1** WHEN an accessibility title is supplied, THE Mermaid_IR_Tool SHALL emit the corresponding Mermaid accessibility title statement.
2. **R5.2** WHEN an accessibility description is supplied, THE Mermaid_IR_Tool SHALL emit the corresponding Mermaid accessibility description statement.
3. **R5.3** WHEN per-diagram frontmatter configuration is supplied, THE Mermaid_IR_Tool SHALL serialize it as per-diagram Mermaid frontmatter.
4. **R5.4** WHEN initialization configuration is supplied, THE Mermaid_IR_Tool SHALL expose it separately from the generated Mermaid source.
5. **R5.5** IF the selected source configuration is not supported by the selected Mermaid version, THEN THE Mermaid_IR_Tool SHALL reject it with a version-aware diagnostic.
6. **R5.6** WHEN no renderer version is supplied, THE Mermaid_IR_Tool SHALL use the documented pinned Mermaid version.
7. **R5.7** WHEN deterministic rendering is enabled, THE Mermaid_IR_Tool SHALL expose deterministic identifier settings in the effective renderer configuration.
8. **R5.8** IF a caller explicitly selects nondeterministic identifier behavior while deterministic rendering is enabled, THEN THE Mermaid_IR_Tool SHALL reject the conflict.

### Requirement 6: Semantic integrity and diagnostics

**User Story:** As a diagram producer, I want invalid relationships rejected before rendering, so that failures identify the faulty JSON rather than an opaque generated-source error.

#### Acceptance Criteria

1. **R6.1** IF a document contains duplicate identifiers where uniqueness is required, THEN THE Mermaid_IR_Tool SHALL reject it with diagnostics for the conflicting JSON locations.
2. **R6.2** IF a relationship references an undeclared identifier, THEN THE Mermaid_IR_Tool SHALL reject it with a diagnostic for the referencing JSON location.
3. **R6.3** IF a target-specific graph invariant is violated, THEN THE Mermaid_IR_Tool SHALL reject it with a diagnostic naming the violated invariant.
4. **R6.4** IF supplied fields form a forbidden combination, THEN THE Mermaid_IR_Tool SHALL reject them with diagnostics identifying the conflicting JSON locations.
5. **R6.5** WHEN independent structural errors exist, THE Mermaid_IR_Tool SHALL report them in stable JSON Pointer order.
6. **R6.6** IF structural validation fails, THEN THE Mermaid_IR_Tool SHALL produce no Mermaid source.
7. **R6.7** IF semantic validation fails, THEN THE Mermaid_IR_Tool SHALL produce no Mermaid source.

### Requirement 7: Deterministic serialization

**User Story:** As an automation author, I want identical normalized JSON to produce identical source, so that generated diagrams can be cached, compared, and audited reliably.

#### Acceptance Criteria

1. **R7.1** WHEN the same normalized document is serialized repeatedly with the same backend contract, THE Mermaid_IR_Tool SHALL produce byte-identical Mermaid source.
2. **R7.2** WHEN an ordered JSON collection is serialized, THE Mermaid_IR_Tool SHALL preserve its declared array order.
3. **R7.3** WHEN an unordered JSON object affects output, THE Mermaid_IR_Tool SHALL serialize its keys in a documented stable order.
4. **R7.4** WHEN text contains context-sensitive special characters, THE Mermaid_IR_Tool SHALL escape the text according to its Mermaid syntax context.
5. **R7.5** IF identifier sanitization creates a collision, THEN THE Mermaid_IR_Tool SHALL resolve the collision reproducibly.
6. **R7.6** WHEN optional sections are absent, THE Mermaid_IR_Tool SHALL omit their corresponding source statements.

### Requirement 8: Mermaid render verification

**User Story:** As a diagram consumer, I want generated source verified by Mermaid, so that accepted JSON produces renderable diagrams rather than merely plausible text.

#### Acceptance Criteria

1. **R8.1** WHEN render verification is requested, THE Mermaid_IR_Tool SHALL validate the exact source produced from the normalized document.
2. **R8.2** IF Mermaid reports a parser error, THEN THE Mermaid_IR_Tool SHALL report render verification as failed.
3. **R8.3** IF Mermaid produces its generated error-placeholder artifact, THEN THE Mermaid_IR_Tool SHALL report render verification as failed.
4. **R8.4** WHEN representative minimal and maximal documents for each supported target are verified, THE Mermaid_IR_Tool SHALL produce no Mermaid render error.

### Requirement 9: Coverage evidence and extensibility

**User Story:** As a skill maintainer, I want measurable target coverage, so that completeness claims and future target additions can be verified.

#### Acceptance Criteria

1. **R9.1** THE Coverage_Manifest SHALL map each supported Mermaid construct to its canonical JSON Pointer.
2. **R9.2** THE Coverage_Manifest SHALL classify each mapped field as compulsory or optional.
3. **R9.3** THE Coverage_Manifest SHALL record the default policy for each mapped field.
4. **R9.4** THE Coverage_Manifest SHALL identify serializer evidence for each mapped construct.
5. **R9.5** THE Coverage_Manifest SHALL identify verification evidence for each mapped construct.
6. **R9.6** IF a supported construct lacks any required coverage entry, THEN THE Mermaid_IR_Tool SHALL fail the coverage check.
7. **R9.7** WHEN an additional Mermaid target module is added, THE Mermaid_IR_Tool SHALL accept it without changing the canonical envelope fields.
8. **R9.8** IF a document selects an unsupported target, THEN THE Mermaid_IR_Tool SHALL reject it with a diagnostic listing supported targets.

### Requirement 10: Offline operation and interaction safety

**User Story:** As a local tool user, I want schema processing to be safe and offline, so that validation does not execute diagram behavior or depend on remote services.

#### Acceptance Criteria

1. **R10.1** WHEN a canonical or legacy document is validated, THE Mermaid_IR_Tool SHALL perform schema resolution without network access.
2. **R10.2** WHEN a document is normalized or serialized, THE Mermaid_IR_Tool SHALL perform the operation without network access.
3. **R10.3** WHEN a link or callback declaration is serialized, THE Mermaid_IR_Tool SHALL treat its value as data without executing it.
4. **R10.4** IF validation fails through the command-line interface, THEN THE Mermaid_IR_Tool SHALL return a nonzero exit status.
5. **R10.5** WHEN validation succeeds through the command-line interface, THE Mermaid_IR_Tool SHALL return a zero exit status.

### Requirement 11: Usable documentation

**User Story:** As a diagram author, I want accurate schema documentation and examples, so that I can construct canonical JSON without reading serializer code.

#### Acceptance Criteria

1. **R11.1** THE Mermaid_IR_Documentation SHALL identify every canonical envelope field as compulsory or optional.
2. **R11.2** THE Mermaid_IR_Documentation SHALL state the default policy for every optional field with a default.
3. **R11.3** THE Mermaid_IR_Documentation SHALL include a minimal canonical example for each supported target.
4. **R11.4** THE Mermaid_IR_Documentation SHALL include a feature-complete canonical example for each supported target.
5. **R11.5** THE Mermaid_IR_Documentation SHALL describe how to migrate a legacy document to canonical JSON.
6. **R11.6** THE Mermaid_IR_Documentation SHALL distinguish source configuration from initialization configuration.

## Risk Classification

- **Security:** Interaction values must remain inert data during processing; execution is out of
  scope.
- **Authorization and privacy:** No accounts, permissions, credentials, or personal-data storage
  are introduced.
- **Accessibility:** Source-level accessibility title and description are part of the canonical
  contract.
- **Performance:** Validation and serialization must remain local and deterministic; quantitative
  thresholds will be introduced only if baseline evidence shows a material regression risk.
- **Observability:** Stable JSON Pointer diagnostics and command exit status are externally visible
  evidence.
- **Migration and rollback:** Legacy input remains accepted through migration; the previous flat
  serializer behavior remains the compatibility baseline.
- **Rollout:** Canonical JSON can be adopted incrementally because legacy input remains valid.

## Approval

Status: **Approved on 2026-08-09 for the pinned 12-target snapshot**
