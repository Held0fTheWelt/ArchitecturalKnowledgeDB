from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from architectural_knowledge_db.cli import app
from architectural_knowledge_db.db.connection import initialize_database
from architectural_knowledge_db.models import ProjectUpsert, RuleInput
from architectural_knowledge_db.services.authoring import AuthoringService
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.projects import ProjectService

runner = CliRunner()


def _seed(tmp_path: Path, monkeypatch) -> str:
    monkeypatch.setenv("AKDB_DATABASE_PATH", str(tmp_path / "cli.sqlite"))
    conn = initialize_database(tmp_path / "cli.sqlite")
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="p", display_name="P"))
    authoring = AuthoringService(conn)
    mvp = authoring.create_mvp("p", "M1", "m")["mvp"]["item_uid"]
    spec_uid = authoring.create_spec("p", "S1", "T", "plugin", mvp)["item_uid"]
    conn.commit()
    conn.close()
    return spec_uid


def test_cli_work_open_and_change_set_state(tmp_path: Path, monkeypatch) -> None:
    _seed(tmp_path, monkeypatch)
    impact = tmp_path / "impact.md"
    impact.write_text(
        "# Spec\n\n## Architektur-Impact\n- add rule R1\n",
        encoding="utf-8",
        newline="\n",
    )

    result = runner.invoke(app, ["spec", "ingest", "p", "S1", str(impact)])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["work", "open", "p"])
    assert result.exit_code == 0, result.output
    assert "S1" in result.output

    conn = initialize_database(tmp_path / "cli.sqlite")
    from architectural_knowledge_db.services.change_sets import ChangeSetService

    item_id = ChangeSetService(conn).open_work_orders("p")[0]["items"][0]["id"]
    conn.close()

    result = runner.invoke(app, ["change", "set-state", "p", str(item_id), "done"])
    assert result.exit_code == 0, result.output
    assert "done" in result.output


def test_cli_plan_basis_and_promote(tmp_path: Path, monkeypatch) -> None:
    _seed(tmp_path, monkeypatch)
    impact = tmp_path / "impact.md"
    impact.write_text(
        "# Spec\n\n## Architektur-Impact\n- add rule R1\n",
        encoding="utf-8",
        newline="\n",
    )
    assert runner.invoke(app, ["spec", "ingest", "p", "S1", str(impact)]).exit_code == 0

    result = runner.invoke(app, ["spec", "plan-basis", "p", "S1"])
    assert result.exit_code == 0, result.output
    assert "change_items" in result.output

    conn = initialize_database(tmp_path / "cli.sqlite")
    from architectural_knowledge_db.services.change_sets import ChangeSetService

    KnowledgeService(conn).upsert_rule("p", RuleInput(rule_id="R1", rule_text="no raw mesh"))
    item_id = ChangeSetService(conn).open_work_orders("p")[0]["items"][0]["id"]
    ChangeSetService(conn).set_item_state("p", item_id, "done")
    conn.commit()
    conn.close()

    result = runner.invoke(app, ["spec", "promote", "p", "S1"])
    assert result.exit_code == 0, result.output
    assert "implemented" in result.output
