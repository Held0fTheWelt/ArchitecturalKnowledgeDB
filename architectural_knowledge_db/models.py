from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


AuthorityLevel = Literal[
    "hard_guardrail",
    "accepted_adr",
    "active_rule",
    "canonical_definition",
    "current_uml_model",
    "source_area_evidence",
    "git_provenance_evidence",
    "historical_context",
    "superseded_decision",
    "deprecated_compatibility",
    "project_note",
    "evidence",
]


class ProjectUpsert(BaseModel):
    project_id: str
    display_name: str
    description: str | None = None
    imports: list[str] = Field(default_factory=list)


class Project(ProjectUpsert):
    status: str = "active"


class KnowledgeSpace(BaseModel):
    space_id: str
    project_id: str | None = None
    space_type: Literal["project", "shared", "archive"] = "project"
    display_name: str
    description: str | None = None


class RepositoryRegistration(BaseModel):
    repository_id: str
    local_path: str
    remote_url_sanitized: str | None = None
    default_branch: str | None = None
    scan_policy: Literal["manual", "startup", "scheduled"] = "manual"
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)


class SearchRequest(BaseModel):
    query: str
    include_types: list[str] | None = None
    include_shared: bool = True
    limit: int = 20


class ContextPackRequest(BaseModel):
    task: str
    source_paths: list[str] = Field(default_factory=list)
    include: list[str] | None = None
    include_git_provenance: bool = True
    include_staleness: bool = True
    max_items: int = 20


class OriginExplainRequest(BaseModel):
    target: str
    target_type: Literal["source_path", "knowledge_item", "uml_element", "rule", "adr"] = "source_path"
    include: list[str] | None = None


class GitProvenanceRequest(BaseModel):
    target: str
    limit_commits: int = 10


class AdrInput(BaseModel):
    adr_id: str
    title: str
    status: str = "proposed"
    context_md: str | None = None
    decision_md: str | None = None
    consequences_md: str | None = None
    supersedes: list[str] = Field(default_factory=list)
    superseded_by: list[str] = Field(default_factory=list)
    authority_level: AuthorityLevel = "accepted_adr"
    summary: str | None = None
    source_uri: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    raw_source: str | None = None
    sections: list[dict[str, Any]] = Field(default_factory=list)


class SadDocumentInput(BaseModel):
    document_id: str
    title: str
    source_key: str = "architecture.md"
    preamble_md: str | None = None
    frontmatter: dict[str, Any] = Field(default_factory=dict)
    status: str = "current"
    summary: str | None = None


class SadSectionInput(BaseModel):
    document_id: str
    section_id: str
    title: str
    order: int
    body_md: str = ""
    level: int = Field(default=2, ge=2, le=6)
    role: str | None = None


class SadDecisionInput(BaseModel):
    document_id: str
    decision_id: str
    title: str
    order: int
    status: str = "proposed"
    body_md: str = ""
    summary: str | None = None


class RuleInput(BaseModel):
    rule_id: str
    title: str | None = None
    severity: str = "normal"
    rule_text: str
    applies_to: list[str] = Field(default_factory=list)
    forbidden_changes: list[str] = Field(default_factory=list)
    authority_level: AuthorityLevel = "active_rule"
    summary: str | None = None
    source_uri: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DefinitionInput(BaseModel):
    term: str
    canonical_meaning: str
    anti_meanings: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    authority_level: AuthorityLevel = "canonical_definition"
    summary: str | None = None
    source_uri: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceAreaInput(BaseModel):
    source_area_id: str
    title: str
    path_patterns: list[str] = Field(default_factory=list)
    description: str | None = None
    repository_id: str | None = None
    authority_level: AuthorityLevel = "source_area_evidence"
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeLinkInput(BaseModel):
    source_item_uid: str
    target_ref: str
    link_type: str
    authority_level: AuthorityLevel = "evidence"
    confidence: str = "explicit"
    evidence: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UMLDiagramInput(BaseModel):
    diagram_id: str
    title: str
    notation: Literal["plantuml", "mermaid", "drawio", "internal"] = "plantuml"
    diagram_kind: str = "unknown"
    source_uri: str | None = None
    model: dict[str, Any] = Field(default_factory=dict)
    raw_source: str | None = None


class UMLDiagramUpdate(BaseModel):
    title: str | None = None
    notation: Literal["plantuml", "mermaid", "drawio", "internal"] | None = None
    diagram_kind: str | None = None
    source_key: str | None = None
    sad_document_id: str | None = None
    raw_source: str | None = None


class UMLElementInput(BaseModel):
    diagram_id: str
    element_id: str | None = None
    element_type: str
    name: str
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UMLElementUpdate(BaseModel):
    element_type: str | None = None
    name: str | None = None
    description: str | None = None
    metadata: dict[str, Any] | None = None


class UMLRelationshipInput(BaseModel):
    diagram_id: str
    source_element_id: str
    target_element_id: str
    relationship_type: str = "association"
    label: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UMLRelationshipUpdate(BaseModel):
    relationship_type: str | None = None
    label: str | None = None
    metadata: dict[str, Any] | None = None


class ConsistencyCheckRequest(BaseModel):
    scope: str | None = None
    types: list[str] | None = None


class ImpactRequest(BaseModel):
    target: str
    depth: int = 3


class LinkQueryRequest(BaseModel):
    target: str | None = None
    direction: Literal["inbound", "outbound", "both"] = "both"


class TopicInput(BaseModel):
    topic_id: str
    title: str
    lifecycle: Literal["active", "dormant", "closed"] = "active"
    summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MvpInput(BaseModel):
    mvp_id: str
    title: str
    seq: int
    lifecycle: Literal["planned", "in_progress", "shipped", "superseded"] = "planned"
    intent_md: str | None = None
    shipped_at: str | None = None
    summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SpecInput(BaseModel):
    spec_id: str
    title: str
    archetype: Literal["plugin", "function", "rule"]
    lifecycle: Literal["draft", "ready", "implemented", "superseded"] = "draft"
    mvp_uid: str | None = None
    sections: list[dict[str, Any]] = Field(default_factory=list)
    summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChangeItemInput(BaseModel):
    spec_uid: str = ""
    op: Literal["add", "modify", "supersede", "remove"]
    target_kind: Literal[
        "sad_decision",
        "sad_section",
        "adr",
        "uml_element",
        "uml_relationship",
        "rule",
        "definition",
    ]
    target_ref: str
    state: Literal["proposed", "in_progress", "done"] = "proposed"
    note: str | None = None


class QuestionInput(BaseModel):
    question_id: str
    title: str
    status: Literal["open", "answered", "wontfix"] = "open"
    summary: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RecallRequest(BaseModel):
    query: str
    hops: int = 1
    detail: Literal["compact", "full"] = "compact"
    include_shared: bool = True
    limit: int = 20
    # RecallBackend seam (FTS-only in MVP-1; vector + cross-space are MVP-6)
    semantic: bool = False
    spaces: list[str] | None = None


class ExploreRequest(BaseModel):
    source: str  # item_uid to start from
    follow: list[str] = Field(default_factory=list)  # link_types; empty = all
    hops: int = 1
    detail: Literal["compact", "full"] = "compact"


class RememberRequest(BaseModel):
    target: str  # item_uid the wording/note attaches to
    wording: str | None = None
    note: str | None = None


def model_dump(model: BaseModel) -> dict[str, Any]:
    return model.model_dump()
