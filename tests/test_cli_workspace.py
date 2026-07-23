from __future__ import annotations

from typer.testing import CliRunner

from architectural_knowledge_db.cli import app

runner = CliRunner()


def test_workspace_commands_registered():
    result = runner.invoke(app, ["workspace", "--help"])
    assert result.exit_code == 0
    assert "scan" in result.output
    assert "resolve" in result.output
    assert "export-manifest" in result.output
