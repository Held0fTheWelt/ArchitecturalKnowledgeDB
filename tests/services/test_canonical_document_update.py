from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from architectural_knowledge_db.models import (
    CanonicalDocumentCreate,
    CanonicalDocumentUpdate,
    ProjectUpsert,
    RepositoryRegistration,
)
from architectural_knowledge_db.services.export_targets import ExportTargetsService
from architectural_knowledge_db.services.import_export import ImportExportService
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.services.repositories import RepositoryService
from architectural_knowledge_db.services.uml import UMLService


def _setup_repository(conn, tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    ProjectService(conn).upsert_project(
        ProjectUpsert(project_id="p", display_name="P")
    )
    RepositoryService(conn).register_repository(
        "p",
        RepositoryRegistration(repository_id="Git", local_path=str(tmp_path)),
    )
    ExportTargetsService(conn).register_target(
        "p",
        "m",
        repository_id="Git",
        dest_root="docs/architecture/_generated",
        layout="arc42-canon",
        content_kinds=["sad", "uml", "adr"],
        auto_export=False,
    )
    return tmp_path


def test_update_canonical_sad_replaces_body_links_and_derived_children(
    conn, tmp_path: Path
) -> None:
    root = _setup_repository(conn, tmp_path)
    sad_path = (
        root
        / "docs"
        / "architecture"
        / "project"
        / "demo"
        / "architecture.md"
    )
    sad_path.parent.mkdir(parents=True)
    sad_path.write_text(
        "# Demo\n\n"
        "## 1. Introduction & Goals\n\n[Old](../old.md)\n\n"
        "## 9. Architecture Decisions\n\n"
        "### D1: Keep one\n\n**Status:** Accepted\n\nFirst.\n\n"
        "### D2: Remove this\n\n**Status:** Accepted\n\nStale.\n",
        encoding="utf-8",
        newline="",
    )
    service = ImportExportService(conn)
    service.import_documents(
        "p",
        root / "docs" / "architecture",
        include=["**/*"],
    )

    replacement = (
        "# Demo\n\n"
        "## 1. Introduction & Goals\n\n[New](../new.md)\n\n"
        "## 9. Architecture Decisions\n\n"
        "### D3: Replace both\n\n**Status:** Accepted\n\nCurrent.\n"
    )
    result = service.update_canonical_document(
        "p",
        CanonicalDocumentUpdate(
            repository_id="Git",
            repo_source_key="docs/architecture/project/demo/architecture.md",
            body_text=replacement,
            body_origin="canonical",
        ),
    )

    assert result["item_type"] == "sad"
    owner = conn.execute(
        """
        SELECT source_uri, metadata_json
        FROM knowledge_items
        WHERE item_uid = ?
        """,
        (result["item_uid"],),
    ).fetchone()
    metadata = json.loads(owner["metadata_json"])
    assert owner["source_uri"].startswith("akdb://p/canon/")
    assert metadata["body_text"] == replacement
    assert metadata["authored_in"] == "akdb"

    decisions = conn.execute(
        """
        SELECT json_extract(metadata_json, '$.decision_id') AS decision_id
        FROM knowledge_items
        WHERE project_id = ?
          AND item_type = 'sad_decision'
          AND json_extract(metadata_json, '$.parent_item_uid') = ?
        ORDER BY decision_id
        """,
        ("p", result["item_uid"]),
    ).fetchall()
    assert [row["decision_id"] for row in decisions] == ["D3"]

    links = conn.execute(
        """
        SELECT target_ref
        FROM knowledge_links
        WHERE source_item_uid = ?
        ORDER BY target_ref
        """,
        (result["item_uid"],),
    ).fetchall()
    targets = [row["target_ref"] for row in links]
    assert "docs/architecture/project/new.md" in targets
    assert "docs/architecture/project/old.md" not in targets
    dirty = ExportTargetsService(conn).peek_dirty("p", "m")
    assert any(
        row["item_ref"] == "docs/architecture/project/demo/architecture.md"
        for row in dirty
    )


def test_create_canonical_sad_without_source_side_authoring_file(
    conn, tmp_path: Path
) -> None:
    root = _setup_repository(conn, tmp_path)
    body = (
        "# New Plugin\n\n"
        "## 1. Introduction & Goals\n\nCurrent implementation.\n\n"
        "## 9. Architecture Decisions\n\n"
        "### D1: DB ownership\n\n"
        "**Status:** Accepted\n\nAKDB owns the body.\n"
    )
    result = ImportExportService(conn).create_canonical_document(
        "p",
        CanonicalDocumentCreate(
            repository_id="Git",
            repo_source_key=(
                "docs/architecture/plugins/NewPlugin/architecture.md"
            ),
            body_text=body,
            body_origin="canonical",
        ),
    )

    assert result["item_type"] == "sad"
    assert result["derived_records"] >= 2
    assert not (
        root
        / "docs"
        / "architecture"
        / "plugins"
        / "NewPlugin"
        / "architecture.md"
    ).exists()
    owner = KnowledgeService(conn).get_item_by_uid(result["item_uid"])
    assert owner["metadata"]["body_text"] == body
    assert owner["metadata"]["authored_in"] == "akdb"


def test_create_canonical_adr_creates_structured_record(
    conn, tmp_path: Path
) -> None:
    _setup_repository(conn, tmp_path)
    body = (
        "# ADR-DEMO-0002: DB-native creation\n\n"
        "## Status\n\naccepted\n\n"
        "## Context\n\nNo source-side authoring file exists.\n\n"
        "## Decision\n\nCreate body and structured ADR together.\n\n"
        "## Consequences\n\nExport remains a projection.\n"
    )
    result = ImportExportService(conn).create_canonical_document(
        "p",
        CanonicalDocumentCreate(
            repository_id="Git",
            repo_source_key=(
                "docs/ADR/Project/demo/adr-demo-0002-db-native-creation.md"
            ),
            body_text=body,
            body_origin="canonical",
        ),
    )

    assert result["item_type"] == "adr"
    adr = KnowledgeService(conn).get_adr("p", "ADR-DEMO-0002")
    assert adr["decision_md"] == "Create body and structured ADR together."
    assert adr["raw_source"] == body
    assert adr["metadata"]["body_text"] == body
    assert adr["metadata"]["authored_in"] == "akdb"


def test_create_canonical_adr_rejects_identity_collision(
    conn, tmp_path: Path
) -> None:
    _setup_repository(conn, tmp_path)
    body = (
        "# ADR-DEMO-0002: DB-native creation\n\n"
        "## Status\n\naccepted\n\n"
        "## Context\n\nContext.\n\n"
        "## Decision\n\nDecision.\n\n"
        "## Consequences\n\nConsequence.\n"
    )
    service = ImportExportService(conn)
    service.create_canonical_document(
        "p",
        CanonicalDocumentCreate(
            repository_id="Git",
            repo_source_key="docs/ADR/A/adr-demo-0002-first.md",
            body_text=body,
            body_origin="canonical",
        ),
    )

    colliding_key = "docs/ADR/B/adr-demo-0002-second.md"
    with pytest.raises(ValueError, match="ADR identity collision"):
        service.create_canonical_document(
            "p",
            CanonicalDocumentCreate(
                repository_id="Git",
                repo_source_key=colliding_key,
                body_text=body,
                body_origin="canonical",
            ),
        )
    assert service._body_owner_rows("p", colliding_key) == []


def test_create_canonical_plantuml_creates_matching_structured_diagram(
    conn, tmp_path: Path
) -> None:
    _setup_repository(conn, tmp_path)
    body = (
        "@startuml\n"
        "title New sequence\n"
        "participant Caller\n"
        "participant Service\n"
        "Caller -> Service : create\n"
        "@enduml\n"
    )
    result = ImportExportService(conn).create_canonical_document(
        "p",
        CanonicalDocumentCreate(
            repository_id="Git",
            repo_source_key=(
                "UML/Plugins/NewPlugin/sequence/new-sequence.puml"
            ),
            body_text=body,
            body_origin="canonical",
            sad_document_id="plugins-newplugin-architecture",
        ),
    )

    diagram = UMLService(conn).get_diagram(
        "p",
        result["structured_uml_diagram_id"],
    )
    assert diagram["raw_source"] == body
    assert diagram["model"]["repo_source_key"] == (
        "UML/Plugins/NewPlugin/sequence/new-sequence.puml"
    )
    assert diagram["model"]["sad_document_id"] == (
        "plugins-newplugin-architecture"
    )


def test_create_canonical_mermaid_creates_matching_structured_diagram(
    conn, tmp_path: Path
) -> None:
    _setup_repository(conn, tmp_path)
    body = "flowchart TD\n  A[Author] --> B[AKDB]\n"
    result = ImportExportService(conn).create_canonical_document(
        "p",
        CanonicalDocumentCreate(
            repository_id="Git",
            repo_source_key="UML/Project/New/flow/authoring.mmd",
            body_text=body,
            body_origin="canonical",
        ),
    )

    diagram = UMLService(conn).get_diagram(
        "p",
        result["structured_uml_diagram_id"],
    )
    assert diagram["notation"] == "mermaid"
    assert diagram["raw_source"] == body


def test_create_canonical_uml_rejects_structured_identity_collision(
    conn, tmp_path: Path
) -> None:
    _setup_repository(conn, tmp_path)
    service = ImportExportService(conn)
    service.create_canonical_document(
        "p",
        CanonicalDocumentCreate(
            repository_id="Git",
            repo_source_key="UML/A/B.puml",
            body_text="@startuml\ncomponent A\n@enduml\n",
            body_origin="canonical",
        ),
    )

    colliding_key = "UML/A-B.puml"
    with pytest.raises(ValueError, match="UML identity collision"):
        service.create_canonical_document(
            "p",
            CanonicalDocumentCreate(
                repository_id="Git",
                repo_source_key=colliding_key,
                body_text="@startuml\ncomponent B\n@enduml\n",
                body_origin="canonical",
            ),
        )
    assert service._body_owner_rows("p", colliding_key) == []


def test_create_canonical_document_rejects_existing_owner(
    conn, tmp_path: Path
) -> None:
    _setup_repository(conn, tmp_path)
    request = CanonicalDocumentCreate(
        repository_id="Git",
        repo_source_key="docs/architecture/plugins/New/README.md",
        body_text="# New\n",
        body_origin="canonical",
    )
    service = ImportExportService(conn)
    service.create_canonical_document("p", request)

    with pytest.raises(ValueError, match="already exists"):
        service.create_canonical_document("p", request)


def test_update_canonical_uml_keeps_generic_and_structured_models_in_sync(
    conn, tmp_path: Path
) -> None:
    root = _setup_repository(conn, tmp_path)
    uml_root = root / "UML"
    diagram_path = uml_root / "Project" / "demo" / "sequence" / "demo.puml"
    diagram_path.parent.mkdir(parents=True)
    diagram_path.write_text(
        "@startuml\nparticipant A\nparticipant B\nA -> B : old\n@enduml\n",
        encoding="utf-8",
        newline="",
    )
    ImportExportService(conn).import_documents(
        "p",
        uml_root,
        include=["**/*"],
    )
    UMLService(conn).import_diagrams("p", uml_root)

    replacement = (
        "@startuml\nparticipant A\nparticipant B\nA -> B : current\n@enduml\n"
    )
    result = ImportExportService(conn).update_canonical_document(
        "p",
        CanonicalDocumentUpdate(
            repository_id="Git",
            repo_source_key="UML/Project/demo/sequence/demo.puml",
            body_text=replacement,
            body_origin="canonical",
        ),
    )

    assert result["structured_uml_updated"] is True
    diagram = UMLService(conn).get_diagram("p", "project-demo-sequence-demo")
    assert diagram["raw_source"] == replacement
    assert diagram["model"]["repo_source_key"] == (
        "UML/Project/demo/sequence/demo.puml"
    )
    owner = conn.execute(
        """
        SELECT metadata_json
        FROM knowledge_items
        WHERE project_id = ?
          AND json_extract(metadata_json, '$.repo_source_key') = ?
          AND json_extract(metadata_json, '$.body_text') IS NOT NULL
        """,
        ("p", "UML/Project/demo/sequence/demo.puml"),
    ).fetchone()
    assert json.loads(owner["metadata_json"])["body_text"] == replacement


def test_update_canonical_adr_keeps_structured_record_and_body_in_sync(
    conn, tmp_path: Path
) -> None:
    root = _setup_repository(conn, tmp_path)
    adr_root = root / "docs" / "ADR"
    adr_path = adr_root / "Project" / "demo" / "adr-demo-0001-choice.md"
    adr_path.parent.mkdir(parents=True)
    adr_path.write_text(
        "# ADR-DEMO-0001: Choice\n\n"
        "## Status\n\naccepted\n\n"
        "## Context\n\nOld context.\n\n"
        "## Decision\n\nUse old behavior.\n\n"
        "## Consequences\n\nOld consequence.\n",
        encoding="utf-8",
        newline="",
    )
    ImportExportService(conn).import_adrs("p", adr_root)

    replacement = (
        "# ADR-DEMO-0001: Choice\n\n"
        "## Status\n\naccepted\n\n"
        "## Context\n\nCurrent context.\n\n"
        "## Decision\n\nUse canonical DB updates.\n\n"
        "## Consequences\n\nBody and structure remain synchronized.\n"
    )
    result = ImportExportService(conn).update_canonical_document(
        "p",
        CanonicalDocumentUpdate(
            repository_id="Git",
            repo_source_key="docs/ADR/Project/demo/adr-demo-0001-choice.md",
            body_text=replacement,
            body_origin="canonical",
        ),
    )

    assert result["item_type"] == "adr"
    adr = KnowledgeService(conn).get_adr("p", "ADR-DEMO-0001")
    assert adr["decision_md"] == "Use canonical DB updates."
    assert adr["consequences_md"] == "Body and structure remain synchronized."
    assert adr["metadata"]["body_text"] == replacement
    assert adr["metadata"]["authored_in"] == "akdb"


@pytest.mark.parametrize(
    "source_key",
    [
        "../docs/architecture/architecture.md",
        "/docs/architecture/architecture.md",
        "C:/docs/architecture/architecture.md",
    ],
)
def test_update_canonical_document_rejects_unsafe_source_keys(
    conn, tmp_path: Path, source_key: str
) -> None:
    _setup_repository(conn, tmp_path)

    with pytest.raises(ValueError, match="safe repository-relative path"):
        ImportExportService(conn).update_canonical_document(
            "p",
            CanonicalDocumentUpdate(
                repository_id="Git",
                repo_source_key=source_key,
                body_text="# Unsafe\n",
                body_origin="canonical",
            ),
        )


def test_update_canonical_document_rejects_missing_body_owner(
    conn, tmp_path: Path
) -> None:
    _setup_repository(conn, tmp_path)

    with pytest.raises(ValueError, match="Canonical document does not exist"):
        ImportExportService(conn).update_canonical_document(
            "p",
            CanonicalDocumentUpdate(
                repository_id="Git",
                repo_source_key="docs/architecture/project/missing/architecture.md",
                body_text="# Missing\n",
                body_origin="canonical",
            ),
        )


def test_update_canonical_document_rejects_generated_projection(
    conn, tmp_path: Path
) -> None:
    root = _setup_repository(conn, tmp_path)
    target_service = ExportTargetsService(conn)
    target_service.register_target(
        "p",
        "m",
        repository_id="Git",
        dest_root="docs/architecture/_generated",
        layout="arc42-canon",
        content_kinds=["sad", "uml", "adr"],
        auto_export=False,
    )
    sad_path = (
        root
        / "docs"
        / "architecture"
        / "project"
        / "demo"
        / "architecture.md"
    )
    sad_path.parent.mkdir(parents=True)
    canonical = (
        "# Demo\n\n"
        "## 1. Introduction & Goals\n\n"
        "[Source](../../../../GovernanceDevelopmentPlugins/Demo/Source)\n"
    )
    sad_path.write_text(canonical, encoding="utf-8", newline="")
    service = ImportExportService(conn)
    service.import_documents(
        "p",
        root / "docs" / "architecture",
        include=["**/*"],
    )
    service.export_incremental("p", "m")
    projected_path = (
        root
        / "docs"
        / "architecture"
        / "_generated"
        / "project"
        / "demo"
        / "architecture.md"
    )
    projected = projected_path.read_text(encoding="utf-8")
    assert projected != canonical

    with pytest.raises(ValueError, match="generated projection"):
        service.update_canonical_document(
            "p",
            CanonicalDocumentUpdate(
                repository_id="Git",
                repo_source_key=(
                    "docs/architecture/project/demo/architecture.md"
                ),
                body_text=projected,
                body_origin="canonical",
            ),
        )
