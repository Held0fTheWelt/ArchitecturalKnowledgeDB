from __future__ import annotations

from tests.services.test_obsidian_expected_files import _seed_min_project


def test_moc_has_static_list_and_dataview_block(conn):
    pid = _seed_min_project(conn)
    from architectural_knowledge_db.services.obsidian_export import expected_vault_files

    files = expected_vault_files(conn, pid, "TTD")
    moc = next(v for k, v in files.items() if "MOC" in k).decode()
    assert "[[" in moc  # static list with real wikilinks
    assert "```dataview" in moc  # interactive block present
    assert "WHERE" in moc.upper()
