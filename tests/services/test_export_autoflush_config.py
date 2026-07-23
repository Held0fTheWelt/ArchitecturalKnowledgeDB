from __future__ import annotations

from architectural_knowledge_db.models import AdrInput, ProjectUpsert
from architectural_knowledge_db.services.export_targets import ExportTargetsService
from architectural_knowledge_db.services.import_export import ImportExportService
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.projects import ProjectService


def test_auto_export_false_marks_dirty_but_does_not_flush(conn, tmp_path):
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="p", display_name="P"))
    dest = tmp_path / "mirror"
    ExportTargetsService(conn).register_target(
        "p", "m", repository_id="Git", dest_root=str(dest), layout="arc42-canon",
        content_kinds=["adr"], auto_export=False,
    )
    KnowledgeService(conn).upsert_adr(
        "p",
        AdrInput(
            adr_id="ADR-0001",
            title="Use X",
            metadata={
                "repo_source_key": "docs/ADR/Plugins/ADR-0001-use-x.md",
                "body_text": "# ADR-0001: Use X\n\nv1\n",
                "body_encoding": "utf-8",
            },
        ),
    )
    mirrored = dest / "ADR" / "Plugins" / "ADR-0001-use-x.md"
    assert not mirrored.exists()                                    # not auto-flushed
    assert ExportTargetsService(conn).peek_dirty("p", "m") != []    # but marked dirty

    ImportExportService(conn).export_incremental("p", "m")          # explicit flush
    assert mirrored.exists()
