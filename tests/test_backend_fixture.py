def test_conn_fixture_is_usable(conn):
    # Runs once per backend param (sqlite always; postgres when AKDB_TEST_DB_URL is set).
    assert conn.execute("SELECT 1 AS ok").fetchone()["ok"] == 1
