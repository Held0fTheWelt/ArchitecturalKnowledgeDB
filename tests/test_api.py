from __future__ import annotations

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from architectural_knowledge_db.api.app import create_app


def test_api_project_knowledge_search_context_pack(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AKDB_DATABASE_PATH", str(tmp_path / "api.sqlite"))
    client = TestClient(create_app())

    response = client.post("/projects", json={"project_id": "akdb", "display_name": "AKDB"})
    assert response.status_code == 200

    response = client.post(
        "/projects/akdb/adrs",
        json={
            "adr_id": "ADR-0002",
            "title": "DB First",
            "status": "accepted",
            "decision_md": "SQLite is the primary local state.",
        },
    )
    assert response.status_code == 200

    response = client.post("/projects/akdb/search", json={"query": "SQLite"})
    assert response.status_code == 200
    assert response.json()[0]["local_id"] == "ADR-0002"

    response = client.post("/projects/akdb/context-pack", json={"task": "Change SQLite store"})
    assert response.status_code == 200
    assert response.json()["accepted_adrs"][0]["local_id"] == "ADR-0002"

    response = client.get("/projects/akdb/drift/status-quo")
    assert response.status_code == 200
    assert response.json()["mode"] == "status_quo"

    response = client.post("/projects/akdb/staleness/compute?mode=status_quo")
    assert response.status_code == 200
    assert response.json()["mode"] == "status_quo"

    response = client.post("/projects/akdb/drift/run")
    assert response.status_code == 200
    assert response.json()["mode"] == "complete_drift_run"

    response = client.get("/")
    assert response.status_code == 200
    assert "ArchitecturalKnowledgeDB Admin" in response.text


def test_api_uml_and_consistency_endpoints(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AKDB_DATABASE_PATH", str(tmp_path / "api-uml.sqlite"))
    client = TestClient(create_app())
    uml_dir = tmp_path / "uml"
    uml_dir.mkdir()
    (uml_dir / "model.puml").write_text("@startuml\nclass A\nclass B\nA --> B\n@enduml\n", encoding="utf-8")

    assert client.post("/projects", json={"project_id": "akdb", "display_name": "AKDB"}).status_code == 200
    response = client.post(f"/projects/akdb/uml/import?folder={uml_dir}")
    assert response.status_code == 200
    assert response.json()["imported"] == 1

    response = client.get("/projects/akdb/uml/diagrams/model")
    assert response.status_code == 200
    assert response.json()["diagram_kind"] == "class"

    response = client.post("/projects/akdb/consistency/check", json={})
    assert response.status_code == 200
    assert isinstance(response.json(), list)
