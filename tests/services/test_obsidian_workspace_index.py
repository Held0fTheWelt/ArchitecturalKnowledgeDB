from __future__ import annotations

from architectural_knowledge_db.models import AdrInput, ProjectUpsert, SpecInput
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.projects import ProjectService


def _seed_two_projects_with_adrs(conn) -> tuple[str, str]:
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="ttd", display_name="TTD"))
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="akdb", display_name="AKDB"))
    ks = KnowledgeService(conn)
    ks.upsert_adr(
        "ttd",
        AdrInput(
            adr_id="ADR-T1",
            title="ADR-T1 Proposed in TTD",
            status="proposed",
            metadata={
                "repo_source_key": "docs/ADR/ADR-T1.md",
                "repository_id": "Git",
                "system": "Governance",
                "body_text": "# ADR-T1\n\nProposed.\n",
                "body_encoding": "utf-8",
            },
        ),
    )
    ks.upsert_adr(
        "akdb",
        AdrInput(
            adr_id="ADR-A1",
            title="ADR-A1 Accepted in AKDB",
            status="accepted",
            metadata={
                "repo_source_key": "docs/ADR/ADR-A1.md",
                "repository_id": "ArchitecturalKnowledgeDB",
                "system": "AKDB",
                "body_text": "# ADR-A1\n\nAccepted.\n",
                "body_encoding": "utf-8",
            },
        ),
    )
    ks._upsert_item(
        project_id="ttd",
        space_id=None,
        item_type="spec",
        local_id="S-T1",
        title="Spec T1",
        status="ready",
        authority_level="draft",
        summary="ready spec",
        source_uri="akdb://ttd/spec/S-T1",
        metadata={
            "repo_source_key": "docs/architecture/specs/S-T1.md",
            "repository_id": "Git",
            "system": "Governance",
            "body_text": "# Spec T1\n",
            "body_encoding": "utf-8",
            "lifecycle": "ready",
        },
    )
    return "ttd", "akdb"


def test_workspace_index_entscheidungen_groups_by_status_with_dataview(conn):
    ttd, akdb = _seed_two_projects_with_adrs(conn)
    from architectural_knowledge_db.services.obsidian_export import (
        build_global_registry,
        build_workspace_index,
    )
    from architectural_knowledge_db.services.workspace import WorkspaceService

    registry = build_global_registry(conn, [ttd, akdb])
    files = build_workspace_index(
        conn,
        [ttd, akdb],
        global_registry=registry,
        workspace=WorkspaceService(conn),
        namespaces={"ttd": "TTD", "akdb": "AKDB"},
    )

    assert "_index/START-HERE.md" in files
    assert "_index/MOC — Entscheidungen.md" in files
    assert "_index/MOC — Specs.md" in files
    assert "_index/MOC — Systeme.md" in files

    ents = files["_index/MOC — Entscheidungen.md"].decode()
    assert "## proposed" in ents.lower() or "### proposed" in ents.lower()
    assert "## accepted" in ents.lower() or "### accepted" in ents.lower()
    assert "[[ADR-T1 Proposed in TTD]]" in ents or "ADR-T1" in ents
    assert "[[ADR-A1 Accepted in AKDB]]" in ents or "ADR-A1" in ents
    assert "```dataview" in ents

    specs = files["_index/MOC — Specs.md"].decode()
    assert "```dataview" in specs

    systeme = files["_index/MOC — Systeme.md"].decode()
    assert "[[MOC —" in systeme or "TTD" in systeme
    assert "```dataview" in systeme
