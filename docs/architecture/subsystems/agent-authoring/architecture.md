---
id: AKDB-SAD-AGENT-AUTHORING
links: []
owns-adrs: []
plugins: []
status: current
supersedes:
- SAD-PROJECT-AKDB-AGENT-AUTHORING
type: subsystem-sad
uml-package: subsystems/agent-authoring/UML
---

# AKDB Agent-Authoring Data Model - Software Architecture (arc42)

**System:** `ArchitecturalKnowledgeDB`
**Scope:** cognition, authoring, completeness, memory, reasoning, roadmap and semantic recall
**Status:** current; code-backed
**Architecture system of record:** AKDB project `architectural-knowledge-db`
**Last reconciled to code:** `2026-07-23`
**Export rule:** generated from AKDB; do not hand-edit.

## 1. Introduction & Goals

This subsystem turns AKDB from a searchable store into an architecture workbench for agents and maintainers. It captures knowledge, proposes topics, structures MVPs and specs, checks completeness, traverses typed relationships, remembers useful items, and produces grounded briefs and plans.

The subsystem is internal to AKDB. Tiny Tool Observatory, coding agents, and other framework tools are consumers or integration contexts; their runtime data and architecture are not owned by this repository.

### 1.1 Quality goals

| Priority | Goal | Evidence |
| --- | --- | --- |
| 1 | Grounded cognition | Recall and review return item identity, source and graph context instead of unsupported prose. |
| 2 | Implementable specs | Completeness gates require archetype diagrams and element-to-file mappings before `ready`. |
| 3 | Deterministic authoring | IDs, ordering, exports and plans are stable for unchanged DB state. |
| 4 | Incremental memory | Usage, pinning, decay and working sets refine retrieval without replacing authority. |
| 5 | Interface parity | Agent workflows are reachable through supported services and MCP; core architecture CRUD also reaches CLI and API. |

### 1.2 Stakeholders

- Coding agents use recall, exploration, authoring, review, guardrails and spec-to-plan tools.
- Architecture maintainers curate topics, decisions, specs, mappings and readiness.
- Operators choose SQLite or PostgreSQL and may configure an external embedding endpoint.
- Downstream tools consume compact responses or exported architecture projections.

### 1.3 Implementation ledger

| Capability | State | Code evidence |
| --- | --- | --- |
| Recall, explore, remember, delta and working set | Implemented | `services/cognition.py`, `memory.py`, `recall_backend.py` |
| Topic, MVP, spec, question and file-map authoring | Implemented | `services/authoring.py` |
| Completeness and ready gate | Implemented | `services/completeness.py`, `archetype_requirements.yml` |
| Roadmap and topic timeline | Implemented | `services/roadmap.py` |
| Connect, tensions and gaps | Implemented | `services/reasoning.py` |
| Survey, context and brief | Implemented | `services/survey.py`, `context.py` |
| Review and change guardrails | Implemented | `services/review.py`, `guardrail.py` |
| Optional vector/hybrid recall | Implemented seam; external endpoint operationally optional | `services/recall_backend.py` |
| DB-native SAD/UML authoring and hierarchical export | Implemented | `services/sad.py`, `uml.py`, `import_export.py` |

## 2. Constraints

- New concepts reuse `knowledge_items`, typed `knowledge_links`, FTS and project isolation before a specialized table is introduced.
- Topic, MVP, spec and question records use project-note authority unless explicitly promoted by another governed workflow.
- Relations are links-first. Dedicated tables require a demonstrated query or integrity need.
- Completeness contracts are package-owned, versioned inputs; readiness is never inferred from prose alone.
- SQLite and PostgreSQL must execute the same domain-service behavior. Backend-specific SQL remains in the database facade, migrations or explicitly documented seams.
- Semantic recall is optional. FTS and graph traversal remain a complete local baseline.
- Registered repositories are scanned read-only. File/symbol mappings are claims with provenance, not permission to mutate a repository.
- SAD/UML for this project is authored in AKDB and only exported to `docs/architecture`; export files are not re-imported as an editing loop.
- Runtime databases, embeddings, private corpora, credentials and generated exports for other projects stay outside Git.

## 3. Context & Scope

The subsystem receives requests through the shared application surfaces and works against the same project-scoped knowledge graph as the rest of AKDB.

### 3.1 In scope

- Alias-aware FTS and optional hybrid semantic recall.
- Typed neighborhood exploration and bounded graph paths.
- Topic, MVP, spec and question lifecycles.
- Archetype completeness, UML requirements and file/symbol mappings.
- Adaptive memory, working sets, deltas, grounded citations, briefs and reviews.
- Deterministic roadmap/spec/topic export as part of the broader corpus exporter.
- DB-native SAD/UML maintenance for architecture documentation.

### 3.2 Out of scope

- Model inference, autonomous code modification, repository write authority and deployment orchestration.
- Ownership of Tiny Tool Observatory or other consumers' internal data.
- Guaranteeing availability or correctness of an optional third-party embedding service.

See [system context](UML/components/c4-context.puml), [containers](UML/components/c4-container.puml), [components](UML/components/c4-component.puml) and [use cases](UML/use-cases/akdb-agent-authoring-use-cases.puml).

## 4. Solution Strategy

1. Extend the common knowledge spine so every authored entity inherits project identity, authority, FTS, links and provenance.
2. Keep orchestration in focused services: cognition reads, authoring writes, completeness gates, roadmap orders, reasoning traverses, memory adapts and survey composes.
3. Express relations as typed graph edges and traverse them with explicit hop limits.
4. Separate deterministic lexical retrieval from optional semantic candidates behind `RecallBackend`.
5. Require grounded results: item IDs, citations, link paths or concrete validation findings accompany conclusions.
6. Maintain spec readiness as a state transition guarded by completeness, not as an arbitrary field update.
7. Preserve stable order for MVP sequence, export paths and generated plans.
8. Expose the capabilities through MCP without duplicating persistence logic.

## 5. Building Block View

| Component | Responsibility |
| --- | --- |
| `CognitionService` | `recall`, `explore`, `remember`, recall deltas and working sets. |
| `AuthoringService` | Topics, MVPs, specs, questions, file mappings, reuse search and spec-to-plan. |
| `CompletenessService` | Archetype requirements, missing UML/elements/mappings and ready gate evidence. |
| `RoadmapService` | Global MVP order and per-topic timelines. |
| `ReasoningService` | Bounded connections, tensions and architecture gaps. |
| `MemoryService` | Use count, recency, boost, pinning and decay. |
| `SurveyService` | Compact/full overview, authoring context and topic brief. |
| `ReviewService` | Aggregated review of an item and its architectural neighborhood. |
| `GuardrailService` | Evaluates proposed changes against rules and constraints. |
| `RecallBackend` | FTS baseline and optional vector/hybrid implementation. |
| `KnowledgeService` | Shared item/link/FTS identity spine. |
| `SadService` / `UMLService` | Supported architecture authoring surface used by this subsystem's own documentation. |

The [data model](UML/classes/akdb-agent-authoring-data-model.puml) and [component view](UML/components/c4-component.puml) define their structural relationships.

## 6. Runtime View

### 6.1 Recall and exploration

`recall` resolves candidates through the configured backend, blends memory signals, loads typed neighbors and returns grounded hits. `explore` starts from a concrete item and follows selected relationship types within a bounded depth. See [recall sequence](UML/sequence/recall-sequence.puml).

### 6.2 Spec completeness and readiness

A spec references an archetype and its UML/file mappings. `spec_validate` compares it to the packaged contract and persists blocking findings and warnings. `set_spec_status(..., ready)` invokes the gate and rejects incomplete specs. See [validation sequence](UML/sequence/spec-validate-sequence.puml) and [validation activity](UML/flow/completeness-validation-activity.puml).

### 6.3 MVP and roadmap authoring

`create_mvp` assigns the next project sequence and may suggest a predecessor on the same topic. Roadmap queries remain stable by sequence and expose contextual topic/spec links. See [MVP sequence](UML/sequence/mvp-predecessor-sequence.puml) and [MVP lifecycle](UML/states/mvp-lifecycle-states.puml).

### 6.4 Questions, reasoning and planning

Questions remain open until explicitly resolved with a reference. Reasoning searches bounded paths, tensions and completeness gaps. `spec_to_plan` turns a validated spec into ordered implementation steps. See [question lifecycle](UML/states/question-lifecycle-states.puml) and [spec-to-plan](UML/sequence/spec-to-plan-sequence.puml).

### 6.5 Adaptive and composite cognition

Use recording, pinning and decay alter ranking signals without changing source authority. Review, check-change and brief compose multiple grounded services. See [adaptive ranking](UML/flow/adaptive-ranking-activity.puml) and [composite cognition](UML/sequence/composite-cognition-sequence.puml).

### 6.6 Semantic recall

When configured, embeddings are stored with model and content hash and hybridized with the lexical baseline. Failure or absence of the endpoint leaves FTS behavior available. See [semantic recall](UML/sequence/semantic-recall-sequence.puml).

### 6.7 Architecture authoring

SAD documents, ordered sections/decisions and associated UML are maintained through DB-native service surfaces. Multi-document export writes the root and this subsystem beneath their DB-owned `source_key` values.

## 7. Deployment View

The subsystem runs inside the AKDB process and has no separate deployment unit.

- Local default: Python process plus SQLite/FTS database.
- Shared opt-in: the same process plus PostgreSQL selected by `AKDB_DB_URL`.
- Optional semantics: HTTP embedding endpoint configured for `LLMStoreEmbeddingClient`; not required for lexical or graph recall.
- Interfaces: local CLI, FastAPI service/admin UI, or MCP stdio.
- Publication: deterministic files under `docs/architecture` and other explicitly selected export roots.

SQLite and PostgreSQL are alternative stores, not automatically synchronized replicas. The database facade, schema migrations and test matrix protect behavioral parity. Secrets for PostgreSQL or embeddings are runtime configuration and never committed.

## 8. Crosscutting Concepts

### Identity and project isolation

Every entity has a stable UID and project ID. Cross-space reads are opt-in. Local IDs are meaningful within their project/type boundary.

### Authority and grounding

Memory scores and semantic similarity affect relevance, never authority. Results retain source URIs, item UIDs and link evidence. DB-native self-architecture uses `akdb://` provenance; external imports retain their owning source.

### Determinism

Stable IDs, explicit sequence fields, normalized paths, sorted result sets and LF UTF-8 rendering make exports and plans reproducible.

### Transactions and backend parity

A request uses one database connection and commits or rolls back at its surface boundary. Domain services use the facade's common SQL subset; PostgreSQL-only behavior is confined and tested.

### Security and privacy

Repository access is read-only. Tokens and DSNs are runtime-only. Private corpora and embeddings do not enter the public repository. Tool responses are compact by default to reduce accidental data disclosure and context waste.

### Failure behavior

Unknown IDs, unsafe export paths, invalid state transitions and incomplete specs fail explicitly. Optional semantic failure does not invalidate the lexical baseline.

## 9. Architecture Decisions

| ID | Decision | Status |
| --- | --- | --- |
| D1 | DB-native authoring | Accepted |
| D2 | Enforced per-archetype completeness and file map | Accepted |
| D3 | Topics are curated, agent-proposed and FTS-deduplicated | Accepted |
| D4 | Extend the knowledge-item spine | Accepted |
| D5 | Use links first and promote only on measured need | Accepted |
| D6 | Return cognition rather than dumps | Accepted |
| D7 | Reason over the typed graph | Accepted |
| D8 | Provide scaffold, reuse and spec-to-plan leverage | Accepted |
| D9 | Add adaptive memory without changing authority | Accepted |
| D10 | Keep semantic, temporal and working-set recall pluggable | Accepted |
| D11 | Compose review, guardrail and brief capabilities | Accepted |

### D1: DB-native authoring

**Status:** Accepted

Architecture records owned by AKDB are created and changed through supported services. Markdown and PlantUML are deterministic projections. This removes the two-truth edit loop while preserving reviewable files.

### D2: Enforced per-archetype completeness and file map

**Status:** Accepted

A spec reaches `ready` only after its archetype requirements and implementation mappings validate. The gate returns concrete blocking evidence rather than relying on author confidence.

### D3: Topics are curated, agent-proposed and FTS-deduplicated

**Status:** Accepted

Agents may propose topics, but identity is normalized and checked against existing knowledge. Human curation keeps the thematic vocabulary useful and prevents uncontrolled duplication.

### D4: Extend the knowledge-item spine

**Status:** Accepted

Topics, MVPs, specs, questions and SAD children reuse `knowledge_items` plus thin side tables or metadata. They inherit project isolation, authority, FTS, links and provenance.

### D5: Use links first and promote only on measured need

**Status:** Accepted

Semantic relations begin as typed `knowledge_links`. A dedicated relation table is introduced only when integrity or measured query performance cannot be met by the indexed graph.

### D6: Return cognition rather than dumps

**Status:** Accepted

Agent tools return ranked neighborhoods, paths, tensions, gaps and citations. Compact responses are the default; bulk source material requires an explicit deeper request.

### D7: Reason over the typed graph

**Status:** Accepted

Connections, tensions and gaps are derived from project-scoped graph structure and completeness evidence. Traversal is bounded and its path is returned so conclusions remain inspectable.

### D8: Provide scaffold, reuse and spec-to-plan leverage

**Status:** Accepted

Authoring helpers turn context into concrete scaffolds, reuse candidates and ordered test-first plan steps while leaving acceptance and repository mutation to the maintainer.

### D9: Add adaptive memory without changing authority

**Status:** Accepted

Usage, decay, boosts and pins influence relevance only. They cannot promote an item above explicit authority constraints or erase source/provenance evidence.

### D10: Keep semantic, temporal and working-set recall pluggable

**Status:** Accepted

FTS is the always-available baseline. Vector candidates, recall deltas and working sets add optional views through defined seams and carry model/content identity.

### D11: Compose review, guardrail and brief capabilities

**Status:** Accepted

Higher-level cognition composes focused services instead of creating a second reasoning store. Review, check-change and brief retain the same item/link evidence as their components.

## 10. Quality Requirements

| Scenario | Required response |
| --- | --- |
| Agent asks for a concept using an alias. | Return ranked, source-grounded candidates and typed neighbors without a corpus dump. |
| Maintainer marks an incomplete spec ready. | Reject the transition and list missing diagrams, elements or file mappings. |
| Same project is exported twice without DB changes. | Managed SAD/UML files are byte-identical. |
| Semantic endpoint is absent. | FTS recall, graph exploration and authoring remain functional. |
| Two projects use the same local ID. | Queries and mutations remain isolated by project. |
| PostgreSQL is selected. | The same service/API/MCP tests pass without domain-layer backend branches. |
| A repository is registered. | Scan provenance without changing the repository. |
| A change violates an active rule. | `check_change` returns grounded guardrail findings. |

## 11. Risks & Technical Debt

| Risk | Impact | Mitigation / status |
| --- | --- | --- |
| Semantic endpoint quality or availability varies. | Hybrid ranking may degrade. | Optional seam, content hashes, model identity and FTS fallback. |
| Metadata JSON carries some typed child fields. | Weak schema constraints. | Pydantic service inputs, focused tests; promote only when integrity/query pressure justifies it. |
| Memory signals can over-amplify frequently used items. | Retrieval bias. | Bounded boosts, decay, pin controls and preserved authority ranking. |
| Graph traversal grows with dense links. | Latency/context growth. | Hop limits, relationship filters and compact responses. |
| SQLite concurrent writers contend. | Busy failures under shared use. | Busy timeout locally; PostgreSQL is the opt-in multi-writer deployment. |
| External imported facts become stale. | Misleading context. | Repository provenance, staleness checks, reingest and source URI retention. |
| Export files are hand-edited. | DB/projection divergence. | Generated header, documented DB-native commands and deterministic overwrite. |
| CLI/API/MCP surface parity may drift. | Inconsistent workflows. | Shared services plus surface contract tests. |

## 12. Glossary

| Term | Meaning |
| --- | --- |
| Topic | Curated thematic anchor used to relate MVPs, specs and knowledge. |
| MVP | Ordered delivery slice with intent, topics, specs and predecessor/context edges. |
| Spec | Archetype-governed design record that must pass completeness before `ready`. |
| Question | Explicit unresolved issue that is later resolved by a reference. |
| Completeness contract | Packaged requirements for diagrams, elements and mappings by archetype. |
| File map | Relationship from a UML element to a concrete repository path and optional symbol. |
| Recall backend | Candidate retrieval seam; FTS baseline or optional vector/hybrid implementation. |
| Working set | Agent-maintained shortlist of relevant item references. |
| Item memory | Usage, recency, boost and pin state used as a ranking signal. |
| Grounding | Item/source/link evidence that supports a returned conclusion. |
| Composite cognition | Review, change checking and briefing assembled from focused services. |
| Projection | Deterministically exported file representation of DB-owned architecture. |

## 13. Architecture Map

| Concern | Diagram |
| --- | --- |
| System boundary | [C4 context](UML/components/c4-context.puml) |
| Runtime containers | [C4 container](UML/components/c4-container.puml) |
| Internal services | [C4 component](UML/components/c4-component.puml) |
| Entity relationships | [Agent-authoring data model](UML/classes/akdb-agent-authoring-data-model.puml) |
| Supported interactions | [Use cases](UML/use-cases/akdb-agent-authoring-use-cases.puml) |
| Recall | [Recall sequence](UML/sequence/recall-sequence.puml) |
| Spec validation | [Spec validation sequence](UML/sequence/spec-validate-sequence.puml) |
| Completeness decisions | [Completeness activity](UML/flow/completeness-validation-activity.puml) |
| MVP ordering | [MVP/predecessor sequence](UML/sequence/mvp-predecessor-sequence.puml) |
| Spec planning | [Spec-to-plan sequence](UML/sequence/spec-to-plan-sequence.puml) |
| Adaptive ranking | [Adaptive ranking activity](UML/flow/adaptive-ranking-activity.puml) |
| Composite cognition | [Composite cognition sequence](UML/sequence/composite-cognition-sequence.puml) |
| Optional semantics | [Semantic recall sequence](UML/sequence/semantic-recall-sequence.puml) |
| Topic/spec lifecycle | [Spec lifecycle](UML/states/spec-lifecycle-states.puml) |
| MVP lifecycle | [MVP lifecycle](UML/states/mvp-lifecycle-states.puml) |
| Question lifecycle | [Question lifecycle](UML/states/question-lifecycle-states.puml) |
| Decision-to-view coverage | [Traceability](UML/TRACEABILITY.puml) |
