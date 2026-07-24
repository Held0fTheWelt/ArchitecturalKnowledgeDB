from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from architectural_knowledge_db.services.export_targets import ExportTargetsService
from architectural_knowledge_db.services.import_export import ImportExportService
from architectural_knowledge_db.services.repositories import RepositoryService
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.models import ProjectUpsert, RepositoryRegistration

FIXTURES = {
    "docs/architecture/plugins/X/architecture.md": (
        "# X SAD\n\n"
        "[Descriptor](../../../../AIPlugins/X/X.uplugin)\n\n"
        "[Workspace sibling](../../../../../Documentation/X/README.md)\n\n"
        "[UML](../../../../UML/Plugins/X/TRACEABILITY.md#models)\n\n"
        "[Peer](../Y/architecture.md)\n\n"
        "[Root-style](docs/ADR/README.md)\n\n"
        "[External](https://example.test/reference)\n\n"
        "```markdown\n"
        "[Example](../../../../AIPlugins/Example/Example.uplugin)\n"
        "```\n"
    ),
}


@pytest.fixture
def import_fixture():
    def _make(conn, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        ProjectService(conn).upsert_project(ProjectUpsert(project_id="p", display_name="P"))
        for rel, text in FIXTURES.items():
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8", newline="")
        ImportExportService(conn).import_documents("p", tmp_path / "docs" / "architecture", include=["**/*"])
        RepositoryService(conn).register_repository(
            "p",
            RepositoryRegistration(repository_id="Git", local_path=str(tmp_path)),
        )
        dest = tmp_path / "docs" / "architecture" / "_generated"
        ExportTargetsService(conn).register_target(
            "p",
            "m",
            repository_id="Git",
            dest_root="docs/architecture/_generated",
            layout="arc42-canon",
            content_kinds=["sad"], auto_export=False,
        )
        return dest, "p"

    return _make


def test_sync_makes_verify_clean_and_prunes_stray(conn, tmp_path, import_fixture):
    dest, pid = import_fixture(conn, tmp_path)
    ies = ImportExportService(conn)
    Path(dest).mkdir(parents=True, exist_ok=True)
    (Path(dest) / "stray.md").write_text("x\n", encoding="utf-8", newline="")
    ies.export_sync(pid, "m")
    r = ies.verify_export(pid, "m")
    assert r["mismatched"] == [] and r["missing"] == [] and r["extra"] == []
    assert not (Path(dest) / "stray.md").exists()
    assert ExportTargetsService(conn).peek_dirty(pid, "m") == []


def test_sync_rebases_links_from_repository_location_to_mirror_location(
    conn, tmp_path, import_fixture
):
    dest, pid = import_fixture(conn, tmp_path)

    ImportExportService(conn).export_sync(pid, "m")

    rendered = (Path(dest) / "plugins" / "X" / "architecture.md").read_text(
        encoding="utf-8"
    )
    assert "[Descriptor](../../../../../AIPlugins/X/X.uplugin)" in rendered
    assert "[Workspace sibling](../../../../../../Documentation/X/README.md)" in rendered
    assert "[UML](../../UML/Plugins/X/TRACEABILITY.md#models)" in rendered
    assert "[Peer](../Y/architecture.md)" in rendered
    assert "[Root-style](docs/ADR/README.md)" in rendered
    assert "[External](https://example.test/reference)" in rendered
    assert "[Example](../../../../AIPlugins/Example/Example.uplugin)" in rendered


def test_incremental_and_full_sync_use_the_same_rebased_projection(
    conn, tmp_path, import_fixture
):
    dest, pid = import_fixture(conn, tmp_path)
    service = ImportExportService(conn)
    targets = ExportTargetsService(conn)
    targets.mark_dirty(
        pid,
        "sad",
        "docs/architecture/plugins/X/architecture.md",
        target_id="m",
    )

    service.export_incremental(pid, "m")
    incremental = (Path(dest) / "plugins" / "X" / "architecture.md").read_bytes()
    service.export_sync(pid, "m")
    synchronized = (Path(dest) / "plugins" / "X" / "architecture.md").read_bytes()

    assert incremental == synchronized
    assert service.verify_export(pid, "m")["mismatched"] == []


def test_sync_rejects_multiple_canonical_body_owners(conn, tmp_path, import_fixture):
    _, pid = import_fixture(conn, tmp_path)
    owner = conn.execute(
        """
        SELECT space_id, metadata_json
        FROM knowledge_items
        WHERE project_id = ?
          AND json_extract(metadata_json, '$.repo_source_key') =
              'docs/architecture/plugins/X/architecture.md'
          AND json_extract(metadata_json, '$.body_text') IS NOT NULL
        """,
        (pid,),
    ).fetchone()
    assert owner is not None
    metadata = json.loads(owner["metadata_json"])
    conn.execute(
        """
        INSERT INTO knowledge_items (
            item_uid, project_id, space_id, item_type, local_id, title,
            authority_level, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"{pid}:document:duplicate-owner",
            pid,
            owner["space_id"],
            "document",
            "duplicate-owner",
            "Duplicate owner",
            "project_note",
            json.dumps(metadata),
        ),
    )

    with pytest.raises(
        ValueError,
        match="Multiple canonical body_text owners.*docs/architecture/plugins/X/architecture.md",
    ):
        ImportExportService(conn).export_sync(pid, "m")
