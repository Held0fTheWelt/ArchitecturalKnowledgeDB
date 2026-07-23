from __future__ import annotations

import subprocess
from pathlib import Path

from architectural_knowledge_db.services.export_targets import ExportTargetsService
from architectural_knowledge_db.services.import_export import ImportExportService
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.models import ProjectUpsert

ADR = "# ADR-0007: Use X\n\n## Status\n\nAccepted\n\n## Context\n\nBecause.   \n\n## Decision\n\nDo X.\n"


def test_adr_flows_into_target_mirror(conn, tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="a", display_name="A"))
    adr_dir = tmp_path / "docs" / "ADR" / "Plugins"
    adr_dir.mkdir(parents=True)
    (adr_dir / "ADR-0007-use-x.md").write_bytes(ADR.encode("utf-8"))
    ies = ImportExportService(conn)
    ies.import_adrs("a", tmp_path / "docs" / "ADR")

    dest = tmp_path / "mirror"
    ExportTargetsService(conn).register_target(
        "a", "m", repository_id="Git", dest_root=str(dest), layout="arc42-canon",
        content_kinds=["sad", "uml", "adr"], auto_export=False,
    )
    ies.export_sync("a", "m")

    mirrored = dest / "ADR" / "Plugins" / "ADR-0007-use-x.md"
    assert mirrored.exists()
    assert mirrored.read_bytes() == ADR.encode("utf-8")
    r = ies.verify_export("a", "m")
    assert r["mismatched"] == [] and r["missing"] == [] and r["extra"] == []
