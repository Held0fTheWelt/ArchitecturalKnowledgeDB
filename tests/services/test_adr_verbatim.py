from __future__ import annotations

import subprocess
from pathlib import Path

from architectural_knowledge_db.services.import_export import ImportExportService
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.models import ProjectUpsert

ADR = "# ADR-0007: Use X\n\n## Status\n\nAccepted\n\n## Context\n\nBecause.   \n\n## Decision\n\nDo X.\n"


def test_adr_ingest_export_is_byte_exact(conn, tmp_path):
    # repo_relative_key() needs a real ".git" marker (see test_export_canon.py).
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="a", display_name="A"))
    adr_dir = tmp_path / "docs" / "ADR" / "Plugins"
    adr_dir.mkdir(parents=True)
    (adr_dir / "ADR-0007-use-x.md").write_bytes(ADR.encode("utf-8"))
    ies = ImportExportService(conn)
    ies.import_adrs("a", tmp_path / "docs" / "ADR")
    out = tmp_path / "out"
    ies.export_canon("a", out)
    written = (out / "docs" / "ADR" / "Plugins" / "ADR-0007-use-x.md").read_bytes()
    assert written == ADR.encode("utf-8")             # trailing spaces + newlines preserved
