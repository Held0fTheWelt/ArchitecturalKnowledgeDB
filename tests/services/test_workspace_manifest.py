from __future__ import annotations

import json
import subprocess

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


def test_export_manifest_projects_live_head_without_mutating_inventory(conn, tmp_path):
    repo = tmp_path / "Website"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    readme = repo / "README.md"
    readme.write_text("# Initial\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=repo, check=True)

    ProjectService(conn).upsert_project(ProjectUpsert(project_id="ws", display_name="WS"))
    RepositoryService(conn).register_repository(
        "ws",
        RepositoryRegistration(repository_id="Website", local_path=str(repo)),
    )
    service = WorkspaceService(conn)
    scanned = service.scan_inventory("ws", "Website")

    readme.write_text("# Current\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "current"], cwd=repo, check=True)
    live_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    out = tmp_path / "workspace-manifest.json"
    service.export_manifest("ws", out)

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["repositories"]["Website"]["sha"] == live_head
    assert live_head != scanned["head_sha"]
    stored = conn.execute(
        "SELECT head_sha FROM repository_inventory_meta WHERE repository_id = ?",
        ("Website",),
    ).fetchone()
    assert stored["head_sha"] == scanned["head_sha"]
