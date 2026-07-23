from __future__ import annotations

import subprocess
from pathlib import Path

from architectural_knowledge_db.services.import_export import ImportExportService
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.models import ProjectUpsert

FIXTURES = {
    "docs/architecture/plugins/Demo/architecture.md": "# Demo\n\n## 1. Goals\n\nBody.   \n",
    "docs/architecture/START-HERE.md": "# Start Here\n\nNav.\n",
    "docs/architecture/contracts/x.md": "# X\n",
    "UML/Plugins/Demo/components/c4-context.puml": "@startuml\n@enduml\n",
    "UML/Plugins/Demo/components/c4-context.md": "```plantuml\n@startuml\n@enduml\n```\n",
}


def _seed(root: Path):
    # repo_relative_key() (import_export.py) walks up looking for a ".git" marker
    # to compute the repo-relative path; a real git repo makes this fixture behave
    # like the real PluginProject checkout instead of falling back to an absolute
    # path (which would defeat the whole-tree mirror layout under test).
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    for rel, text in FIXTURES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="")


def test_export_canon_reproduces_repo_tree_byte_for_byte(conn, tmp_path):
    src = tmp_path / "repo"
    _seed(src)
    ProjectService(conn).upsert_project(
        ProjectUpsert(project_id="canon", display_name="Canon")
    )
    svc = ImportExportService(conn)
    svc.import_documents("canon", src / "docs" / "architecture", include=["**/*"])
    svc.import_documents("canon", src / "UML", include=["**/*"])

    out = tmp_path / "export"
    result = svc.export_canon("canon", out)

    assert result["exported"] == len(FIXTURES)
    for rel, text in FIXTURES.items():
        target = out / rel
        assert target.is_file(), f"missing {rel}"
        assert target.read_text(encoding="utf-8") == text, f"bytes drift for {rel}"
    manifest = out / ".akdb-canon-export.json"
    assert manifest.is_file()
