from __future__ import annotations

import pytest

from architectural_knowledge_db.models import AdrInput
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.search import SearchService
from tests.conftest import add_project


def test_same_adr_id_can_exist_in_two_projects(conn) -> None:
    add_project(conn, "project-a")
    add_project(conn, "project-b")
    knowledge = KnowledgeService(conn)
    knowledge.upsert_adr(
        "project-a",
        AdrInput(
            adr_id="ADR-0002",
            title="Use SQLite",
            status="accepted",
            decision_md="Project A stores architecture knowledge in SQLite.",
        ),
    )
    knowledge.upsert_adr(
        "project-b",
        AdrInput(
            adr_id="ADR-0002",
            title="Use JSON",
            status="accepted",
            decision_md="Project B exports portable JSON bundles.",
        ),
    )

    project_a = knowledge.get_adr("project-a", "ADR-0002")
    project_b = knowledge.get_adr("project-b", "ADR-0002")

    assert project_a["title"] == "Use SQLite"
    assert project_b["title"] == "Use JSON"


def test_search_requires_project_id(conn) -> None:
    add_project(conn, "project-a")
    knowledge = KnowledgeService(conn)
    knowledge.upsert_adr(
        "project-a",
        AdrInput(adr_id="ADR-0001", title="Scoped search", decision_md="No global search."),
    )

    with pytest.raises(ValueError, match="project_id is required"):
        SearchService(conn).search("", "global")


def test_search_does_not_leak_between_projects(conn) -> None:
    add_project(conn, "project-a")
    add_project(conn, "project-b")
    knowledge = KnowledgeService(conn)
    knowledge.upsert_adr(
        "project-a",
        AdrInput(adr_id="ADR-0001", title="Only A", decision_md="Needle belongs to A."),
    )
    knowledge.upsert_adr(
        "project-b",
        AdrInput(adr_id="ADR-0001", title="Only B", decision_md="Different project."),
    )

    results = SearchService(conn).search("project-b", "Needle")

    assert results == []
