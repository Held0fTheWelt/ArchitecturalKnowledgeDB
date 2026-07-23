from __future__ import annotations


def _columns(conn, table: str) -> set[str]:
    if getattr(conn, "is_postgres", False):
        rows = conn.execute(
            "SELECT column_name AS name FROM information_schema.columns WHERE table_name = ?",
            (table,),
        ).fetchall()
        return {r["name"] for r in rows}
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def test_repository_files_table_exists(conn):
    assert {"repository_id", "path", "anchors_json"} <= _columns(conn, "repository_files")


def test_repository_inventory_meta_table_exists(conn):
    assert {"repository_id", "head_sha", "scanned_at"} <= _columns(conn, "repository_inventory_meta")
