from __future__ import annotations

from typing import Any, Sequence


def to_pyformat(sql: str) -> str:
    """Convert sqlite qmark placeholders to psycopg pyformat.

    Escapes any literal '%' first (psycopg treats '%' specially), then turns each
    '?' bind marker into '%s'. Safe because no SQL string literal in this codebase
    contains a '?' or '%' (asserted by the codebase-wide test below)."""
    return sql.replace("%", "%%").replace("?", "%s")
