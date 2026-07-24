from __future__ import annotations

import subprocess
from pathlib import Path

from architectural_knowledge_db.models import AdrInput, ProjectUpsert
from architectural_knowledge_db.services.export_targets import ExportTargetsService
from architectural_knowledge_db.services.import_export import ImportExportService
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.projects import ProjectService

# NOTE: the plan text imagines an `AkdbApp` facade with `upsert_sad()` /
# `deferred_export()` methods. That class does not exist in this codebase (see
# .superpowers/sdd/progress.md "Adaptation note"). The REAL single write choke
# point is `KnowledgeService._upsert_item()`; these tests exercise it directly
# (single-mutation case) and via the real bulk entry point `import_documents`
# (batched case), which is the behavioral intent of Plan A Task 2.2.


def _project_with_target(conn, tmp_path, pid="p"):
    ProjectService(conn).upsert_project(ProjectUpsert(project_id=pid, display_name="P"))
    dest = tmp_path / "mirror"
    ExportTargetsService(conn).register_target(
        pid, "m", repository_id="Git", dest_root=str(dest), layout="arc42-canon",
        content_kinds=["sad", "adr", "uml"],
    )
    return dest


def test_single_upsert_autoflushes_to_mirror(conn, tmp_path):
    dest = _project_with_target(conn, tmp_path)
    KnowledgeService(conn).upsert_adr(
        "p",
        AdrInput(
            adr_id="ADR-0001",
            title="Use X",
            metadata={
                "repo_source_key": "docs/ADR/Plugins/ADR-0001-use-x.md",
                "body_text": "# ADR-0001: Use X\n\nv2\n",
                "body_encoding": "utf-8",
            },
        ),
    )
    assert not (dest / "ADR").exists()
    conn.commit()
    mirrored = dest / "ADR" / "Plugins" / "ADR-0001-use-x.md"
    assert mirrored.exists()
    assert mirrored.read_bytes() == b"# ADR-0001: Use X\n\nv2\n"


def test_bulk_import_flushes_once(conn, tmp_path, monkeypatch):
    dest = _project_with_target(conn, tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    tree = tmp_path / "docs" / "architecture" / "plugins"
    for i in range(5):
        (tree / f"P{i}").mkdir(parents=True)
        (tree / f"P{i}" / "architecture.md").write_text(
            f"# P{i}\n\n## 1. Intro\n\nbody\n", encoding="utf-8", newline=""
        )

    calls = {"n": 0}
    orig = ImportExportService.export_incremental

    def counting(self, *a, **k):
        calls["n"] += 1
        return orig(self, *a, **k)

    monkeypatch.setattr(ImportExportService, "export_incremental", counting)

    ImportExportService(conn).import_documents("p", tmp_path / "docs" / "architecture", include=["**/*"])

    assert calls["n"] == 0
    conn.commit()
    assert calls["n"] == 1          # one coalesced flush, not five
    for i in range(5):
        assert (dest / "plugins" / f"P{i}" / "architecture.md").exists()


def test_deferred_export_context_manager_coalesces_across_calls(conn, tmp_path):
    from architectural_knowledge_db.services.export_flush import deferred_export

    dest = _project_with_target(conn, tmp_path)
    with deferred_export(conn):
        for i in range(3):
            KnowledgeService(conn).upsert_adr(
                "p",
                AdrInput(
                    adr_id=f"ADR-000{i}",
                    title=f"D{i}",
                    metadata={
                        "repo_source_key": f"docs/ADR/Plugins/ADR-000{i}-d.md",
                        "body_text": f"# ADR-000{i}\n",
                        "body_encoding": "utf-8",
                    },
                ),
            )
        # Not yet flushed -- still inside the deferred block.
        assert not (dest / "ADR").exists()
    # The context coalesces work, but the filesystem projection waits until
    # the authoritative database transaction commits.
    assert not (dest / "ADR").exists()
    conn.commit()
    for i in range(3):
        assert (dest / "ADR" / "Plugins" / f"ADR-000{i}-d.md").exists()


def test_rollback_discards_pending_export(conn, tmp_path):
    dest = _project_with_target(conn, tmp_path)
    conn.commit()

    KnowledgeService(conn).upsert_adr(
        "p",
        AdrInput(
            adr_id="ADR-ROLLBACK-0001",
            title="Never mirror rolled-back state",
            metadata={
                "repo_source_key": "docs/ADR/Plugins/ADR-ROLLBACK-0001.md",
                "body_text": "# Rolled back\n",
                "body_encoding": "utf-8",
            },
        ),
    )
    conn.rollback()

    assert not (dest / "ADR" / "Plugins" / "ADR-ROLLBACK-0001.md").exists()
    assert not KnowledgeService(conn).list_adrs("p", limit=100)
