from __future__ import annotations

from architectural_knowledge_db.services.export_targets import ExportTargetsService
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.models import ProjectUpsert


def _proj(conn, pid="et-test"):
    ProjectService(conn).upsert_project(ProjectUpsert(project_id=pid, display_name="ET"))
    return pid


def test_register_and_get_roundtrips_content_kinds(conn):
    pid = _proj(conn)
    svc = ExportTargetsService(conn)
    svc.register_target(pid, "ttd-canon", repository_id="Git",
                        dest_root="docs/architecture/_generated", layout="arc42-canon",
                        content_kinds=["sad", "uml", "adr"])
    t = svc.get_target(pid, "ttd-canon")
    assert t["repository_id"] == "Git"
    assert t["content_kinds"] == ["sad", "uml", "adr"]      # list, not raw JSON text
    assert t["auto_export"] is True and t["enabled"] is True


def test_register_is_idempotent_upsert(conn):
    pid = _proj(conn)
    svc = ExportTargetsService(conn)
    svc.register_target(pid, "t", repository_id="Git", dest_root="a", layout="l", content_kinds=["sad"])
    svc.register_target(pid, "t", repository_id="Git", dest_root="b", layout="l", content_kinds=["sad"])
    assert svc.get_target(pid, "t")["dest_root"] == "b"
    assert len(svc.list_targets(pid)) == 1


def test_dirty_mark_drain_is_fifo_and_clears(conn):
    pid = _proj(conn)
    svc = ExportTargetsService(conn)
    svc.mark_dirty(pid, "sad", "docs/architecture/plugins/X/architecture.md", "upsert", target_id="ttd-canon")
    svc.mark_dirty(pid, "uml", "UML/Plugins/X/c.puml", "upsert", target_id="ttd-canon")
    drained = svc.drain_dirty(pid, "ttd-canon")
    assert [d["item_ref"] for d in drained] == [
        "docs/architecture/plugins/X/architecture.md", "UML/Plugins/X/c.puml"]
    assert svc.peek_dirty(pid, "ttd-canon") == []          # drain cleared them


def test_drain_includes_untargeted_rows(conn):
    pid = _proj(conn)
    svc = ExportTargetsService(conn)
    svc.mark_dirty(pid, "sad", "r1", "upsert", target_id=None)   # applies to all targets
    assert [d["item_ref"] for d in svc.drain_dirty(pid, "ttd-canon")] == ["r1"]


def test_set_enabled(conn):
    pid = _proj(conn)
    svc = ExportTargetsService(conn)
    svc.register_target(pid, "t", repository_id="Git", dest_root="a", layout="l", content_kinds=["sad"])
    svc.set_enabled(pid, "t", False)
    assert svc.get_target(pid, "t")["enabled"] is False
    assert svc.list_targets(pid, enabled_only=True) == []
