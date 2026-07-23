from __future__ import annotations

import subprocess
from pathlib import Path

from architectural_knowledge_db.mcp import McpDispatcher
from architectural_knowledge_db.services.export_targets import ExportTargetsService
from architectural_knowledge_db.services.import_export import ImportExportService
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.models import ProjectUpsert


def _seed(conn, tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="p", display_name="P"))
    tree = tmp_path / "docs" / "architecture" / "plugins" / "X"
    tree.mkdir(parents=True)
    (tree / "architecture.md").write_text("# X\n\n## 1. Intro\n\nbody\n", encoding="utf-8", newline="")
    ImportExportService(conn).import_documents("p", tmp_path / "docs" / "architecture", include=["**/*"])
    dest = tmp_path / "mirror"
    ExportTargetsService(conn).register_target(
        "p", "m", repository_id="Git", dest_root=str(dest), layout="arc42-canon",
        content_kinds=["sad"], auto_export=False,
    )
    return dest


def test_akdb_export_sync_and_verify_export_tools(conn, tmp_path):
    dest = _seed(conn, tmp_path)
    dispatcher = McpDispatcher(conn)
    dispatcher.dispatch("akdb_export_sync", {"project_id": "p", "target_id": "m"})
    assert (dest / "plugins" / "X" / "architecture.md").is_file()

    result = dispatcher.dispatch("akdb_verify_export", {"project_id": "p", "target_id": "m"})
    assert set(result.keys()) >= {"matched", "mismatched", "missing", "extra"}
    assert result["mismatched"] == [] and result["missing"] == [] and result["extra"] == []


def test_akdb_export_flush_tool(conn, tmp_path):
    dest = _seed(conn, tmp_path)
    ExportTargetsService(conn).mark_dirty(
        "p", "sad", "docs/architecture/plugins/X/architecture.md", "upsert", target_id="m"
    )
    result = McpDispatcher(conn).dispatch("akdb_export_flush", {"project_id": "p", "target_id": "m"})
    assert any("architecture.md" in w for w in result["written"])
    assert (dest / "plugins" / "X" / "architecture.md").is_file()
