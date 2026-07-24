from __future__ import annotations

import subprocess
from pathlib import Path

from architectural_knowledge_db.models import ProjectUpsert, RepositoryRegistration
from architectural_knowledge_db.services.export_targets import ExportTargetsService
from architectural_knowledge_db.services.import_export import ImportExportService
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.services.repositories import RepositoryService
from tests.services.test_obsidian_expected_files import _seed_min_project


def test_obsidian_sync_then_verify_is_clean(conn, tmp_path):
    pid = _seed_min_project(conn)
    dest = tmp_path / "TTD"
    ExportTargetsService(conn).register_target(
        pid,
        "vault",
        repository_id="Git",
        dest_root=str(dest),
        layout="obsidian-vault",
        content_kinds=["sad", "adr", "uml_diagram"],
        auto_export=False,
    )
    svc = ImportExportService(conn)
    svc.export_sync(pid, "vault")
    # Must be the derived Obsidian projection (not the arc42 body_text mirror).
    notes = list(dest.rglob("*.md"))
    assert notes, "obsidian sync must write notes"
    assert any("MOC" in p.name for p in notes)
    assert any(p.read_text(encoding="utf-8").startswith("---\n") for p in notes)
    assert not (dest / "docs").exists(), "must not write arc42-canon path tree"
    res = svc.verify_export(pid, "vault")
    assert res["mismatched"] == [] and res["missing"] == [] and res["extra"] == []
    # Incremental is a full namespace re-render in v1 and stays clean.
    svc.export_incremental(pid, "vault")
    res2 = svc.verify_export(pid, "vault")
    assert res2["mismatched"] == [] and res2["missing"] == [] and res2["extra"] == []


def test_non_obsidian_layout_never_touches_renderer(conn, tmp_path, monkeypatch):
    import architectural_knowledge_db.services.obsidian_export as ox

    monkeypatch.setattr(
        ox,
        "expected_vault_files",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("renderer must not run")),
    )

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="p2", display_name="P2"))
    RepositoryService(conn).register_repository(
        "p2",
        RepositoryRegistration(repository_id="Git", local_path=str(tmp_path)),
    )
    tree = tmp_path / "docs" / "architecture" / "plugins" / "X"
    tree.mkdir(parents=True)
    (tree / "architecture.md").write_text("# X\n\n## 1. Intro\n\nbody\n", encoding="utf-8", newline="")
    ImportExportService(conn).import_documents(
        "p2", tmp_path / "docs" / "architecture", include=["**/*"]
    )
    dest = tmp_path / "mirror"
    ExportTargetsService(conn).register_target(
        "p2",
        "m",
        repository_id="Git",
        dest_root=str(dest),
        layout="arc42-canon",
        content_kinds=["sad"],
        auto_export=False,
    )
    svc = ImportExportService(conn)
    svc.export_sync("p2", "m")
    res = svc.verify_export("p2", "m")
    assert res["mismatched"] == [] and res["missing"] == [] and res["extra"] == []
