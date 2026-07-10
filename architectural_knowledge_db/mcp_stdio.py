from __future__ import annotations

import json
import os
import sqlite3
import sys
from typing import Any, TextIO

from architectural_knowledge_db.config import Settings
from architectural_knowledge_db.db.connection import initialize_database
from architectural_knowledge_db.mcp import MCP_MANIFEST, McpDispatcher

SERVER_NAME = "akdb"
SERVER_VERSION = "0.1.0"
DEFAULT_PROTOCOL_VERSION = "2025-06-18"


def _tools_list() -> list[dict[str, Any]]:
    return [
        {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "inputSchema": tool.get("input_schema", {"type": "object"}),
        }
        for tool in MCP_MANIFEST["tools"]
    ]


class StdioServer:
    def __init__(self, conn: sqlite3.Connection, default_project: str | None = None) -> None:
        self.conn = conn
        self.dispatcher = McpDispatcher(conn)
        self.default_project = default_project

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        msg_id = message.get("id")
        if msg_id is None and str(method or "").startswith("notifications/"):
            return None
        if method == "initialize":
            params = message.get("params") or {}
            return self._ok(msg_id, {
                "protocolVersion": params.get("protocolVersion", DEFAULT_PROTOCOL_VERSION),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            })
        if method == "ping":
            return self._ok(msg_id, {})
        if method == "tools/list":
            return self._ok(msg_id, {"tools": _tools_list()})
        if method == "tools/call":
            params = message.get("params") or {}
            name = params.get("name")
            arguments = dict(params.get("arguments") or {})
            if self.default_project and "project_id" not in arguments:
                arguments["project_id"] = self.default_project
            try:
                result = self.dispatcher.dispatch(name, arguments)
                self.conn.commit()
            except Exception as exc:  # tool-level error: MCP result with isError, not a protocol error
                self.conn.rollback()
                return self._ok(msg_id, {"content": [{"type": "text", "text": str(exc)}], "isError": True})
            text = json.dumps(result, ensure_ascii=False, default=str)
            return self._ok(msg_id, {"content": [{"type": "text", "text": text}]})
        if msg_id is None:
            return None
        return self._error(msg_id, -32601, f"Method not found: {method}")

    @staticmethod
    def _ok(msg_id: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    @staticmethod
    def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def serve(stdin: TextIO, stdout: TextIO, conn: sqlite3.Connection,
          default_project: str | None = None) -> None:
    server = StdioServer(conn, default_project=default_project)
    for raw in stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            continue
        response = server.handle(message)
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()


def main() -> None:
    settings = Settings.from_env()
    conn = initialize_database(settings.database_path)
    conn.execute("PRAGMA busy_timeout = 5000")
    serve(sys.stdin, sys.stdout, conn, default_project=os.getenv("AKDB_DEFAULT_PROJECT"))


if __name__ == "__main__":
    main()
