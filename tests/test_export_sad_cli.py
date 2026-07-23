from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from architectural_knowledge_db.cli import app
from architectural_knowledge_db.db.connection import initialize_database
from architectural_knowledge_db.models import ProjectUpsert
from architectural_knowledge_db.services.import_export import ImportExportService
from architectural_knowledge_db.services.projects import ProjectService
from tests.test_sad_sections import SAD


def test_cli_sad_export_writes_architecture_md(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AKDB_DATABASE_PATH", str(tmp_path / "cli.sqlite"))
    runner = CliRunner()

    conn = initialize_database(tmp_path / "cli.sqlite")
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="p", display_name="P"))
    src = tmp_path / "src"
    src.mkdir()
    (src / "architecture.md").write_text(SAD, encoding="utf-8", newline="\n")
    ImportExportService(conn).import_documents("p", src)
    conn.commit()
    conn.close()

    out = tmp_path / "out"
    result = runner.invoke(app, ["sad", "export", "--project", "p", "--folder", str(out)])
    assert result.exit_code == 0, result.output
    text = (out / "architecture.md").read_text(encoding="utf-8")
    assert "## 1. Introduction" in text
    assert "### D1: First decision" in text
