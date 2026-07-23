def test_api_migrates_once_at_startup_not_per_request(tmp_path, monkeypatch):
    monkeypatch.setenv("AKDB_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("AKDB_DATABASE_PATH", str(tmp_path / "api.sqlite"))

    import architectural_knowledge_db.db.connection as connection_mod
    calls = {"n": 0}
    original = connection_mod.run_migrations

    def counting(conn):
        calls["n"] += 1
        return original(conn)

    monkeypatch.setattr(connection_mod, "run_migrations", counting)

    from fastapi.testclient import TestClient
    from architectural_knowledge_db.api.app import create_app

    app = create_app()            # migrations run exactly once here
    client = TestClient(app)
    for _ in range(3):
        assert client.get("/health").status_code == 200

    assert calls["n"] == 1        # startup only — not once per request
