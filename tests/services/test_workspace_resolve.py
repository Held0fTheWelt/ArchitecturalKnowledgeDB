from __future__ import annotations

import json

from architectural_knowledge_db.models import ProjectUpsert, RepositoryRegistration
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.services.repositories import RepositoryService
from architectural_knowledge_db.services.workspace import WorkspaceService


def _seed(conn, repo, files):
    # repository_files.repository_id has a FOREIGN KEY into repositories(repository_id),
    # so the registration record must exist even though scan_inventory is bypassed here
    # (this test proves resolution is DB-only — the target repo's disk copy is never read).
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="ws", display_name="WS"))
    RepositoryService(conn).register_repository(
        "ws", RepositoryRegistration(repository_id=repo, local_path=repo)
    )
    for path, anchors in files.items():
        conn.execute(
            "INSERT OR REPLACE INTO repository_files (repository_id, path, anchors_json) VALUES (?, ?, ?)",
            (repo, path, json.dumps(anchors)),
        )
    conn.commit()


def test_resolve_reference_paths_and_anchors(conn):
    _seed(conn, "Website", {
        "build.py": [],
        "src/static/atlas3d.js": [],
        "README.md": ["overview", "install"],
    })
    ws = WorkspaceService(conn)

    # path hit; an anchor on a non-markdown target is ignored (GitHub has none)
    assert ws.resolve_reference("ws", "Website/src/static/atlas3d.js#anything")["resolved"] is True
    # path miss
    assert ws.resolve_reference("ws", "Website/does/not/exist.py")["reason"] == "path_not_in_inventory"
    # unregistered repo
    assert ws.resolve_reference("ws", "NoSuchRepo/x.py")["reason"] == "repository_not_registered"
    # markdown anchors verified from the inventory, no filesystem
    assert ws.resolve_reference("ws", "Website/README.md#install")["resolved"] is True
    miss = ws.resolve_reference("ws", "Website/README.md#no-such-heading")
    assert miss["resolved"] is False and miss["reason"] == "anchor_not_found"


def test_git_alias_maps_to_plugins_repo(conn):
    _seed(conn, "TTD-Plugins", {"docs/architecture/START-HERE.md": ["start"]})
    ws = WorkspaceService(conn)
    r = ws.resolve_reference("ws", "Git/docs/architecture/START-HERE.md#start", aliases={"Git": "TTD-Plugins"})
    assert r["resolved"] is True and r["repository_id"] == "TTD-Plugins"
