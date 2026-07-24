from __future__ import annotations

import json
import subprocess
from pathlib import Path

from architectural_knowledge_db.mcp import McpDispatcher
from architectural_knowledge_db.services.export_targets import ExportTargetsService
from architectural_knowledge_db.services.import_export import ImportExportService
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.services.repositories import RepositoryService
from architectural_knowledge_db.models import ProjectUpsert, RepositoryRegistration


def _seed(conn, tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="p", display_name="P"))
    RepositoryService(conn).register_repository(
        "p",
        RepositoryRegistration(repository_id="Git", local_path=str(tmp_path)),
    )
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


def test_akdb_update_canonical_document_tool(conn, tmp_path):
    _seed(conn, tmp_path)
    body = "# X\n\n## 1. Intro\n\nDB-native replacement.\n"

    result = McpDispatcher(conn).dispatch(
        "akdb_update_canonical_document",
        {
            "project_id": "p",
            "repository_id": "Git",
            "repo_source_key": "docs/architecture/plugins/X/architecture.md",
            "body_text": body,
            "body_origin": "canonical",
        },
    )

    assert result["repo_source_key"] == (
        "docs/architecture/plugins/X/architecture.md"
    )
    owner = conn.execute(
        """
        SELECT metadata_json
        FROM knowledge_items
        WHERE item_uid = ?
        """,
        (result["item_uid"],),
    ).fetchone()
    assert json.loads(owner["metadata_json"])["body_text"] == body


def test_akdb_create_canonical_document_tool(conn, tmp_path):
    _seed(conn, tmp_path)
    body = "# New\n\n## 1. Goals\n\nDB-owned.\n"

    result = McpDispatcher(conn).dispatch(
        "akdb_create_canonical_document",
        {
            "project_id": "p",
            "repository_id": "Git",
            "repo_source_key": (
                "docs/architecture/plugins/New/architecture.md"
            ),
            "body_text": body,
            "body_origin": "canonical",
        },
    )

    assert result["item_type"] == "sad"
    owner = conn.execute(
        "SELECT metadata_json FROM knowledge_items WHERE item_uid = ?",
        (result["item_uid"],),
    ).fetchone()
    assert json.loads(owner["metadata_json"])["body_text"] == body


def test_akdb_obsidian_sync_and_verify_tools(conn, tmp_path):
    from tests.services.test_obsidian_expected_files import _seed_min_project

    pid = _seed_min_project(conn)
    dest = tmp_path / "TTD"
    ExportTargetsService(conn).register_target(
        pid,
        "vault",
        repository_id="Git",
        dest_root=str(dest),
        layout="obsidian-vault",
        content_kinds=["sad", "adr"],
        auto_export=False,
    )
    dispatcher = McpDispatcher(conn)
    dispatcher.dispatch("akdb_obsidian_sync", {"project_id": pid, "target_id": "vault"})
    assert any(dest.rglob("*.md"))
    result = dispatcher.dispatch("akdb_obsidian_verify", {"project_id": pid, "target_id": "vault"})
    assert result["mismatched"] == [] and result["missing"] == [] and result["extra"] == []
