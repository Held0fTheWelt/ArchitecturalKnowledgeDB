from __future__ import annotations

import json

from architectural_knowledge_db.mcp import McpDispatcher
from architectural_knowledge_db.models import AdrInput
from architectural_knowledge_db.services.knowledge import KnowledgeService
from tests.conftest import add_project


def _seed(conn) -> None:
    add_project(conn, "akdb")
    KnowledgeService(conn).upsert_adr(
        "akdb",
        AdrInput(
            adr_id="ADR-0001",
            title="Compact Output Contract",
            status="accepted",
            decision_md="Bulk MCP tools return compact records by default.",
            context_md="ctx " * 2000,
            consequences_md="cons " * 2000,
            raw_source="# ADR-0001\n" + ("body " * 4000),
        ),
    )
    conn.commit()


def test_search_compact_by_default(conn) -> None:
    _seed(conn)
    results = McpDispatcher(conn).dispatch(
        "architectural_knowledge_db_search", {"project_id": "akdb", "query": "compact"}
    )
    assert results, "expected at least one hit"
    blob = json.dumps(results)
    assert "raw_source" not in blob
    assert "decision_md" not in blob
    assert "consequences_md" not in blob
    # identity + triage fields are preserved
    assert results[0]["item_uid"]
    assert results[0]["title"] == "Compact Output Contract"
    assert "authority_level" in results[0]


def test_search_full_is_opt_in(conn) -> None:
    _seed(conn)
    results = McpDispatcher(conn).dispatch(
        "architectural_knowledge_db_search",
        {"project_id": "akdb", "query": "compact", "detail": "full"},
    )
    blob = json.dumps(results)
    assert "raw_source" in blob
    assert "decision_md" in blob


def test_context_pack_compact_by_default(conn) -> None:
    _seed(conn)
    pack = McpDispatcher(conn).dispatch(
        "architectural_knowledge_db_get_context_pack",
        {"project_id": "akdb", "task": "compact output contract"},
    )
    blob = json.dumps(pack)
    assert "raw_source" not in blob
    assert "decision_md" not in blob
    # the pack still routes the ADR and keeps its identity
    assert pack["accepted_adrs"], "expected the ADR in the pack"
    assert pack["accepted_adrs"][0]["local_id"] == "ADR-0001"


def test_list_diagrams_compact_drops_raw_source(conn) -> None:
    add_project(conn, "akdb")
    from architectural_knowledge_db.services.uml import UMLService

    UMLService(conn).import_diagrams(
        "akdb",
        _write_puml(conn),
    )
    conn.commit()
    diagrams = McpDispatcher(conn).dispatch("akdb_list_diagrams", {"project_id": "akdb"})
    assert diagrams
    blob = json.dumps(diagrams)
    assert "raw_source" not in blob
    assert diagrams[0]["diagram_id"]


def _write_puml(conn) -> str:
    import tempfile
    from pathlib import Path

    folder = Path(tempfile.mkdtemp())
    (folder / "demo.puml").write_text(
        "@startuml demo\ntitle Demo\nclass A\nclass B\nA --> B\n@enduml\n", encoding="utf-8"
    )
    return str(folder)
