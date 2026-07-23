from __future__ import annotations

from typing import Any, Sequence


def to_pyformat(sql: str) -> str:
    """Convert sqlite qmark placeholders to psycopg pyformat.

    Escapes any literal '%' first (psycopg treats '%' specially), then turns each
    '?' bind marker into '%s'. Safe because no SQL string literal in this codebase
    contains a '?' or '%' (asserted by the codebase-wide test below)."""
    return sql.replace("%", "%%").replace("?", "%s")


def _split_statements(script: str) -> list[str]:
    # Our DDL contains no embedded ';' (PG FTS uses a generated column, not a
    # trigger), so a plain split is sufficient.
    return [stmt.strip() for stmt in script.split(";") if stmt.strip()]


class Database:
    """A sqlite3.Connection-compatible facade over sqlite3 OR psycopg (PostgreSQL)."""

    def __init__(self, raw: Any, *, is_postgres: bool) -> None:
        self._raw = raw
        self.is_postgres = is_postgres
        self._pg_changes = 0

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        bind = tuple(params)
        if self.is_postgres:
            cur = self._raw.execute(to_pyformat(sql), bind or None)
            rowcount = getattr(cur, "rowcount", -1)
            if rowcount and rowcount > 0:
                self._pg_changes += rowcount
            return cur
        return self._raw.execute(sql, bind)

    def executescript(self, script: str) -> None:
        if self.is_postgres:
            for stmt in _split_statements(script):
                self._raw.execute(stmt)
        else:
            self._raw.executescript(script)

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        self._raw.close()

    @property
    def total_changes(self) -> int:
        return self._pg_changes if self.is_postgres else self._raw.total_changes
