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
| ImportExportService | External imports, corpus export, hierarchical multi-SAD export. | `services/import_export.py` |
| KnowledgeService | Item identity, authority, FTS, links, definitions, rules, ADRs. | `services/knowledge.py` |
| Project/Repository | Projects, spaces, repositories, source-root resolution. | `projects.py`, `repositories.py` |
| Search/Context/Recall | FTS, context packs, optional vectors, graph exploration. | `search.py`, `context.py`, `recall_backend.py` |
| Cognition/Authoring | Topics, MVPs, specs, questions, memory, reasoning, survey, roadmap. | `cognition.py`, `authoring.py`, `memory.py`, `reasoning.py`, `survey.py`, `roadmap.py` |
| Assurance | Completeness, consistency, staleness, review, guardrails, origin. | `completeness.py`, `consistency.py`, `staleness.py`, `review.py`, `guardrail.py`, `origin.py` |
| Persistence | Driver-neutral execution, selection, migrations, dual schema. | `db/database.py`, `connection.py`, `migrations.py`, `db/schema/` |

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
- **Public boundary:** only AKDB-owned architecture is exported here.

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

## 10. Quality Requirements

| Quality | Scenario | Evidence |
| --- | --- | --- |
| DB-native authoring | SAD/UML CRUD and export require no file edit. | `test_sad_authoring.py`, `test_uml.py`, CLI/API/MCP tests |
| Multi-SAD isolation | Root/subsystem exports never mix. | multi-SAD export test |
| Backend parity | Same behavior passes SQLite and PostgreSQL. | parametrized pytest |
| Project isolation | No undeclared cross-project leakage. | `test_project_isolation.py` |
| Determinism | Unchanged DB exports byte-identically. | round-trip and export verification |
| Export boundary safety | A relative mirror resolves to its registered repository; an unrelated checkout is rejected before writes. | `tests/services/test_export_targets.py`, export sync/verify tests |
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
| Generated file edits | Changes vanish. | README warning and deterministic CI gate. |

## 12. Glossary

| Term | Meaning |
| --- | --- |
| DB-native | Authored through supported AKDB mutation surfaces with `akdb://` provenance. |
| SAD | Parent record plus structured preamble, sections, and decisions. |
| Self-project | `architectural-knowledge-db`, owned by AKDB. |
| Authority context | Per-project rule defining AKDB or external ownership. |
| Generated mirror | Deterministic Markdown/PlantUML projection, never hand-authored. |
| Context pack | Ranked task-specific architecture evidence. |
| Knowledge spine | `knowledge_items`, links, and FTS shared by domain records. |

## 13. Architecture Map

| Area | SAD / UML |
| --- | --- |
| Whole system | This SAD and [root UML](UML/) |
| Agent authoring, cognition, recall, specs, lifecycle | [Subsystem SAD](subsystems/agent-authoring/architecture.md) and [UML](subsystems/agent-authoring/UML/) |
| Storage decision | [ADR-AKDB-0001](../adr/ADR-AKDB-0001-dual-backend.md) and [backend note](dual-backend.md) |
| Operations | [PostgreSQL](../operations/postgres.md), [MCP](../operations/MCP.md) |
