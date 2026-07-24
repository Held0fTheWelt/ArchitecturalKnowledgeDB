# ArchitecturalKnowledgeDB - Software Architecture (arc42)

**System:** `ArchitecturalKnowledgeDB`
**Repository:** `ArchitecturalKnowledgeDB`
**Kind:** standalone architecture knowledge service / Outer Tool
**Architecture system of record:** AKDB project `architectural-knowledge-db`
**Last reconciled to code:** `2026-07-23`
**Export rule:** generated from AKDB; do not hand-edit.

## 1. Introduction & Goals

ArchitecturalKnowledgeDB (AKDB) is a local-first, multi-project architecture knowledge service. It turns decisions, SAD sections, UML models, rules, repository evidence, memory, and planning records into queryable context for humans and agents.

For the `architectural-knowledge-db` self-project AKDB is the authoring system and source of truth: this document and its UML tree are deterministic exports of database state. For external projects, AKDB may instead index repository-owned sources without taking over their authority.

### 1.1 Quality goals

| Priority | Goal | Observable evidence |
| --- | --- | --- |
| 1 | Trustworthy authority | Every result retains project, authority level, origin, and staleness context. |
| 2 | Deterministic publication | Repeated SAD/UML exports from unchanged DB state are byte-identical. |
| 3 | Local-first operation | SQLite requires no service; PostgreSQL is optional for concurrent writers. |
| 4 | Agent usability | CLI, HTTP, and MCP expose the same project-aware service semantics. |
| 5 | Evolvability | Backend and publication differences stay behind explicit seams. |

### 1.2 Stakeholders

- Architecture maintainers author SAD, ADR, UML, rules, and mappings.
- Coding agents query context, recall, guardrails, reviews, and provenance through MCP.
- Tool developers integrate AKDB through Python, CLI, or HTTP.
- Operators run SQLite locally or PostgreSQL for shared multi-writer deployments.
- Documentation consumers read the generated, repository-local architecture mirror.

## 2. Constraints

- Python 3.11+ and a standalone repository; no Unreal Engine or Fab runtime dependency.
- SQLite is the zero-configuration default. PostgreSQL remains optional through `AKDB_DB_URL`.
- Self-architecture changes use supported AKDB SAD/UML commands, API routes, or MCP tools. Generated files are read-only mirrors.
- External repositories are read-only unless a separate workflow explicitly grants mutation authority.
- Project isolation is mandatory; shared knowledge is visible only through declared shared spaces.
- Imported corpora, runtime databases, backups, embeddings, and exports for other projects are never committed here.
- Secrets, credentials, personal data, and raw private corpora are outside the public Git boundary.

## 3. Context & Scope

AKDB sits between architecture authors, coding agents, project repositories, and publication targets.

- Maintainers and agents author/query through CLI, FastAPI, or MCP.
- `SadService`, `UMLService`, and `KnowledgeService` persist structured architecture.
- `ImportExportService` imports external authority contexts and exports DB-owned contexts.
- `RepositoryService` and `GitScanner` collect read-only provenance.
- Search, context, cognition, reasoning, completeness, review, and guardrail services consume the same knowledge spine.

See [C4 context](UML/components/c4-context.puml) and [authority contexts](UML/components/authority-contexts.puml).

### 3.1 Scope boundary

| In scope | Out of scope |
| --- | --- |
| Project registry, SAD/ADR/UML authoring, import/export, FTS and optional semantic recall, provenance, drift, cognition, planning, review, CLI/API/MCP. | Autonomous repository mutation, hosted identity service, general document management, model-provider ownership. |
| Root plus subsystem SADs and UML as DB-owned records. | Treating generated Markdown/PlantUML as an independent source of truth. |
| SQLite and PostgreSQL behind one facade. | ORM migration, pgvector, pooling, distributed jobs in v1. |

## 4. Solution Strategy

1. Use `knowledge_items` as the common identity and search spine; specialized tables carry domain detail.
2. Provide dedicated authoring services instead of private `_upsert_item` workflows.
3. Model SADs as parents with preamble, frontmatter, ordered sections, and ordered decisions.
4. Model UML diagrams, elements, and relationships in the DB and render deterministic projections.
5. Export multiple SADs by DB-owned `source_key`; assign UML through `sad_document_id`.
6. Keep persistence portable through the `Database` facade and five audited divergence seams.
7. Separate authority contexts: AKDB owns self-architecture; imported platform sources keep theirs.
8. Register the self-repository so drift checks compare architecture against real code.
9. Keep this Git limited to AKDB code, architecture, tests, operations, and examples.

## 5. Building Block View

See [C4 container](UML/components/c4-container.puml), [C4 component](UML/components/c4-component.puml), and [knowledge data model](UML/classes/knowledge-data-model.puml).

| Block | Responsibility | Main implementation |
| --- | --- | --- |
| CLI / FastAPI / MCP | Human, HTTP, and agent entry points. | `cli.py`, `api/app.py`, `mcp.py`, `mcp_stdio.py` |
| SadService | SAD document/section/decision lifecycle and `akdb://` provenance. | `services/sad.py` |
| UMLService | Diagram/element/relationship CRUD, parsing, rendering, export. | `services/uml.py` |
| ImportExportService | External imports, DB-native creation and update of canonical body owners with derived SAD/ADR/UML reconciliation, target projection, corpus export, and hierarchical multi-SAD export. | `services/import_export.py` |
| KnowledgeService | Item identity, authority, FTS, links, definitions, rules, ADRs. | `services/knowledge.py` |
| Project/Repository | Projects, spaces, repositories, source-root resolution. | `projects.py`, `repositories.py` |
| Search/Context/Recall | FTS, context packs, optional vectors, graph exploration. | `search.py`, `context.py`, `recall_backend.py` |
| Cognition/Authoring | Topics, MVPs, specs, questions, memory, reasoning, survey, roadmap. | `cognition.py`, `authoring.py`, `memory.py`, `reasoning.py`, `survey.py`, `roadmap.py` |
| Assurance | Completeness, consistency, staleness, review, guardrails, origin. | `completeness.py`, `consistency.py`, `staleness.py`, `review.py`, `guardrail.py`, `origin.py` |
| Persistence | Driver-neutral execution, selection, migrations, dual schema, and coalesced post-commit/rollback callbacks. | `db/database.py`, `connection.py`, `migrations.py`, `db/schema/` |

Detailed cognition and authoring behavior: [Agent-Authoring subsystem SAD](subsystems/agent-authoring/architecture.md).

## 6. Runtime View

### 6.1 DB-native SAD authoring and export

A client calls `SadService` through CLI, API, or MCP. It upserts a SAD parent plus structured children with `akdb://` provenance and FTS. `export_sad` renders ordered documents and assigned UML. A deterministic manifest removes only previously managed files that are no longer present while preserving supporting notes. See [authoring/export sequence](UML/sequence/sad-authoring-export-sequence.puml).

### 6.2 DB-native UML authoring

Clients create/update diagrams, elements, and relationships. Structural edits mark models dirty; rendering rebuilds PlantUML from DB state. Raw-source updates parse into structured records. Deletion cleans relationships, search rows, links, elements, and diagrams atomically.

### 6.3 External import and reingest

For file-authoritative projects, importers parse ADR, document, YAML/JSON/CSV, and UML. Reingest refreshes derived state and Git provenance without writing back. Authority is contextual, not globally file-first or DB-first.

### 6.4 Search, context, and cognition

Search uses SQLite FTS5 or PostgreSQL `tsvector`; LIKE/ILIKE is fallback. Context packs combine knowledge, rules, ADRs, UML, provenance, staleness, and authority. Cognition adds recall, topics, specs, MVPs, questions, memory, reasoning, review, and working sets.

### 6.5 Persistence request

`connect()` chooses SQLite unless `AKDB_DB_URL` selects PostgreSQL. Services call `Database`; it normalizes placeholders and rows. Migrations run at startup. See [database facade](UML/components/database-facade.puml) and [PostgreSQL sequence](UML/sequence/postgres-request-sequence.puml).

### 6.6 Drift and provenance

The self-repository is scanned read-only. Findings are advisory; corrections are authored in AKDB and re-exported.

### 6.7 Export-target destination resolution

Incremental export, full synchronization, and freshness verification all ask `ExportTargetsService` to resolve the destination. An explicit absolute destination remains absolute after root/path-traversal validation. A relative destination is bound to the target's registered repository: an existing registered `local_path` wins; a source-root candidate or current checkout is accepted only when its sanitized Git remote matches the registration. If repository identity cannot be proven, export fails before any write. See [authoring/export sequence](UML/sequence/sad-authoring-export-sequence.puml).

### 6.8 Target-specific document projection

Imported document bodies retain links relative to their canonical `repo_source_key`. During verification, incremental export, and full synchronization, Markdown links outside fenced examples are projected to the target layout: links to exported SAD, ADR, or UML artifacts point to their mirror locations; links to non-exported repository or adjacent-workspace artifacts are rebased from their canonical relative locations when the target is repository-relative. External URLs, fragments, and explicit repository-root references remain unchanged. Exactly one knowledge item may own `body_text` for a `repo_source_key`; derived structured records may share the key but cannot compete as export payloads.

### 6.9 DB-native creation and update of canonical documents

A client submits a registered repository id, safe `repo_source_key`, complete body, supported encoding, and explicit `body_origin=canonical` through CLI, API, or MCP. Create requires no existing owner, creates one AKDB-provenance body owner, builds links and derived SAD records, and creates the matching structured ADR or UML record. Update requires exactly one owner, preserves its stable identity, replaces stale links and SAD children, and synchronizes structured ADR/UML state. SAD reconciliation recognizes simple (`D1`), descriptive (`D-DB`), and scoped numbered (`B-D1`, `C-T1`) decision identifiers; when a decision has no inline status, its summary-table status is retained as structured state. Unsafe paths, collisions, missing or ambiguous owners, reclassification, structurally unmatched UML, and exact generated-projection feedback fail closed. See [canonical document authoring sequence](UML/sequence/canonical-document-update-sequence.puml).

### 6.10 Commit-bound target publication

Supported write surfaces transact through the `Database` facade. Canonical state and durable dirty rows commit before a coalesced callback drains and projects enabled targets. Rollback clears the callback and cannot write a mirror. A post-commit projection failure rolls back the drain, retains repair work, and leaves the committed canonical body authoritative until a later flush succeeds. Full target verification remains the byte-level publication oracle. Structured AKDB self-SAD/UML and ADR exports remain a separate workflow and do not use a generic body-owner mirror target. See [ADR-AKDB-0005](../adr/adr-akdb-0005-db-native-canonical-creation-and-commit-bound-publication.md).

## 7. Deployment View

See [dual-backend deployment](UML/deployment/dual-backend-deployment.puml).

| Mode | Storage | Intended use |
| --- | --- | --- |
| CLI / MCP local | SQLite in `.akdb/` | One maintainer or agent-owned process. |
| FastAPI local | SQLite or PostgreSQL | Shared HTTP/admin access. |
| Compose default | SQLite volume | Zero-setup container. |
| Compose PostgreSQL override | PostgreSQL 16 | Concurrent API, CLI, MCP, agents. |

Configuration includes `AKDB_DATABASE_PATH`, `AKDB_DATA_ROOT`, `AKDB_DB_URL`, `AKDB_DEFAULT_PROJECT`, `AKDB_SOURCE_ROOT`, `AKDB_RECALL_BACKEND`, and `AKDB_EMBED_URL`. PostgreSQL backup uses `pg_dump`; SQLite uses a consistent backup operation. Runtime DBs and backups are ignored.

Portable export targets store a repository id plus a repository-relative destination such as `docs/architecture/_generated`. Workstation-specific absolute repository paths remain registration data; restored snapshots resolve only to a checkout whose identity matches the registered Git remote.

## 8. Crosscutting Concepts

- **Authority context:** self-project is DB-owned; imported contexts retain declared external authority.
- **Stable identity:** deterministic UIDs derive from project, item type, and local id.
- **Project isolation:** every record belongs to a project/space; shared visibility is explicit.
- **Provenance:** DB-authored architecture uses `akdb://`; imports preserve external origins.
- **Determinism:** ordered metadata and UTF-8/LF rendering make exports reproducible.
- **Search:** all knowledge uses the shared FTS spine; embeddings are optional acceleration.
- **Backend portability:** differences stay in database, connection, migration, search, backup seams.
- **Transactions:** CLI/API/MCP commit success and roll back failure.
- **Export safety:** empty, current, parent-traversal, and filesystem-root destinations are rejected. Relative destinations require a registered repository and fail closed unless an existing registration path or matching Git checkout proves the target boundary.
- **Projection-safe references:** canonical Markdown retains repository-relative intent; the export layer rebases local links against the mirror layout without changing the stored body or fenced examples.
- **Single body owner:** one and only one item with `body_text` supplies each `repo_source_key`; structured derivatives are never selected nondeterministically as file payloads.
- **Public boundary:** only AKDB-owned architecture is exported here.
- **Canonical authoring:** canonical bodies are created or updated by stable `repo_source_key` with explicit `body_origin=canonical`, never by reviving a retired source file or editing a generated mirror.
- **Derivative reconciliation:** canonical creation/update keeps body owners, links, SAD children, structured ADRs, and structured PlantUML records consistent in the authoritative transaction.
- **Commit-bound publication:** canonical data and dirty rows commit before target I/O; rollback writes no mirror and failed publication retains repair work.

## 9. Architecture Decisions

| ID | Title | Status |
| --- | --- | --- |
| D1 | Active standalone Outer Tool classification | Accepted |
| D2 | Authority is project-context dependent | Accepted |
| D3 | CLI, API, and MCP share one service model | Accepted |
| D4 | Registered repositories are read-only by default | Accepted |
| D5 | Website and Atlas are curated projections | Accepted |
| D-DB | SQLite default, PostgreSQL opt-in through Database facade | Accepted |
| D-SoR | AKDB is system of record for its own architecture | Accepted |
| D-SAD | SAD and UML authoring use supported DB-native services | Accepted |
| D-MULTI | Root and subsystem SADs export hierarchically | Accepted |
| D-EXPORT | Relative export destinations are repository-bound and fail closed | Accepted |
| D-PROJECTION | Target mirrors rebase canonical links and require one body owner | Accepted |
| D-CANON-UPDATE | Existing canonical documents update by stable DB identity | Accepted |
| D-CANON-CREATE | New canonical documents are DB-owned from the first write | Accepted |
| D-COMMIT-EXPORT | Generated targets publish only after authoritative commit | Accepted |

### D1: Active standalone Outer Tool classification

**Status:** Accepted

AKDB is a standalone Python architecture knowledge service, not an Unreal plugin or Fab package.

### D2: Authority is project-context dependent

**Status:** Accepted

AKDB is authoritative for DB-owned projects. Imported projects retain owning-file authority unless a migration transfers it. Reads expose source URI and authority.

### D3: CLI, API, and MCP share one service model

**Status:** Accepted

All public surfaces call the same project-aware services and transaction semantics.

### D4: Registered repositories are read-only by default

**Status:** Accepted

Repository registration and Git scanning collect provenance only; mutation needs a separate explicit workflow.

### D5: Website and Atlas are curated projections

**Status:** Accepted

Public catalog content presents AKDB but is not runtime or architecture authority.

### D-DB: SQLite default, PostgreSQL opt-in through Database facade

**Status:** Accepted

SQLite is default; `AKDB_DB_URL` opts into PostgreSQL. Services use the facade and backend branches remain confined.

### D-SoR: AKDB is system of record for its own architecture

**Status:** Accepted

The self-project owns this SAD and assigned UML as DB records. `docs/architecture` is generated.

### D-SAD: SAD and UML authoring use supported DB-native services

**Status:** Accepted

SadService and UMLService are exposed through CLI, API, and MCP. Private item upserts are not an authoring workflow.

### D-MULTI: Root and subsystem SADs export hierarchically

**Status:** Accepted

Each SAD owns an export source_key; diagrams carry sad_document_id; export never mixes children.

### D-EXPORT: Relative export destinations are repository-bound and fail closed

**Status:** Accepted

Export targets bind a destination to a registered repository. Existing registered paths are authoritative locally; restored-checkout fallbacks require a matching sanitized Git remote. Unsafe roots and traversal are rejected, and unresolved repository identity stops the operation before writes. See [ADR-AKDB-0002](../adr/adr-akdb-0002-bind-relative-export-destinations-to-registered-repositories.md).

### D-PROJECTION: Target mirrors rebase canonical links and require one body owner

**Status:** Accepted

Canonical document bodies retain repository-source link semantics. Verification, incremental export, and full synchronization apply the same target-specific Markdown projection. Exportable SAD/ADR/UML links resolve inside the mirror; non-exported repository and adjacent-workspace artifacts resolve from their canonical relative locations when possible. Fenced examples, external URLs, fragments, and explicit repository-root references are unchanged. Multiple `body_text` owners for one `repo_source_key` are rejected. See [ADR-AKDB-0003](../adr/adr-akdb-0003-project-canonical-links-into-target-mirrors.md).

### D-CANON-UPDATE: Existing canonical documents update by stable DB identity

**Status:** Accepted

An existing imported canonical body changes only through the validated canonical-document update operation with explicit `body_origin=canonical`. The operation requires a registered repository and one body owner, preserves the owner UID, rejects exact generated-projection feedback, reconciles links and imported SAD children, and synchronizes structured ADR/UML state. The SAD parser preserves simple, descriptive, and scoped numbered decision IDs plus table-only status values instead of collapsing scoped decisions into a synthetic wrapper. See [ADR-AKDB-0004](../adr/adr-akdb-0004-update-imported-canonical-documents-by-stable-db-identity.md).

### D-CANON-CREATE: New canonical documents are DB-owned from the first write

**Status:** Accepted

Canonical creation requires explicit `body_origin=canonical`, a registered repository, a safe unused `repo_source_key`, and collision-free identity. It creates the body owner and links plus derived SAD records, a structured ADR for ADR paths, or a structured UML record for supported UML paths. See [ADR-AKDB-0005](../adr/adr-akdb-0005-db-native-canonical-creation-and-commit-bound-publication.md).

### D-COMMIT-EXPORT: Generated targets publish only after authoritative commit

**Status:** Accepted

Supported writes persist canonical state and dirty rows before target I/O. A coalesced post-commit callback performs incremental publication; rollback clears the callback, and projection failure retains dirty repair work while canonical state stays authoritative. Structured self-export remains separate from repository body-owner targets. See [ADR-AKDB-0005](../adr/adr-akdb-0005-db-native-canonical-creation-and-commit-bound-publication.md).

## 10. Quality Requirements

| Quality | Scenario | Evidence |
| --- | --- | --- |
| DB-native authoring | SAD/UML CRUD and export require no file edit. | `test_sad_authoring.py`, `test_uml.py`, CLI/API/MCP tests |
| Multi-SAD isolation | Root/subsystem exports never mix. | multi-SAD export test |
| Backend parity | Same behavior passes SQLite and PostgreSQL. | parametrized pytest |
| Project isolation | No undeclared cross-project leakage. | `test_project_isolation.py` |
| Determinism | Unchanged DB exports byte-identically. | round-trip and export verification |
| Export boundary safety | A relative mirror resolves to its registered repository; an unrelated checkout is rejected before writes. | `tests/services/test_export_targets.py`, export sync/verify tests |
| Projection integrity | Full sync, incremental export, and verification derive identical target-relative Markdown links from canonical source paths; fenced examples remain verbatim. | `tests/services/test_export_sync.py` |
| Canonical payload uniqueness | Ambiguous `body_text` owners fail instead of making row-order-dependent output. | export sync/incremental tests |
| Canonical authoring safety | New or existing canonical bodies change without a source-side authoring file; explicit origin, traversal, duplicates, missing owners, ambiguity, and projection feedback fail closed. | `tests/services/test_canonical_document_update.py`, CLI/API/MCP tests |
| Derivative consistency | SAD children and links reconcile; canonical ADR creation/update and structured UML source remain equal to their body owner. | canonical-document authoring service tests |
| Transactional publication | Rollback leaves the mirror untouched; successful commit triggers one coalesced export; failed publication retains dirty repair work. | `tests/services/test_export_autoflush.py` |
| Provenance | Self uses `akdb://`; imports retain origins. | authoring tests |
| Agent compatibility | MCP authoring and retrieval tools dispatch consistently. | MCP tests |

## 11. Risks & Technical Debt

| Risk / debt | Impact | Mitigation |
| --- | --- | --- |
| New authoring API shapes | Early clients may couple tightly. | Typed models and surface-parity tests. |
| Partial PlantUML grammar | Complex macros remain passthrough. | Preserve raw until edit; expand fixtures before syntax. |
| Multi-SAD diagram ambiguity | Unassigned diagrams lack owner. | Require `sad_document_id` for multi-SAD export. |
| No PostgreSQL pool | High concurrency opens connections. | Add after measurement. |
| Backend ranking variance | Result order can differ. | Test relevance invariants. |
| Mixed authority contexts | Users may trust wrong owner. | Always surface URI and authority. |
| Unavailable repository registration | Portable snapshot export cannot resolve its destination. | Fail closed; restore a valid registration path or run in a checkout with the registered sanitized remote. |
| Absolute external export target | A target outside the registered repository has no provable path back to non-mirrored repository files. | Preserve unresolved source links; prefer repository-relative targets for complete projections. |
| Unsupported Markdown link syntax | Reference definitions or unusual inline syntax may not be projected. | Keep projection parser deliberately narrow, test observed syntax, and fail link gates on unresolved targets. |
| Canonical create/update parser failure or unsupported derived format | Body and structured records could diverge. | Validate before commit, reject identity collisions, require exactly one structured UML match on update, and verify the target mirror. |
| Post-commit target I/O failure | Canonical state is current while a projection is stale. | Roll back the dirty-queue drain, report the failure, retry flush, and use full target verification as the oracle. |
| Generated file edits | Changes vanish. | README warning and deterministic CI gate. |

## 12. Glossary

| Term | Meaning |
| --- | --- |
| DB-native | Authored through supported AKDB mutation surfaces with `akdb://` provenance. |
| SAD | Parent record plus structured preamble, sections, and decisions. |
| Self-project | `architectural-knowledge-db`, owned by AKDB. |
| Authority context | Per-project rule defining AKDB or external ownership. |
| Generated mirror | Deterministic Markdown/PlantUML projection, never hand-authored. |
| Canonical body owner | The single AKDB item whose `body_text` and `repo_source_key` define one projected file. |
| Commit-bound publication | Target I/O scheduled only after the authoritative database transaction commits. |
| Context pack | Ranked task-specific architecture evidence. |
| Knowledge spine | `knowledge_items`, links, and FTS shared by domain records. |

## 13. Architecture Map

| Area | SAD / UML |
| --- | --- |
| Whole system | This SAD and [root UML](UML/) |
| Agent authoring, cognition, recall, specs, lifecycle | [Subsystem SAD](subsystems/agent-authoring/architecture.md) and [UML](subsystems/agent-authoring/UML/) |
| Storage decision | [ADR-AKDB-0001](../adr/ADR-AKDB-0001-dual-backend.md) and [backend note](dual-backend.md) |
| Operations | [PostgreSQL](../operations/postgres.md), [MCP](../operations/MCP.md) |
