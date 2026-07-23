from __future__ import annotations

import subprocess
from pathlib import Path

from typer.testing import CliRunner

from architectural_knowledge_db.cli import app
from architectural_knowledge_db.db.connection import initialize_database
from architectural_knowledge_db.models import ProjectUpsert
from architectural_knowledge_db.services.projects import ProjectService

runner = CliRunner()


def test_canon_export_command_registered():
    result = runner.invoke(app, ["canon", "--help"])
    assert result.exit_code == 0
    assert "export" in result.output
    assert "verify" in result.output


def test_canon_export_and_verify_round_trip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AKDB_DATABASE_PATH", str(tmp_path / "cli.sqlite"))
    conn = initialize_database(tmp_path / "cli.sqlite")
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="p", display_name="P"))
    conn.commit()
    conn.close()

    repo = tmp_path / "repo"
    live = repo / "docs" / "architecture"
    live.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (live / "START-HERE.md").write_text("# Start\n", encoding="utf-8", newline="")

    result = runner.invoke(
        app, ["document", "import", "--project", "p", "--folder", str(live), "--include", "**/*"]
    )
    assert result.exit_code == 0, result.output

    out = tmp_path / "export"
    result = runner.invoke(app, ["canon", "export", "--project", "p", "--folder", str(out)])
    assert result.exit_code == 0, result.output
    assert (out / "docs" / "architecture" / "START-HERE.md").is_file()

    result = runner.invoke(app, ["canon", "verify", "--project", "p", "--folder", str(repo)])
    assert result.exit_code == 0, result.output
    assert '"mismatched": []' in result.output
