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


def test_cli_sad_export_uses_self_export_default(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "TinyToolDevelopment" / "ArchitecturalKnowledgeDB"
    data = repo / ".akdb"
    data.mkdir(parents=True)
    db_path = data / "architectural_knowledge_db.sqlite"
    monkeypatch.setenv("AKDB_DATA_ROOT", str(data))
    monkeypatch.setenv("AKDB_DATABASE_PATH", str(db_path))
    runner = CliRunner()

    conn = initialize_database(db_path)
    ProjectService(conn).upsert_project(
        ProjectUpsert(project_id="architectural-knowledge-db", display_name="AKDB")
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "architecture.md").write_text(SAD, encoding="utf-8", newline="\n")
    ImportExportService(conn).import_documents("architectural-knowledge-db", src)
    conn.commit()
    conn.close()

    result = runner.invoke(app, ["sad", "export", "--project", "architectural-knowledge-db"])
    assert result.exit_code == 0, result.output
    out = repo / "docs" / "architecture" / "architecture.md"
    assert out.is_file()
    assert "## 1. Introduction" in out.read_text(encoding="utf-8")


def test_cli_authors_sad_directly_in_database(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "cli-author.sqlite"
    monkeypatch.setenv("AKDB_DATABASE_PATH", str(db))
    runner = CliRunner()
    conn = initialize_database(db)
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="p", display_name="P"))
    conn.commit()
    conn.close()

    assert runner.invoke(
        app,
        [
            "sad", "upsert", "--project", "p", "--document", "root", "--title", "Root",
            "--preamble", "# Root", "--frontmatter-json", '{"id":"SAD-P"}',
        ],
    ).exit_code == 0
    assert runner.invoke(
        app,
        [
            "sad", "section-set", "--project", "p", "--document", "root", "--id", "intro",
            "--title", "1. Introduction", "--order", "0", "--body", "Direct DB authoring.",
        ],
    ).exit_code == 0
    assert runner.invoke(
        app,
        [
            "uml", "create", "--project", "p", "--diagram", "context",
            "--title", "Context", "--kind", "component",
            "--source-key", "UML/context.puml", "--sad-document", "root",
            "--raw-source", "@startuml\ncomponent Context\n@enduml\n",
        ],
    ).exit_code == 0
    out = tmp_path / "out"
    result = runner.invoke(app, ["sad", "export", "--project", "p", "--folder", str(out)])
    assert result.exit_code == 0, result.output
    architecture = (out / "architecture.md").read_text(encoding="utf-8")
    assert "id: SAD-P" in architecture
    assert "Direct DB authoring." in architecture
    assert "component Context" in (out / "UML" / "context.puml").read_text(encoding="utf-8")
