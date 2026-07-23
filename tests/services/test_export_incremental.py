from __future__ import annotations

import subprocess
from pathlib import Path

from architectural_knowledge_db.services.import_export import ImportExportService
from architectural_knowledge_db.services.export_targets import ExportTargetsService
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.models import ProjectUpsert


def _setup(conn, tmp_path):
    # repo_relative_key() needs a real ".git" marker to compute repo-relative
    # paths (else it falls back to an absolute path) -- see test_export_canon.py.
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="p", display_name="P"))
    tree = tmp_path / "docs" / "architecture"
    (tree / "plugins" / "X").mkdir(parents=True)
    (tree / "plugins" / "X" / "architecture.md").write_text(
        "# X SAD\n\n## 1. Intro\n\nbody\n", encoding="utf-8", newline=""
    )
    (tree / "plugins" / "X" / "product-facts.yml").write_text(
        "display_name: X\n", encoding="utf-8", newline=""
    )
    ImportExportService(conn).import_documents("p", tree, include=["**/*"])
    dest = tmp_path / "mirror"
    ExportTargetsService(conn).register_target(
        "p", "m", repository_id="Git", dest_root=str(dest), layout="arc42-canon",
        content_kinds=["sad", "sad_section", "sad_decision", "uml", "adr"])
    return dest


def test_incremental_writes_only_dirty_items(conn, tmp_path):
    dest = _setup(conn, tmp_path)
    ies = ImportExportService(conn)
    ExportTargetsService(conn).mark_dirty(
        "p", "sad", "docs/architecture/plugins/X/architecture.md", "upsert", target_id="m")
    res = ies.export_incremental("p", "m")
    written = {Path(w).name for w in res["written"]}
    assert "architecture.md" in written
    # class-H is never mirrored
    assert not (Path(dest) / "plugins" / "X" / "product-facts.yml").exists()
    # the mirrored SAD is byte-identical to what the DB stores (verbatim body_text)
    assert (Path(dest) / "plugins" / "X" / "architecture.md").read_bytes() == \
           b"# X SAD\n\n## 1. Intro\n\nbody\n"


def test_incremental_deletes_removed_items(conn, tmp_path):
    dest = _setup(conn, tmp_path)
    ies = ImportExportService(conn)
    ExportTargetsService(conn).mark_dirty("p", "sad", "docs/architecture/plugins/X/architecture.md", "upsert", "m")
    ies.export_incremental("p", "m")
    assert (Path(dest) / "plugins" / "X" / "architecture.md").exists()
    ExportTargetsService(conn).mark_dirty("p", "sad", "docs/architecture/plugins/X/architecture.md", "delete", "m")
    res = ies.export_incremental("p", "m")
    assert not (Path(dest) / "plugins" / "X" / "architecture.md").exists()
    assert any("architecture.md" in d for d in res["deleted"])


def test_mirror_path_maps_uml_and_adr_roots(conn, tmp_path):
    from architectural_knowledge_db.services.import_export import _mirror_path

    dest = tmp_path / "mirror"
    assert _mirror_path(dest, "docs/architecture/plugins/X/architecture.md") == \
        dest / "plugins" / "X" / "architecture.md"
    assert _mirror_path(dest, "UML/Plugins/X/c.puml") == dest / "UML" / "Plugins" / "X" / "c.puml"
    assert _mirror_path(dest, "docs/ADR/Plugins/ADR-0001-x.md") == dest / "ADR" / "Plugins" / "ADR-0001-x.md"
    assert _mirror_path(dest, "docs/architecture/plugins/X/product-facts.yml") is None
    assert _mirror_path(dest, "README.md") is None
