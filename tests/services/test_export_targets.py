from __future__ import annotations

import pytest

from architectural_knowledge_db.models import ProjectUpsert, RepositoryRegistration
from architectural_knowledge_db.services.export_targets import ExportTargetsService
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.services.repositories import RepositoryService


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


def test_register_normalizes_backslashes_to_posix_for_cross_platform_dest_root(conn):
    # A target registered on Windows (typer.Path str() uses "\\") must still resolve
    # correctly when the freshness gate / CI later runs `Path(dest_root) / ...` on
    # Linux, where "\\" is not a path separator.
    pid = _proj(conn)
    svc = ExportTargetsService(conn)
    svc.register_target(pid, "t", repository_id="Git",
                        dest_root="docs\\architecture\\_generated", layout="arc42-canon",
                        content_kinds=["sad"])
    assert svc.get_target(pid, "t")["dest_root"] == "docs/architecture/_generated"


def test_relative_destination_resolves_against_registered_repository(conn, tmp_path):
    pid = _proj(conn)
    repository_root = tmp_path / "Git"
    repository_root.mkdir()
    RepositoryService(conn).register_repository(
        pid,
        RepositoryRegistration(repository_id="ttd-main", local_path=str(repository_root)),
    )
    svc = ExportTargetsService(conn)
    svc.register_target(
        pid,
        "t",
        repository_id="ttd-main",
        dest_root="docs/architecture/_generated",
        layout="arc42-canon",
        content_kinds=["sad"],
    )

    assert svc.resolve_dest_root(pid, "t") == repository_root / "docs/architecture/_generated"


def test_absolute_destination_remains_absolute(conn, tmp_path):
    pid = _proj(conn)
    destination = tmp_path / "mirror"
    svc = ExportTargetsService(conn)
    svc.register_target(
        pid,
        "t",
        repository_id="Git",
        dest_root=str(destination),
        layout="arc42-canon",
        content_kinds=["sad"],
    )

    assert svc.resolve_dest_root(pid, "t") == destination


@pytest.mark.parametrize("destination", ["", ".", "..", "../mirror", "docs/../mirror"])
def test_unsafe_destination_is_rejected(conn, destination):
    pid = _proj(conn)

    with pytest.raises(ValueError):
        ExportTargetsService(conn).register_target(
            pid,
            "t",
            repository_id="Git",
            dest_root=destination,
            layout="arc42-canon",
            content_kinds=["sad"],
        )


def test_filesystem_root_destination_is_rejected(conn):
    pid = _proj(conn)

    with pytest.raises(ValueError, match="filesystem root"):
        ExportTargetsService(conn).register_target(
            pid,
            "t",
            repository_id="Git",
            dest_root="/",
            layout="arc42-canon",
            content_kinds=["sad"],
        )


def test_relative_destination_requires_registered_repository(conn):
    pid = _proj(conn)
    svc = ExportTargetsService(conn)
    svc.register_target(
        pid,
        "t",
        repository_id="missing",
        dest_root="docs/architecture/_generated",
        layout="arc42-canon",
        content_kinds=["sad"],
    )

    with pytest.raises(ValueError, match="requires registered repository"):
        svc.resolve_dest_root(pid, "t")


def test_missing_registered_path_uses_matching_checkout_remote(
    conn, tmp_path, monkeypatch
):
    pid = _proj(conn)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    RepositoryService(conn).register_repository(
        pid,
        RepositoryRegistration(
            repository_id="ttd-main",
            local_path=str(tmp_path / "missing"),
            remote_url_sanitized="https://example.test/ttd.git",
        ),
    )
    svc = ExportTargetsService(conn)
    svc.register_target(
        pid,
        "t",
        repository_id="ttd-main",
        dest_root="docs/architecture/_generated",
        layout="arc42-canon",
        content_kinds=["sad"],
    )
    monkeypatch.chdir(checkout)
    monkeypatch.setattr(
        "architectural_knowledge_db.services.export_targets.detect_remote_url",
        lambda _path: "https://example.test/ttd.git",
    )

    assert svc.resolve_dest_root(pid, "t") == checkout / "docs/architecture/_generated"


def test_missing_registered_path_rejects_unrelated_checkout(
    conn, tmp_path, monkeypatch
):
    pid = _proj(conn)
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    RepositoryService(conn).register_repository(
        pid,
        RepositoryRegistration(
            repository_id="ttd-main",
            local_path=str(tmp_path / "missing"),
            remote_url_sanitized="https://example.test/ttd.git",
        ),
    )
    svc = ExportTargetsService(conn)
    svc.register_target(
        pid,
        "t",
        repository_id="ttd-main",
        dest_root="docs/architecture/_generated",
        layout="arc42-canon",
        content_kinds=["sad"],
    )
    monkeypatch.chdir(checkout)
    monkeypatch.setattr(
        "architectural_knowledge_db.services.export_targets.detect_remote_url",
        lambda _path: "https://example.test/akdb.git",
    )

    with pytest.raises(ValueError, match="does not match its remote"):
        svc.resolve_dest_root(pid, "t")


def test_set_enabled(conn):
    pid = _proj(conn)
    svc = ExportTargetsService(conn)
    svc.register_target(pid, "t", repository_id="Git", dest_root="a", layout="l", content_kinds=["sad"])
    svc.set_enabled(pid, "t", False)
    assert svc.get_target(pid, "t")["enabled"] is False
    assert svc.list_targets(pid, enabled_only=True) == []
