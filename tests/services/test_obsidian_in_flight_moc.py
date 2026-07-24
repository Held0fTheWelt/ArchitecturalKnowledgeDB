from __future__ import annotations

from architectural_knowledge_db.models import ProjectUpsert
from architectural_knowledge_db.services.authoring import AuthoringService
from architectural_knowledge_db.services.change_sets import ChangeSetService
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.projects import ProjectService


def _seed_project(conn, project_id: str = "ttd") -> str:
    ProjectService(conn).upsert_project(ProjectUpsert(project_id=project_id, display_name=project_id.upper()))
    return project_id


def test_in_arbeit_moc_lists_open_change_item_with_link(conn):
    pid = _seed_project(conn)
    authoring = AuthoringService(conn)
    mvp = authoring.create_mvp(pid, "M1", "m")["mvp"]["item_uid"]
    spec = authoring.create_spec(pid, "S-OPEN", "Open work", "plugin", mvp)
    # Put the spec in ready lifecycle for the ready section.
    authoring.set_spec_status(pid, spec["item_uid"], "ready")
    ChangeSetService(conn).ingest_impact(
        pid, spec["item_uid"], "## Architektur-Impact\n- add ADR-OPEN — in flight\n"
    )
    # Also seed a note the change item can link toward (ADR title-ish).
    KnowledgeService(conn).upsert_adr(
        pid,
        __import__("architectural_knowledge_db.models", fromlist=["AdrInput"]).AdrInput(
            adr_id="ADR-OPEN",
            title="ADR-OPEN in flight",
            status="proposed",
            metadata={
                "repo_source_key": "docs/ADR/ADR-OPEN.md",
                "repository_id": "Git",
                "system": "Governance",
                "body_text": "# ADR-OPEN\n",
                "body_encoding": "utf-8",
            },
        ),
    )

    from architectural_knowledge_db.services.obsidian_export import (
        build_global_registry,
        build_workspace_index,
    )

    registry = build_global_registry(conn, [pid])
    files = build_workspace_index(conn, [pid], global_registry=registry, namespaces={pid: "TTD"})
    assert "_index/MOC — In Arbeit.md" in files
    body = files["_index/MOC — In Arbeit.md"].decode()
    assert "S-OPEN" in body or "Open work" in body
    assert "[[" in body
    assert "nothing in flight" not in body.lower()


def test_in_arbeit_moc_degrades_when_nothing_open(conn):
    pid = _seed_project(conn, "empty")
    from architectural_knowledge_db.services.obsidian_export import (
        build_global_registry,
        build_workspace_index,
    )

    registry = build_global_registry(conn, [pid])
    files = build_workspace_index(conn, [pid], global_registry=registry, namespaces={pid: "EMPTY"})
    body = files["_index/MOC — In Arbeit.md"].decode()
    assert "nothing in flight" in body.lower()
