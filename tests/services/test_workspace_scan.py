from __future__ import annotations

import subprocess
from pathlib import Path

from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.services.repositories import RepositoryService
from architectural_knowledge_db.services.workspace import WorkspaceService
from architectural_knowledge_db.models import ProjectUpsert, RepositoryRegistration


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    (path / "build.py").write_text("print(1)\n")
    (path / "src").mkdir()
    (path / "src" / "app.js").write_text("//\n")
    (path / "README.md").write_text("# Overview\n\n## Install Steps\n\ntext\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)


def test_scan_inventory_stores_paths_and_markdown_anchors(conn, tmp_path):
    import json
    repo = tmp_path / "Website"
    _init_repo(repo)
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="ws", display_name="WS"))
    RepositoryService(conn).register_repository(
        "ws", RepositoryRegistration(repository_id="Website", local_path=str(repo))
    )

    result = WorkspaceService(conn).scan_inventory("ws", "Website")

    assert result["files"] == 3
    rows = {r["path"]: r["anchors_json"] for r in conn.execute(
        "SELECT path, anchors_json FROM repository_files WHERE repository_id = ?", ("Website",)
    ).fetchall()}
    assert set(rows) == {"build.py", "src/app.js", "README.md"}
    # Markdown headings become GitHub-style slugs; non-markdown files carry no anchors.
    assert set(json.loads(rows["README.md"])) == {"overview", "install-steps"}
    assert json.loads(rows["build.py"]) == []
    meta = conn.execute(
        "SELECT head_sha FROM repository_inventory_meta WHERE repository_id = ?", ("Website",)
    ).fetchone()
    assert meta["head_sha"]


# Shared parity fixture — the SAME constants are asserted against the gate's
# github_heading_slugs in Phase B Task B2. Identical results ⇒ anchor rules agree.
PARITY_MD = "# Getting Started\n\n## API Reference\n\n## API Reference\n"
PARITY_SLUGS = {"getting-started", "api-reference", "api-reference-1"}


def test_heading_slugs_match_shared_parity_fixture():
    from architectural_knowledge_db.services.markdown_anchors import heading_slugs
    assert heading_slugs(PARITY_MD) == PARITY_SLUGS
