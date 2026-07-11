from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path

from architectural_knowledge_db.db.connection import initialize_database
from architectural_knowledge_db.models import AdrInput, ProjectUpsert
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.mcp_stdio import StdioServer, configure_stdio_utf8, serve


def _seed(tmp_path: Path):
    conn = initialize_database(tmp_path / "mcp.sqlite")
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="p", display_name="P"))
    KnowledgeService(conn).upsert_adr(
        "p",
        AdrInput(adr_id="ADR-0001", title="SQLite first", status="accepted",
                 decision_md="SQLite is the primary local state."),
    )
    conn.commit()
    return conn


def test_initialize_lists_tools_and_calls_search(tmp_path):
    server = StdioServer(_seed(tmp_path), default_project="p")

    init = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                          "params": {"protocolVersion": "2025-06-18"}})
    assert init["result"]["serverInfo"]["name"] == "akdb"
    assert "tools" in init["result"]["capabilities"]
    assert init["result"]["protocolVersion"] == "2025-06-18"

    listed = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = listed["result"]["tools"]
    assert any(t["name"] == "architectural_knowledge_db_search" for t in tools)
    assert all("inputSchema" in t for t in tools)

    called = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                            "params": {"name": "architectural_knowledge_db_search",
                                       "arguments": {"query": "SQLite"}}})
    assert "ADR-0001" in called["result"]["content"][0]["text"]


def test_notification_returns_none(tmp_path):
    server = StdioServer(_seed(tmp_path), default_project="p")
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_unknown_method_is_jsonrpc_error(tmp_path):
    server = StdioServer(_seed(tmp_path))
    resp = server.handle({"jsonrpc": "2.0", "id": 9, "method": "no/such"})
    assert resp["error"]["code"] == -32601


def test_tool_error_is_returned_as_iserror(tmp_path):
    server = StdioServer(_seed(tmp_path), default_project="p")
    resp = server.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                          "params": {"name": "does_not_exist", "arguments": {}}})
    assert resp["result"]["isError"] is True


def test_default_project_is_injected(tmp_path):
    server = StdioServer(_seed(tmp_path), default_project="p")
    resp = server.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                          "params": {"name": "architectural_knowledge_db_search",
                                     "arguments": {"query": "SQLite"}}})  # no project_id supplied
    assert "isError" not in resp["result"]


def test_tool_call_commits_successful_mutation(tmp_path):
    db_path = tmp_path / "mcp.sqlite"
    conn = initialize_database(db_path)
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="p", display_name="P"))
    conn.commit()
    server = StdioServer(conn)

    resp = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "akdb_propose_adr",
                "arguments": {"project_id": "p", "adr_id": "ADR-0099", "title": "Committed"},
            },
        }
    )

    assert "isError" not in resp["result"]
    probe = sqlite3.connect(db_path)
    try:
        count = probe.execute("SELECT COUNT(*) FROM adrs WHERE adr_id = 'ADR-0099'").fetchone()[0]
    finally:
        probe.close()
    assert count == 1


def test_serve_loop_emits_one_line_per_request(tmp_path):
    conn = _seed(tmp_path)
    stdin = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n"
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n"
    )
    stdout = io.StringIO()
    serve(stdin, stdout, conn, default_project="p")
    lines = [l for l in stdout.getvalue().splitlines() if l.strip()]
    assert len(lines) == 2  # initialize + tools/list; notification produced no line
    assert json.loads(lines[0])["result"]["serverInfo"]["name"] == "akdb"
    assert any(t["name"] == "architectural_knowledge_db_search"
               for t in json.loads(lines[1])["result"]["tools"])


def test_stdio_transport_is_reconfigured_to_utf8():
    buffer = io.BytesIO()
    stream = io.TextIOWrapper(buffer, encoding="cp1252")
    configure_stdio_utf8(stream)
    assert stream.encoding.lower().replace("-", "") == "utf8"
    stream.write(json.dumps({"description": "source -> target"}, ensure_ascii=False).replace("->", "→"))
    stream.flush()
    assert "→".encode("utf-8") in buffer.getvalue()
