from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from architectural_knowledge_db.cli import app
from architectural_knowledge_db.db.connection import initialize_database
from architectural_knowledge_db.models import AdrInput, ProjectUpsert
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.projects import ProjectService

runner = CliRunner()


def _seed_obsidian_project(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("AKDB_DATABASE_PATH", str(tmp_path / "cli.sqlite"))
    conn = initialize_database(tmp_path / "cli.sqlite")
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="p", display_name="P"))
    ks = KnowledgeService(conn)
    ks._upsert_item(
        project_id="p",
        space_id=None,
        item_type="sad",
        local_id="gov",
        title="Software Architecture",
        status="current",
        authority_level="active_rule",
        summary="SAD",
        source_uri="akdb://p/sad/gov",
        metadata={
            "repo_source_key": "docs/architecture/architecture.md",
            "repository_id": "Git",
            "system": "Governance",
            "body_text": "# Software Architecture\n\n## D1 Product boundary\n\nBody.\n",
            "body_encoding": "utf-8",
        },
    )
    ks.upsert_adr(
        "p",
        AdrInput(
            adr_id="ADR-0001",
            title="ADR-0001 Choose X",
            status="proposed",
            metadata={
                "repo_source_key": "docs/ADR/ADR-0001.md",
                "repository_id": "Git",
                "system": "Governance",
                "body_text": (
                    "# ADR-0001\n\n"
                    "See [SAD](docs/architecture/architecture.md#d1-product-boundary).\n"
                ),
                "body_encoding": "utf-8",
            },
        ),
    )
    conn.commit()
    conn.close()
    return tmp_path / "TTD"


def test_obsidian_verify_exit_code(tmp_path: Path, monkeypatch) -> None:
    dest = _seed_obsidian_project(tmp_path, monkeypatch)

    result = runner.invoke(
        app,
        [
            "export",
            "target-add",
            "p",
            "vault",
            "--repo",
            "Git",
            "--dest",
            str(dest),
            "--layout",
            "obsidian-vault",
            "--kinds",
            "sad,adr,uml_diagram",
            "--no-auto",
        ],
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["obsidian", "sync", "p", "--target", "vault"])
    assert result.exit_code == 0, result.output
    assert any(dest.rglob("*.md"))

    result = runner.invoke(app, ["obsidian", "verify", "p", "--target", "vault"])
    assert result.exit_code == 0, result.output

    # Corrupt one note → verify must exit non-zero
    note = next(dest.rglob("*.md"))
    note.write_text("tampered\n", encoding="utf-8", newline="")
    result = runner.invoke(app, ["obsidian", "verify", "p", "--target", "vault"])
    assert result.exit_code != 0
