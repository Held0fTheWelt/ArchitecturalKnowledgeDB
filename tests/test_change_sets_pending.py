from tests.test_change_sets_service import _spec, IMPACT
from architectural_knowledge_db.services.change_sets import ChangeSetService
from architectural_knowledge_db.services.export_targets import ExportTargetsService
from architectural_knowledge_db.services.import_export import ImportExportService


def test_render_pending_one_file_per_open_spec(conn):
    s = _spec(conn)
    cs = ChangeSetService(conn)
    cs.ingest_impact("p", s, IMPACT)
    out = cs.render_pending("p", "docs/architecture/_generated")
    assert "docs/architecture/_generated/_pending/S1.md" in out
    assert "GENERATED" in out["docs/architecture/_generated/_pending/S1.md"]


def test_render_pending_empty_when_all_done(conn):
    s = _spec(conn)
    cs = ChangeSetService(conn)
    cs.ingest_impact("p", s, IMPACT)
    for it in cs.open_work_orders("p")[0]["items"]:
        cs.set_item_state("p", it["id"], "done")
    assert cs.render_pending("p", "docs/architecture/_generated") == {}


def test_verify_export_clean_with_open_pending_view(conn, tmp_path):
    s = _spec(conn)
    cs = ChangeSetService(conn)
    cs.ingest_impact("p", s, IMPACT)
    dest = tmp_path / "mirror"
    ExportTargetsService(conn).register_target(
        "p",
        "m",
        repository_id="Git",
        dest_root=str(dest),
        layout="arc42-canon",
        content_kinds=["specs"],
        auto_export=False,
    )
    ies = ImportExportService(conn)
    ies.export_sync("p", "m")

    pending_file = dest / "_pending" / "S1.md"
    assert pending_file.is_file()
    assert "GENERATED" in pending_file.read_text(encoding="utf-8")

    result = ies.verify_export("p", "m")
    assert result["mismatched"] == [] and result["missing"] == [] and result["extra"] == []


def test_export_sync_prunes_pending_file_once_spec_closes(conn, tmp_path):
    s = _spec(conn)
    cs = ChangeSetService(conn)
    cs.ingest_impact("p", s, IMPACT)
    dest = tmp_path / "mirror"
    ExportTargetsService(conn).register_target(
        "p",
        "m",
        repository_id="Git",
        dest_root=str(dest),
        layout="arc42-canon",
        content_kinds=["specs"],
        auto_export=False,
    )
    ies = ImportExportService(conn)
    ies.export_sync("p", "m")
    pending_file = dest / "_pending" / "S1.md"
    assert pending_file.is_file()

    for it in cs.open_work_orders("p")[0]["items"]:
        cs.set_item_state("p", it["id"], "done")
    ies.export_sync("p", "m")

    assert not pending_file.exists()
    result = ies.verify_export("p", "m")
    assert result["mismatched"] == [] and result["missing"] == [] and result["extra"] == []
