from __future__ import annotations

from pathlib import Path
import subprocess

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


def test_api_db_native_sad_and_uml_crud(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AKDB_DATABASE_PATH", str(tmp_path / "api-authoring.sqlite"))
    client = TestClient(create_app())
    assert client.post("/projects", json={"project_id": "p", "display_name": "P"}).status_code == 200

    response = client.put(
        "/projects/p/sads/root",
        json={
            "document_id": "root",
            "title": "Root",
            "source_key": "architecture.md",
            "preamble_md": "# Root",
        },
    )
    assert response.status_code == 200
    response = client.put(
        "/projects/p/sads/root/sections/intro",
        json={
            "document_id": "root",
            "section_id": "intro",
            "title": "1. Introduction",
            "order": 0,
            "body_md": "API-authored.",
        },
    )
    assert response.status_code == 200
    assert client.get("/projects/p/sads/root").json()["source_uri"] == "akdb://p/sad/root"

    response = client.post(
        "/projects/p/uml/diagrams",
        json={
            "diagram_id": "components",
            "title": "Components",
            "diagram_kind": "c4-component",
            "model": {"source_key": "UML/components.puml", "sad_document_id": "root"},
        },
    )
    assert response.status_code == 200
    assert response.json()["source_uri"] == "akdb://p/uml/components"
    assert client.delete("/projects/p/uml/diagrams/components").status_code == 200


def test_api_updates_existing_canonical_document_without_source_write(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "AKDB_DATABASE_PATH",
        str(tmp_path / "api-canonical-update.sqlite"),
    )
    client = TestClient(create_app())
    repository = tmp_path / "repo"
    source = (
        repository
        / "docs"
        / "architecture"
        / "plugins"
        / "Example"
        / "architecture.md"
    )
    source.parent.mkdir(parents=True)
    source.write_text("# Example\n\nOriginal.\n", encoding="utf-8", newline="")
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)

    assert client.post(
        "/projects",
        json={"project_id": "p", "display_name": "P"},
    ).status_code == 200
    assert client.post(
        "/projects/p/repositories",
        json={"repository_id": "Git", "local_path": str(repository)},
    ).status_code == 200
    assert client.post(
        "/projects/p/imports/documents",
        params={
            "folder": str(repository / "docs" / "architecture"),
            "include": "**/*",
        },
    ).status_code == 200

    replacement = "# Example\n\nDB-native API replacement.\n"
    response = client.put(
        "/projects/p/canon/document",
        json={
            "repository_id": "Git",
            "repo_source_key": (
                "docs/architecture/plugins/Example/architecture.md"
            ),
            "body_text": replacement,
            "body_origin": "canonical",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["item_type"] == "sad"
    assert source.read_text(encoding="utf-8") == "# Example\n\nOriginal.\n"


def test_api_creates_canonical_document_without_source_write(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "AKDB_DATABASE_PATH",
        str(tmp_path / "api-canonical-create.sqlite"),
    )
    client = TestClient(create_app())
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)

    assert client.post(
        "/projects",
        json={"project_id": "p", "display_name": "P"},
    ).status_code == 200
    assert client.post(
        "/projects/p/repositories",
        json={"repository_id": "Git", "local_path": str(repository)},
    ).status_code == 200

    source_key = "docs/architecture/plugins/New/architecture.md"
    response = client.post(
        "/projects/p/canon/document",
        json={
            "repository_id": "Git",
            "repo_source_key": source_key,
            "body_text": "# New\n\n## 1. Goals\n\nDB-owned.\n",
            "body_origin": "canonical",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["item_type"] == "sad"
    assert not (repository / Path(*source_key.split("/"))).exists()
