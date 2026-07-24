from __future__ import annotations

import subprocess
from pathlib import Path

from typer.testing import CliRunner

from architectural_knowledge_db.cli import app
from architectural_knowledge_db.db.connection import initialize_database
from architectural_knowledge_db.models import ProjectUpsert
from architectural_knowledge_db.services.projects import ProjectService

runner = CliRunner()

# NOTE: the plan's illustrative CLI text uses `akdb export verify`/`export flush`.
# This codebase already has an unrelated `export verify`/`export run` command
# pair (corpus export/verify, --project/--folder options, no --target concept --
# see tests/test_export_proof.py). To avoid silently shadowing/breaking that
# existing surface, the new target-based commands use distinct verb names:
# `export target-add` / `export target-list` / `export flush` / `export sync` /
# `export target-verify`. Plan B's freshness gate (implemented later in this
# same runway) shells out to these exact names -- see progress.md.


def _seed(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("AKDB_DATABASE_PATH", str(tmp_path / "cli.sqlite"))
    conn = initialize_database(tmp_path / "cli.sqlite")
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="p", display_name="P"))
    conn.commit()
    conn.close()

    repo = tmp_path / "repo"
    live = repo / "docs" / "architecture" / "plugins" / "X"
    live.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (live / "architecture.md").write_text("# X\n\n## 1. Intro\n\nbody\n", encoding="utf-8", newline="")
    return repo


def test_export_target_add_list_sync_verify_round_trip(tmp_path: Path, monkeypatch) -> None:
    repo = _seed(tmp_path, monkeypatch)
    dest = tmp_path / "mirror"

    result = runner.invoke(
        app, ["document", "import", "--project", "p", "--folder", str(repo / "docs" / "architecture"), "--include", "**/*"]
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        app,
        [
            "export", "target-add", "p", "m",
            "--repo", "Git", "--dest", str(dest), "--layout", "arc42-canon",
            "--kinds", "sad,sad_section,sad_decision,uml,adr",
        ],
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["export", "target-list", "p"])
    assert result.exit_code == 0, result.output
    assert "m" in result.output

    result = runner.invoke(app, ["export", "sync", "p", "--target", "m"])
    assert result.exit_code == 0, result.output
    assert (dest / "plugins" / "X" / "architecture.md").is_file()

    result = runner.invoke(app, ["export", "target-verify", "p", "--target", "m"])
    assert result.exit_code == 0, result.output
    assert '"mismatched": []' in result.output

    # tamper -> verify must exit non-zero
    (dest / "plugins" / "X" / "architecture.md").write_text("tampered\n", encoding="utf-8", newline="")
    result = runner.invoke(app, ["export", "target-verify", "p", "--target", "m"])
    assert result.exit_code != 0

    result = runner.invoke(app, ["export", "target-delete", "p", "m"])
    assert result.exit_code == 0, result.output
    assert '"deleted": true' in result.output


def test_document_update_canonical_cli(tmp_path: Path, monkeypatch) -> None:
    repo = _seed(tmp_path, monkeypatch)
    result = runner.invoke(
        app,
        [
            "repo",
            "add",
            "--project",
            "p",
            "--id",
            "Git",
            "--path",
            str(repo),
        ],
    )
    assert result.exit_code == 0, result.output
    result = runner.invoke(
        app,
        [
            "document",
            "import",
            "--project",
            "p",
            "--folder",
            str(repo / "docs" / "architecture"),
            "--include",
            "**/*",
        ],
    )
    assert result.exit_code == 0, result.output
    body_file = tmp_path / "replacement.md"
    body_file.write_text(
        "# X\n\nDB-native CLI replacement.\n",
        encoding="utf-8",
        newline="",
    )

    result = runner.invoke(
        app,
        [
            "document",
            "update-canonical",
            "--project",
            "p",
            "--repository",
            "Git",
            "--source-key",
            "docs/architecture/plugins/X/architecture.md",
            "--body-file",
            str(body_file),
            "--body-origin",
            "canonical",
        ],
    )

    assert result.exit_code == 0, result.output
    assert '"item_type": "sad"' in result.output

    new_body = tmp_path / "new.md"
    new_body.write_text(
        "# New\n\n## 1. Goals\n\nDB-owned.\n",
        encoding="utf-8",
        newline="",
    )
    result = runner.invoke(
        app,
        [
            "document",
            "create-canonical",
            "--project",
            "p",
            "--repository",
            "Git",
            "--source-key",
            "docs/architecture/plugins/New/architecture.md",
            "--body-file",
            str(new_body),
            "--body-origin",
            "canonical",
        ],
    )
    assert result.exit_code == 0, result.output
    assert '"item_type": "sad"' in result.output
