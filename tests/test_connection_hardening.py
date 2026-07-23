from architectural_knowledge_db.db.connection import connect


def test_connect_sets_busy_timeout_and_synchronous(tmp_path):
    conn = connect(tmp_path / "x.sqlite")
    try:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 1  # NORMAL == 1
    finally:
        conn.close()
