from __future__ import annotations

import subprocess
from pathlib import Path

from architectural_knowledge_db.services.import_export import ImportExportService
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.models import ProjectUpsert

FIXTURES = {
    "docs/architecture/plugins/Demo/architecture.md": "# Demo\n\n## 1. Goals\n\nBody.\n",
    "docs/architecture/plugins/Demo/product-facts.yml": "display_name: Demo\n",  # class H, retained
    "UML/Plugins/Demo/components/c4-context.puml": "@startuml\n@enduml\n",
}


def _seed(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    for rel, text in FIXTURES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="")


def test_verify_canon_clean_when_mirror_matches_live_tree(conn, tmp_path):
    repo = tmp_path / "repo"
    _seed(repo)
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="canon", display_name="Canon"))
    svc = ImportExportService(conn)
    # Ingest only SAD + UML (NOT product-facts — class H is not ingested, per spec §3).
    svc.import_documents("canon", repo / "docs" / "architecture",
                          include=["**/*"], exclude=["**/product-facts.yml"])
    svc.import_documents("canon", repo / "UML", include=["**/*"])

    result = svc.verify_canon("canon", repo)

    assert result["mismatched"] == []
    # product-facts.yml exists in the live tree but is class H -> excluded, not "missing".
    assert result["missing"] == []
    assert result["matched"] >= 2


def test_verify_canon_flags_a_tampered_file(conn, tmp_path):
    repo = tmp_path / "repo"
    _seed(repo)
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="canon2", display_name="Canon2"))
    svc = ImportExportService(conn)
    svc.import_documents("canon2", repo / "docs" / "architecture",
                          include=["**/*"], exclude=["**/product-facts.yml"])
    svc.import_documents("canon2", repo / "UML", include=["**/*"])
    # Live file drifts from what AKDB holds:
    (repo / "docs/architecture/plugins/Demo/architecture.md").write_text(
        "# Demo TAMPERED\n", encoding="utf-8", newline=""
    )

    result = svc.verify_canon("canon2", repo)
    assert any("architecture.md" in m for m in result["mismatched"])
