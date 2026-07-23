from __future__ import annotations

from tests.conftest import catalog_table_names


def test_009_creates_export_tables(conn):
    names = catalog_table_names(conn)
    assert "export_targets" in names
    assert "export_dirty" in names
