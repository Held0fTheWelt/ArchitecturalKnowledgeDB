from __future__ import annotations

import sqlite3
from typing import Any

from architectural_knowledge_db.models import (
    AdrInput,
    ContextPackRequest,
    ExploreRequest,
    OriginExplainRequest,
    RecallRequest,
    RememberRequest,
    UMLElementInput,
    UMLElementUpdate,
    UMLRelationshipInput,
)
from architectural_knowledge_db.services.authoring import AuthoringService
from architectural_knowledge_db.services.cognition import CognitionService
from architectural_knowledge_db.services.completeness import CompletenessService
from architectural_knowledge_db.services.consistency import ConsistencyService
from architectural_knowledge_db.services.context import ContextPackBuilder
from architectural_knowledge_db.services.git_scanner import GitScanner
from architectural_knowledge_db.services.guardrail import GuardrailService
from architectural_knowledge_db.services.import_export import ImportExportService
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.memory import MemoryService
from architectural_knowledge_db.services.origin import OriginService
from architectural_knowledge_db.services.reasoning import ReasoningService
from architectural_knowledge_db.services.recall_backend import LLMStoreEmbeddingClient, VectorBackend
from architectural_knowledge_db.services.reingest import ReingestService
from architectural_knowledge_db.services.review import ReviewService
from architectural_knowledge_db.services.roadmap import RoadmapService
from architectural_knowledge_db.services.survey import SurveyService
from architectural_knowledge_db.services.search import SearchService
from architectural_knowledge_db.services.staleness import StalenessService
from architectural_knowledge_db.services.uml import UMLService


# Bulk/list/search tools return many records at once. By default they strip large
# source/prose blobs so an agent can triage results without exhausting its token
# budget; pass detail="full" for complete records, or use the targeted get_* tools
# to read a single item in full.
_COMPACT_TOOLS = {
    "architectural_knowledge_db_search",
    "architectural_knowledge_db_get_context_pack",
    "architectural_knowledge_db_get_staleness_report",
    "architectural_knowledge_db_find_status_quo_drifts",
    "architectural_knowledge_db_run_drift_check",
    "akdb_list_adrs",
    "akdb_list_diagrams",
    "akdb_recall",
    "akdb_explore",
    "akdb_roadmap",
    "akdb_find_reuse",
    "akdb_tensions",
    "akdb_gaps",
    "akdb_survey",
    "akdb_spec_authoring_context",
    "akdb_brief",
    "akdb_recall_delta",
    "akdb_review",
}

_HEAVY_KEYS = frozenset(
    {
        "raw_source",
        "sections",
        "model",
        "body_passthrough",
        "header_passthrough",
        "context_md",
        "decision_md",
        "consequences_md",
        "evidence_json",
        "request_json",
        "response_json",
    }
)


def _strip_heavy(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _strip_heavy(item) for key, item in value.items() if key not in _HEAVY_KEYS}
    if isinstance(value, list):
        return [_strip_heavy(item) for item in value]
    return value


MCP_MANIFEST: dict[str, Any] = {
    "name": "architectural_knowledge_db",
    "version": "0.1.0",
    "description": "Multi-project architecture knowledge service with ADR, UML, rules, definitions, source areas, and linked Git provenance.",
    "tools": [
        {
            "name": "architectural_knowledge_db_search",
            "description": "Search project-local and imported shared architecture knowledge.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "query"],
                "properties": {
                    "project_id": {"type": "string"},
                    "query": {"type": "string"},
                    "include_types": {"type": "array", "items": {"type": "string"}},
                    "limit": {"type": "integer", "default": 20},
                },
            },
        },
        {
            "name": "architectural_knowledge_db_get_context_pack",
            "description": "Build an authority-aware context pack for a coding or modeling task.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "task"],
                "properties": {
                    "project_id": {"type": "string"},
                    "task": {"type": "string"},
                    "source_paths": {"type": "array", "items": {"type": "string"}},
                    "include_git_provenance": {"type": "boolean", "default": True},
                    "include_staleness": {"type": "boolean", "default": True},
                    "max_items": {"type": "integer", "default": 20},
                },
            },
        },
        {
            "name": "architectural_knowledge_db_explain_origin",
            "description": "Explain why a source path, ADR, rule, or UML element exists and how it evolved.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "target"],
                "properties": {
                    "project_id": {"type": "string"},
                    "target": {"type": "string"},
                    "target_type": {
                        "type": "string",
                        "enum": ["source_path", "knowledge_item", "uml_element", "rule", "adr"],
                    },
                },
            },
        },
        {
            "name": "architectural_knowledge_db_get_rules_for_path",
            "description": "Return active project and shared rules that apply to a source path.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "path"],
                "properties": {
                    "project_id": {"type": "string"},
                    "path": {"type": "string"},
                    "include_git_evidence": {"type": "boolean", "default": False},
                },
            },
        },
        {
            "name": "architectural_knowledge_db_get_git_provenance",
            "description": "Return Git file history and co-change evidence for a source path or knowledge item.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "target"],
                "properties": {
                    "project_id": {"type": "string"},
                    "target": {"type": "string"},
                    "limit_commits": {"type": "integer", "default": 10},
                },
            },
        },
        {
            "name": "architectural_knowledge_db_get_staleness_report",
            "description": "Return staleness and drift hints for ADRs, UML diagrams, rules, or source areas.",
            "input_schema": {
                "type": "object",
                "required": ["project_id"],
                "properties": {
                    "project_id": {"type": "string"},
                    "target": {"type": "string"},
                    "status_filter": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        {
            "name": "architectural_knowledge_db_find_status_quo_drifts",
            "description": "Find current-content drift hints without using Git timestamps as the signal. Use Git provenance afterwards to explain why or when a confirmed drift emerged.",
            "input_schema": {
                "type": "object",
                "required": ["project_id"],
                "properties": {
                    "project_id": {"type": "string"},
                    "target": {"type": "string"},
                    "limit": {"type": "integer", "default": 100},
                    "persist": {"type": "boolean", "default": False},
                },
            },
        },
        {
            "name": "architectural_knowledge_db_run_drift_check",
            "description": "Run the complete drift script: status-quo drift plus Git timeline provenance. Persists every report and returns an agent-sized prioritized summary.",
            "input_schema": {
                "type": "object",
                "required": ["project_id"],
                "properties": {
                    "project_id": {"type": "string"},
                    "target": {"type": "string"},
                    "limit": {"type": "integer", "default": 100},
                },
            },
        },
        {
            "name": "architectural_knowledge_db_validate_task_context",
            "description": "Check whether a proposed task appears to conflict with known ADRs, rules, or definitions.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "task"],
                "properties": {
                    "project_id": {"type": "string"},
                    "task": {"type": "string"},
                    "source_paths": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        {
            "name": "akdb_list_adrs",
            "description": "List ADRs for a project.",
            "input_schema": {
                "type": "object",
                "required": ["project_id"],
                "properties": {
                    "project_id": {"type": "string"},
                    "status": {"type": "string"},
                    "limit": {"type": "integer", "default": 100},
                },
            },
        },
        {
            "name": "akdb_get_adr",
            "description": "Read one ADR.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "adr_id"],
                "properties": {"project_id": {"type": "string"}, "adr_id": {"type": "string"}},
            },
        },
        {
            "name": "akdb_propose_adr",
            "description": "Create or update an ADR in the database.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "adr_id", "title"],
                "properties": {
                    "project_id": {"type": "string"},
                    "adr_id": {"type": "string"},
                    "title": {"type": "string"},
                    "context_md": {"type": "string"},
                    "decision_md": {"type": "string"},
                    "consequences_md": {"type": "string"},
                    "status": {"type": "string", "default": "Proposed"},
                },
            },
        },
        {
            "name": "akdb_update_adr_section",
            "description": "Update one typed ADR section in the database.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "adr_id", "role", "body_md"],
                "properties": {
                    "project_id": {"type": "string"},
                    "adr_id": {"type": "string"},
                    "role": {"type": "string"},
                    "body_md": {"type": "string"},
                },
            },
        },
        {
            "name": "akdb_set_adr_status",
            "description": "Set ADR status and supersedes list.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "adr_id", "status"],
                "properties": {
                    "project_id": {"type": "string"},
                    "adr_id": {"type": "string"},
                    "status": {"type": "string"},
                    "supersedes": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        {
            "name": "akdb_import_adrs",
            "description": "Import ADR markdown files into the database.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "folder"],
                "properties": {"project_id": {"type": "string"}, "folder": {"type": "string"}},
            },
        },
        {
            "name": "akdb_export_adrs",
            "description": "Export ADR markdown files from the database.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "folder"],
                "properties": {"project_id": {"type": "string"}, "folder": {"type": "string"}},
            },
        },
        {
            "name": "akdb_list_diagrams",
            "description": "List UML diagrams for a project.",
            "input_schema": {
                "type": "object",
                "required": ["project_id"],
                "properties": {
                    "project_id": {"type": "string"},
                    "kind": {"type": "string"},
                    "limit": {"type": "integer", "default": 100},
                },
            },
        },
        {
            "name": "akdb_import_uml",
            "description": "Import PlantUML diagrams into the database.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "folder"],
                "properties": {"project_id": {"type": "string"}, "folder": {"type": "string"}},
            },
        },
        {
            "name": "akdb_export_uml",
            "description": "Export PlantUML diagrams from the database.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "folder"],
                "properties": {"project_id": {"type": "string"}, "folder": {"type": "string"}},
            },
        },
        {
            "name": "akdb_get_diagram",
            "description": "Read one structured UML diagram with elements and relationships.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "diagram_id"],
                "properties": {"project_id": {"type": "string"}, "diagram_id": {"type": "string"}},
            },
        },
        {
            "name": "akdb_add_uml_element",
            "description": "Add a UML element to a diagram in the database.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "diagram_id", "element_type", "name"],
                "properties": {
                    "project_id": {"type": "string"},
                    "diagram_id": {"type": "string"},
                    "element_id": {"type": "string"},
                    "element_type": {"type": "string"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "metadata": {"type": "object"},
                },
            },
        },
        {
            "name": "akdb_update_uml_element",
            "description": "Update a UML element in the database.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "element_id", "changes"],
                "properties": {
                    "project_id": {"type": "string"},
                    "element_id": {"type": "string"},
                    "changes": {"type": "object"},
                },
            },
        },
        {
            "name": "akdb_add_uml_relationship",
            "description": "Add a relationship between UML elements.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "diagram_id", "source_element_id", "target_element_id"],
                "properties": {
                    "project_id": {"type": "string"},
                    "diagram_id": {"type": "string"},
                    "source_element_id": {"type": "string"},
                    "target_element_id": {"type": "string"},
                    "relationship_type": {"type": "string"},
                    "label": {"type": "string"},
                    "metadata": {"type": "object"},
                },
            },
        },
        {
            "name": "akdb_check_consistency",
            "description": "Run advisory consistency checks for a project.",
            "input_schema": {
                "type": "object",
                "required": ["project_id"],
                "properties": {
                    "project_id": {"type": "string"},
                    "scope": {"type": "string"},
                    "types": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        {
            "name": "akdb_impact_of",
            "description": "Return the link-graph blast radius for a target.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "target"],
                "properties": {
                    "project_id": {"type": "string"},
                    "target": {"type": "string"},
                    "depth": {"type": "integer", "default": 3},
                },
            },
        },
        {
            "name": "akdb_link",
            "description": "Create an explicit knowledge link.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "source", "target", "link_type"],
                "properties": {
                    "project_id": {"type": "string"},
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                    "link_type": {"type": "string"},
                    "evidence": {"type": "string"},
                },
            },
        },
        {
            "name": "akdb_get_links",
            "description": "Inspect inbound and outbound knowledge links.",
            "input_schema": {
                "type": "object",
                "required": ["project_id"],
                "properties": {
                    "project_id": {"type": "string"},
                    "target": {"type": "string"},
                    "direction": {"type": "string", "enum": ["inbound", "outbound", "both"]},
                },
            },
        },
        {
            "name": "akdb_recall",
            "description": "What do I know about X: resolve a wording to concept(s) and return the ranked neighbourhood with link types and grounding.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "query": {"type": "string"},
                    "hops": {"type": "integer"},
                    "detail": {"type": "string", "enum": ["compact", "full"]},
                    "semantic": {"type": "boolean"},
                    "spaces": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["query"],
            },
        },
        {
            "name": "akdb_explore",
            "description": "Follow a thread: traverse chosen link_types from a node, breadth-first up to hops.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "source": {"type": "string"},
                    "follow": {"type": "array", "items": {"type": "string"}},
                    "hops": {"type": "integer"},
                    "detail": {"type": "string", "enum": ["compact", "full"]},
                },
                "required": ["source"],
            },
        },
        {
            "name": "akdb_remember",
            "description": "Refill: attach a wording (alias) and/or a short note to an existing item; the wording becomes recall-able immediately.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "target": {"type": "string"},
                    "wording": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["target"],
            },
        },
        {
            "name": "akdb_propose_topic",
            "description": "Propose a curated topic; FTS-dedups against existing topics and refuses to create a near-duplicate.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "topic_id", "title"],
                "properties": {
                    "project_id": {"type": "string"},
                    "topic_id": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                },
            },
        },
        {
            "name": "akdb_create_mvp",
            "description": "Create an MVP with an auto-assigned monotonic seq; links it to a topic and suggests a predecessor when the topic already has MVPs.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "mvp_id", "title"],
                "properties": {
                    "project_id": {"type": "string"},
                    "mvp_id": {"type": "string"},
                    "title": {"type": "string"},
                    "intent_md": {"type": "string"},
                    "topic_uid": {"type": "string"},
                },
            },
        },
        {
            "name": "akdb_create_spec",
            "description": "Create a spec (plugin|function|rule archetype) attached to an MVP, optionally inheriting a topic.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "spec_id", "title", "archetype", "mvp_uid"],
                "properties": {
                    "project_id": {"type": "string"},
                    "spec_id": {"type": "string"},
                    "title": {"type": "string"},
                    "archetype": {"type": "string", "enum": ["plugin", "function", "rule"]},
                    "mvp_uid": {"type": "string"},
                    "topic_uid": {"type": "string"},
                },
            },
        },
        {
            "name": "akdb_open_question",
            "description": "Open a first-class question, optionally about a topic.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "question_id", "title"],
                "properties": {
                    "project_id": {"type": "string"},
                    "question_id": {"type": "string"},
                    "title": {"type": "string"},
                    "topic_uid": {"type": "string"},
                },
            },
        },
        {
            "name": "akdb_resolve_question",
            "description": "Mark a question answered and link it to the resolving item.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "question_uid", "by_ref"],
                "properties": {
                    "project_id": {"type": "string"},
                    "question_uid": {"type": "string"},
                    "by_ref": {"type": "string"},
                },
            },
        },
        {
            "name": "akdb_map_element_to_file",
            "description": "Map a model element to a real source file (Implementation File Map edge).",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "element_uid", "path"],
                "properties": {
                    "project_id": {"type": "string"},
                    "element_uid": {"type": "string"},
                    "path": {"type": "string"},
                    "symbol": {"type": "string"},
                },
            },
        },
        {
            "name": "akdb_roadmap",
            "description": "Return the seq-ordered MVP changelog with topics, specs, and predecessor edges.",
            "input_schema": {
                "type": "object",
                "required": ["project_id"],
                "properties": {"project_id": {"type": "string"}},
            },
        },
        {
            "name": "akdb_spec_validate",
            "description": "Validate a spec against its archetype completeness contract (required diagrams + file-map). Returns {blocking, warnings, ok} and writes findings.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "spec_uid"],
                "properties": {"project_id": {"type": "string"}, "spec_uid": {"type": "string"}},
            },
        },
        {
            "name": "akdb_set_spec_status",
            "description": "Set a spec's lifecycle. draft->ready is gated by spec_validate and refused when incomplete.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "spec_uid", "status"],
                "properties": {
                    "project_id": {"type": "string"},
                    "spec_uid": {"type": "string"},
                    "status": {"type": "string", "enum": ["draft", "ready", "implemented", "superseded"]},
                },
            },
        },
        {
            "name": "akdb_scaffold_spec",
            "description": "Scaffold a new spec for an archetype: required diagram stubs, a file-map stub, and reusable prior work when a topic is given.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "archetype"],
                "properties": {
                    "project_id": {"type": "string"},
                    "archetype": {"type": "string", "enum": ["plugin", "function", "rule"]},
                    "topic_uid": {"type": "string"},
                },
            },
        },
        {
            "name": "akdb_find_reuse",
            "description": "Find similar prior specs/elements to clone or extend (FTS now; semantic later).",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "query"],
                "properties": {
                    "project_id": {"type": "string"},
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                },
            },
        },
        {
            "name": "akdb_spec_to_plan",
            "description": "Turn a ready spec's file-map into an ordered TDD task list with checkpoints; refuses a non-ready spec.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "spec_uid"],
                "properties": {"project_id": {"type": "string"}, "spec_uid": {"type": "string"}},
            },
        },
        {
            "name": "akdb_connect",
            "description": "Find and explain the shortest knowledge-graph path between two items.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "a_uid", "b_uid"],
                "properties": {
                    "project_id": {"type": "string"},
                    "a_uid": {"type": "string"},
                    "b_uid": {"type": "string"},
                    "max_hops": {"type": "integer", "default": 4},
                },
            },
        },
        {
            "name": "akdb_tensions",
            "description": "Detect conflicts (superseded-still-referenced, rule-forbidden hits), optionally scoped to a topic.",
            "input_schema": {
                "type": "object",
                "required": ["project_id"],
                "properties": {"project_id": {"type": "string"}, "topic_uid": {"type": "string"}},
            },
        },
        {
            "name": "akdb_gaps",
            "description": "Detect blind-spots (topic/mvp without spec, incomplete spec, stale UML), optionally scoped to a topic or archetype.",
            "input_schema": {
                "type": "object",
                "required": ["project_id"],
                "properties": {
                    "project_id": {"type": "string"},
                    "topic_uid": {"type": "string"},
                    "archetype": {"type": "string"},
                },
            },
        },
        {
            "name": "akdb_survey",
            "description": "Zoom-out map of the environment: topics, changelog tail, specs-by-status, and a health summary.",
            "input_schema": {
                "type": "object",
                "required": ["project_id"],
                "properties": {"project_id": {"type": "string"}},
            },
        },
        {
            "name": "akdb_spec_authoring_context",
            "description": "Topic-scoped authoring pack: timeline, related knowledge, archetype contract, source areas, reusable elements.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "topic_uid"],
                "properties": {
                    "project_id": {"type": "string"},
                    "topic_uid": {"type": "string"},
                    "archetype": {"type": "string"},
                },
            },
        },
        {
            "name": "akdb_brief",
            "description": "Narrative brief for a topic: what it is, key decisions, MVP lineage, open questions, blind spots.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "topic_uid"],
                "properties": {"project_id": {"type": "string"}, "topic_uid": {"type": "string"}},
            },
        },
        {
            "name": "akdb_pin",
            "description": "Pin (or unpin) an item so it stays at the top of recall regardless of decay.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "item_uid"],
                "properties": {
                    "project_id": {"type": "string"},
                    "item_uid": {"type": "string"},
                    "pinned": {"type": "boolean", "default": True},
                },
            },
        },
        {
            "name": "akdb_recall_delta",
            "description": "Items changed since an ISO timestamp or an mvp_id, newest-first (continuity / catch-up).",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "since"],
                "properties": {"project_id": {"type": "string"}, "since": {"type": "string"}},
            },
        },
        {
            "name": "akdb_working_set",
            "description": "Focus set: add/list/clear the items you are actively working with under a label.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "action"],
                "properties": {
                    "project_id": {"type": "string"},
                    "action": {"type": "string", "enum": ["add", "list", "clear"]},
                    "ref": {"type": "string"},
                    "label": {"type": "string", "default": "default"},
                },
            },
        },
        {
            "name": "akdb_check_change",
            "description": "Guardrail-lint a proposed change {path, summary} against active rules' applies_to/forbidden_changes.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "path"],
                "properties": {
                    "project_id": {"type": "string"},
                    "path": {"type": "string"},
                    "summary": {"type": "string"},
                },
            },
        },
        {
            "name": "akdb_review",
            "description": "Composite self-review of a target: completeness (if spec) + tensions + gaps + staleness → a soundness verdict.",
            "input_schema": {
                "type": "object",
                "required": ["project_id", "target_uid"],
                "properties": {"project_id": {"type": "string"}, "target_uid": {"type": "string"}},
            },
        },
        {
            "name": "akdb_embed_project",
            "description": "Build semantic embeddings for a project's items (needs a configured vector backend). No-ops with backend='none' when AKDB_RECALL_BACKEND/AKDB_EMBED_URL are unset; recall stays FTS.",
            "input_schema": {
                "type": "object",
                "required": ["project_id"],
                "properties": {"project_id": {"type": "string"}},
            },
        },
        {
            "name": "akdb_scan_repo",
            "description": "Trigger read-only Git metadata scan.",
            "input_schema": {
                "type": "object",
                "required": ["project_id"],
                "properties": {
                    "project_id": {"type": "string"},
                    "repository_id": {"type": "string"},
                    "max_commits": {"type": "integer", "default": 500},
                },
            },
        },
        {
            "name": "akdb_reingest_project",
            "description": "Rebuild a project's knowledge by re-importing ADRs, architecture documents, and UML from its source folders, then rescanning Git provenance. Use to refresh the DB state after sources change. Folders default to the standard repo layout under source_root (AKDB_SOURCE_ROOT); missing folders are skipped. Writes to the database (run against a DB the agent owns, or with the :8787 service stopped).",
            "input_schema": {
                "type": "object",
                "required": ["project_id"],
                "properties": {
                    "project_id": {"type": "string"},
                    "source_root": {"type": "string", "description": "Base dir; defaults to AKDB_SOURCE_ROOT."},
                    "adr_folder": {"type": "string", "description": "Override ADR folder (default <root>/docs/ADR)."},
                    "document_folder": {"type": "string", "description": "Override docs folder (default <root>/docs/architecture)."},
                    "uml_folder": {"type": "string", "description": "Override UML folder (default <root>/UML)."},
                    "scan_git": {"type": "boolean", "default": True},
                    "max_commits": {"type": "integer", "default": 400},
                },
            },
        },
    ],
}


# Advertise the detail switch on every bulk/list tool.
for _tool in MCP_MANIFEST["tools"]:
    if _tool["name"] in _COMPACT_TOOLS:
        _tool["input_schema"]["properties"]["detail"] = {
            "type": "string",
            "enum": ["compact", "full"],
            "default": "compact",
            "description": "compact (default) strips large source/prose blobs; full returns complete records.",
        }


def _backend_from_env(conn: sqlite3.Connection):
    import os

    mode = os.environ.get("AKDB_RECALL_BACKEND", "").lower()
    url = os.environ.get("AKDB_EMBED_URL")
    if mode in {"vector", "hybrid"} and url:
        model = os.environ.get("AKDB_EMBED_MODEL", "default")
        return VectorBackend(conn, LLMStoreEmbeddingClient(url, model), model=model)
    return None


class McpDispatcher:
    def __init__(self, conn: sqlite3.Connection, backend=None):
        self.conn = conn
        self.backend = backend if backend is not None else _backend_from_env(conn)

    def dispatch(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        detail = "compact"
        if isinstance(arguments, dict):
            detail = str(arguments.pop("detail", "compact") or "compact").lower()
        result = self._dispatch_raw(tool_name, arguments)
        if tool_name in _COMPACT_TOOLS and detail != "full":
            return _strip_heavy(result)
        return result

    def _dispatch_raw(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        if tool_name == "architectural_knowledge_db_search":
            return SearchService(self.conn).search(
                arguments["project_id"],
                arguments["query"],
                include_types=arguments.get("include_types"),
                limit=arguments.get("limit", 20),
            )
        if tool_name == "architectural_knowledge_db_get_context_pack":
            project_id = arguments.pop("project_id")
            return ContextPackBuilder(self.conn).build(project_id, ContextPackRequest(**arguments))
        if tool_name == "architectural_knowledge_db_explain_origin":
            project_id = arguments.pop("project_id")
            return OriginService(self.conn).explain(project_id, OriginExplainRequest(**arguments))
        if tool_name == "architectural_knowledge_db_get_rules_for_path":
            return KnowledgeService(self.conn).matching_rules_for_path(arguments["project_id"], arguments["path"])
        if tool_name == "architectural_knowledge_db_get_git_provenance":
            return OriginService(self.conn).git_provenance(
                arguments["project_id"],
                arguments["target"],
                limit_commits=arguments.get("limit_commits", 10),
            )
        if tool_name == "architectural_knowledge_db_get_staleness_report":
            return StalenessService(self.conn).list_reports(
                arguments["project_id"],
                target=arguments.get("target"),
                status_filter=arguments.get("status_filter"),
            )
        if tool_name == "architectural_knowledge_db_find_status_quo_drifts":
            service = StalenessService(self.conn)
            if arguments.get("persist"):
                return service.compute_status_quo(
                    arguments["project_id"],
                    target=arguments.get("target"),
                    limit=arguments.get("limit", 100),
                )
            return service.find_status_quo_drifts(
                arguments["project_id"],
                target=arguments.get("target"),
                limit=arguments.get("limit", 100),
            )
        if tool_name == "architectural_knowledge_db_run_drift_check":
            return StalenessService(self.conn).run_drift_check(
                arguments["project_id"],
                target=arguments.get("target"),
                limit=arguments.get("limit", 100),
            )
        if tool_name == "architectural_knowledge_db_validate_task_context":
            return ContextPackBuilder(self.conn).validate_task_context(
                arguments["project_id"],
                arguments["task"],
                arguments.get("source_paths") or [],
            )
        if tool_name == "akdb_list_adrs":
            return KnowledgeService(self.conn).list_adrs(
                arguments["project_id"],
                status=arguments.get("status"),
                limit=arguments.get("limit", 100),
            )
        if tool_name == "akdb_get_adr":
            return KnowledgeService(self.conn).get_adr(arguments["project_id"], arguments["adr_id"])
        if tool_name == "akdb_propose_adr":
            project_id = arguments.pop("project_id")
            return _adr_edit_response(
                self.conn,
                project_id,
                KnowledgeService(self.conn).upsert_adr(project_id, AdrInput(**arguments)),
            )
        if tool_name == "akdb_update_adr_section":
            project_id = arguments["project_id"]
            adr = KnowledgeService(self.conn).get_adr(project_id, arguments["adr_id"])
            role = arguments["role"]
            payload = AdrInput(
                adr_id=adr["adr_id"],
                title=adr["title"],
                status=adr["status"],
                context_md=arguments["body_md"] if role == "context" else adr.get("context_md"),
                decision_md=arguments["body_md"] if role == "decision" else adr.get("decision_md"),
                consequences_md=arguments["body_md"] if role == "consequences" else adr.get("consequences_md"),
                supersedes=adr.get("supersedes", []),
                superseded_by=adr.get("superseded_by", []),
                summary=adr.get("summary"),
                source_uri=adr.get("source_uri"),
                metadata=adr.get("metadata", {}),
                raw_source=adr.get("raw_source"),
                sections=adr.get("sections", []),
            )
            if role == "status":
                payload.status = arguments["body_md"].strip()
            return _adr_edit_response(self.conn, project_id, KnowledgeService(self.conn).upsert_adr(project_id, payload))
        if tool_name == "akdb_set_adr_status":
            project_id = arguments["project_id"]
            adr = KnowledgeService(self.conn).get_adr(project_id, arguments["adr_id"])
            payload = AdrInput(
                adr_id=adr["adr_id"],
                title=adr["title"],
                status=arguments["status"],
                context_md=adr.get("context_md"),
                decision_md=adr.get("decision_md"),
                consequences_md=adr.get("consequences_md"),
                supersedes=arguments.get("supersedes") or adr.get("supersedes", []),
                superseded_by=adr.get("superseded_by", []),
                summary=adr.get("summary"),
                source_uri=adr.get("source_uri"),
                metadata=adr.get("metadata", {}),
                raw_source=adr.get("raw_source"),
                sections=adr.get("sections", []),
            )
            return _adr_edit_response(self.conn, project_id, KnowledgeService(self.conn).upsert_adr(project_id, payload))
        if tool_name == "akdb_import_adrs":
            return ImportExportService(self.conn).import_adrs(arguments["project_id"], arguments["folder"])
        if tool_name == "akdb_export_adrs":
            return ImportExportService(self.conn).export_adrs(arguments["project_id"], arguments["folder"])
        if tool_name == "akdb_list_diagrams":
            return UMLService(self.conn).list_diagrams(
                arguments["project_id"],
                kind=arguments.get("kind"),
                limit=arguments.get("limit", 100),
            )
        if tool_name == "akdb_import_uml":
            return UMLService(self.conn).import_diagrams(arguments["project_id"], arguments["folder"])
        if tool_name == "akdb_export_uml":
            return UMLService(self.conn).export_diagrams(arguments["project_id"], arguments["folder"])
        if tool_name == "akdb_get_diagram":
            return UMLService(self.conn).get_diagram(arguments["project_id"], arguments["diagram_id"])
        if tool_name == "akdb_add_uml_element":
            project_id = arguments.pop("project_id")
            return UMLService(self.conn).add_element(project_id, UMLElementInput(**arguments))
        if tool_name == "akdb_update_uml_element":
            project_id = arguments["project_id"]
            return UMLService(self.conn).update_element(
                project_id,
                arguments["element_id"],
                UMLElementUpdate(**arguments.get("changes", {})),
            )
        if tool_name == "akdb_add_uml_relationship":
            project_id = arguments.pop("project_id")
            return UMLService(self.conn).add_relationship(project_id, UMLRelationshipInput(**arguments))
        if tool_name == "akdb_check_consistency":
            return ConsistencyService(self.conn).check(
                arguments["project_id"],
                scope=arguments.get("scope"),
                types=arguments.get("types"),
            )
        if tool_name == "akdb_impact_of":
            return ConsistencyService(self.conn).impact_of(
                arguments["project_id"],
                arguments["target"],
                depth=arguments.get("depth", 3),
            )
        if tool_name == "akdb_link":
            return ConsistencyService(self.conn).link(
                arguments["project_id"],
                arguments["source"],
                arguments["target"],
                arguments["link_type"],
                evidence=arguments.get("evidence"),
            )
        if tool_name == "akdb_get_links":
            return ConsistencyService(self.conn).get_links(
                arguments["project_id"],
                target=arguments.get("target"),
                direction=arguments.get("direction", "both"),
            )
        if tool_name == "akdb_recall":
            return CognitionService(self.conn, backend=self.backend).recall(
                arguments["project_id"], RecallRequest(**_without_project(arguments))
            )
        if tool_name == "akdb_embed_project":
            if self.backend is None:
                return {"embedded": 0, "backend": "none"}
            result = self.backend.embed_project(arguments["project_id"])
            return {"embedded": result["embedded"], "backend": "vector"}
        if tool_name == "akdb_explore":
            return CognitionService(self.conn).explore(
                arguments["project_id"], ExploreRequest(**_without_project(arguments))
            )
        if tool_name == "akdb_remember":
            return CognitionService(self.conn).remember(
                arguments["project_id"], RememberRequest(**_without_project(arguments))
            )
        if tool_name == "akdb_propose_topic":
            return AuthoringService(self.conn).propose_topic(
                arguments["project_id"], arguments["topic_id"], arguments["title"],
                summary=arguments.get("summary"),
            )
        if tool_name == "akdb_create_mvp":
            return AuthoringService(self.conn).create_mvp(
                arguments["project_id"], arguments["mvp_id"], arguments["title"],
                intent_md=arguments.get("intent_md"), topic_uid=arguments.get("topic_uid"),
            )
        if tool_name == "akdb_create_spec":
            return AuthoringService(self.conn).create_spec(
                arguments["project_id"], arguments["spec_id"], arguments["title"],
                arguments["archetype"], arguments["mvp_uid"], topic_uid=arguments.get("topic_uid"),
            )
        if tool_name == "akdb_open_question":
            return AuthoringService(self.conn).open_question(
                arguments["project_id"], arguments["question_id"], arguments["title"],
                topic_uid=arguments.get("topic_uid"),
            )
        if tool_name == "akdb_resolve_question":
            return AuthoringService(self.conn).resolve_question(
                arguments["project_id"], arguments["question_uid"], arguments["by_ref"],
            )
        if tool_name == "akdb_map_element_to_file":
            return AuthoringService(self.conn).map_element_to_file(
                arguments["project_id"], arguments["element_uid"], arguments["path"],
                symbol=arguments.get("symbol"),
            )
        if tool_name == "akdb_roadmap":
            return RoadmapService(self.conn).roadmap(arguments["project_id"])
        if tool_name == "akdb_spec_validate":
            return CompletenessService(self.conn).spec_validate(arguments["project_id"], arguments["spec_uid"])
        if tool_name == "akdb_set_spec_status":
            return AuthoringService(self.conn).set_spec_status(
                arguments["project_id"], arguments["spec_uid"], arguments["status"]
            )
        if tool_name == "akdb_scaffold_spec":
            return AuthoringService(self.conn).scaffold_spec(
                arguments["project_id"], arguments["archetype"], topic_uid=arguments.get("topic_uid")
            )
        if tool_name == "akdb_find_reuse":
            return AuthoringService(self.conn).find_reuse(
                arguments["project_id"], arguments["query"], limit=arguments.get("limit", 10)
            )
        if tool_name == "akdb_spec_to_plan":
            return AuthoringService(self.conn).spec_to_plan(arguments["project_id"], arguments["spec_uid"])
        if tool_name == "akdb_connect":
            return ReasoningService(self.conn).connect(
                arguments["project_id"], arguments["a_uid"], arguments["b_uid"],
                max_hops=arguments.get("max_hops", 4),
            )
        if tool_name == "akdb_tensions":
            return ReasoningService(self.conn).tensions(
                arguments["project_id"], topic_uid=arguments.get("topic_uid")
            )
        if tool_name == "akdb_gaps":
            return ReasoningService(self.conn).gaps(
                arguments["project_id"], topic_uid=arguments.get("topic_uid"),
                archetype=arguments.get("archetype"),
            )
        if tool_name == "akdb_survey":
            return SurveyService(self.conn).survey(arguments["project_id"])
        if tool_name == "akdb_spec_authoring_context":
            return SurveyService(self.conn).spec_authoring_context(
                arguments["project_id"], arguments["topic_uid"], archetype=arguments.get("archetype")
            )
        if tool_name == "akdb_brief":
            return SurveyService(self.conn).brief(arguments["project_id"], arguments["topic_uid"])
        if tool_name == "akdb_pin":
            memory = MemoryService(self.conn)
            memory.pin(arguments["project_id"], arguments["item_uid"], pinned=arguments.get("pinned", True))
            return {"item_uid": arguments["item_uid"], **memory.state(arguments["item_uid"])}
        if tool_name == "akdb_recall_delta":
            return CognitionService(self.conn).recall_delta(arguments["project_id"], arguments["since"])
        if tool_name == "akdb_working_set":
            return CognitionService(self.conn).working_set(
                arguments["project_id"], arguments["action"],
                ref=arguments.get("ref"), label=arguments.get("label", "default"),
            )
        if tool_name == "akdb_check_change":
            return GuardrailService(self.conn).check_change(
                arguments["project_id"],
                {"path": arguments.get("path", ""), "summary": arguments.get("summary", "")},
            )
        if tool_name == "akdb_review":
            return ReviewService(self.conn).review(arguments["project_id"], arguments["target_uid"])
        if tool_name == "akdb_scan_repo":
            scanner = GitScanner(self.conn)
            if arguments.get("repository_id"):
                return scanner.scan_repository(
                    arguments["project_id"],
                    arguments["repository_id"],
                    max_commits=arguments.get("max_commits", 500),
                )
            return scanner.scan_project(arguments["project_id"], max_commits=arguments.get("max_commits", 500))
        if tool_name == "akdb_reingest_project":
            return ReingestService(self.conn).reingest_project(
                arguments["project_id"],
                source_root=arguments.get("source_root"),
                adr_folder=arguments.get("adr_folder"),
                document_folder=arguments.get("document_folder"),
                uml_folder=arguments.get("uml_folder"),
                scan_git=arguments.get("scan_git", True),
                max_commits=arguments.get("max_commits", 400),
            )
        raise ValueError(f"Unknown MCP tool: {tool_name}")


def _without_project(arguments: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in arguments.items() if k != "project_id"}


def _adr_edit_response(conn: sqlite3.Connection, project_id: str, adr: dict[str, Any]) -> dict[str, Any]:
    return {
        "adr": adr,
        "impact": ConsistencyService(conn).impact_of(project_id, adr["item_uid"]),
    }
