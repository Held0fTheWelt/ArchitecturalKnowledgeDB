from __future__ import annotations

import json

from architectural_knowledge_db.models import ProjectUpsert, RepositoryRegistration
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.services.repositories import RepositoryService
from architectural_knowledge_db.services.workspace import WorkspaceService


def test_export_manifest_shape(conn, tmp_path):
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="ws", display_name="WS"))
    RepositoryService(conn).register_repository(
        "ws", RepositoryRegistration(repository_id="Website", local_path="Website")
    )
    for path, anchors in [("build.py", []), ("src/app.js", []), ("README.md", ["overview"])]:
        conn.execute(
            "INSERT OR REPLACE INTO repository_files (repository_id, path, anchors_json) VALUES (?, ?, ?)",
            ("Website", path, json.dumps(anchors)),
        )
    conn.execute(
        "INSERT OR REPLACE INTO repository_inventory_meta (repository_id, head_sha, scanned_at) VALUES (?,?,?)",
        ("Website", "abc123", "2026-07-23T00:00:00Z"),
    )
    conn.commit()

    out = tmp_path / "workspace-manifest.json"
    WorkspaceService(conn).export_manifest("ws", out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["format_version"] == 1
    assert data["repositories"]["Website"]["sha"] == "abc123"
    assert set(data["repositories"]["Website"]["files"]) == {"build.py", "src/app.js", "README.md"}
    assert data["repositories"]["Website"]["anchors"]["README.md"] == ["overview"]
