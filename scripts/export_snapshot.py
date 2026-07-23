#!/usr/bin/env python3
"""Produce a compressed, restorable SQL dump of the AKDB sqlite database.

CI has no access to the live AKDB database (or a running Postgres instance),
so the export freshness gate (`Tools/Pipeline/export_freshness_gate` in the
TTD-Plugins repo) instead loads a committed snapshot and runs the exact same
`akdb export target-verify` engine against it. This script produces that
snapshot; refresh it (and re-commit) whenever the DB changes in a way that
should be reflected in CI's view of the mirror.

Equivalent to the standard `sqlite3 <db> .dump | gzip > <out>` recipe, with
one deliberate omission: the `fts_knowledge` FTS5 virtual table (and its
`INSERT INTO sqlite_master ...` bootstrap row) is dropped from the dump.
Python's `sqlite3.Connection.iterdump()` emits virtual tables via a legacy
`INSERT INTO sqlite_master` trick whose shadow tables are only wired up by
the *next* fresh connection's schema parse -- not the same connection that
just ran the INSERT -- so a same-process dump/restore round-trip (as used by
--restore-check below, and by any Python-based CI restore step) leaves
`fts_knowledge` broken. The underlying content is not lost: FTS5's own
`fts_knowledge_content` shadow table is a normal table and dumps/restores
fine. `export target-verify` only reads `knowledge_items`/`adrs`/`export_*`,
so the search index is irrelevant to freshness-gate correctness -- it is a
derived accelerator, not system-of-record data.

Usage:
    python scripts/export_snapshot.py --db .akdb/architectural_knowledge_db.sqlite --out snapshots/tiny-tool-development.sql.gz
    python scripts/export_snapshot.py --db ... --out ... --restore-check   # also restores into a temp DB and sanity-checks row counts
"""

from __future__ import annotations

import argparse
import gzip
import sqlite3
import sys
import tempfile
from pathlib import Path

_SKIP_PREFIXES = (
    "INSERT INTO sqlite_master",
    'INSERT INTO "fts_knowledge"',
    "INSERT INTO 'fts_knowledge'",
)


def _filtered_dump(conn: sqlite3.Connection):
    skipping_virtual_table_body = False
    for line in conn.iterdump():
        if any(line.startswith(p) for p in _SKIP_PREFIXES):
            skipping_virtual_table_body = line.startswith("INSERT INTO sqlite_master") and not line.rstrip().endswith(");")
            continue
        if skipping_virtual_table_body:
            if line.rstrip().endswith(");") or line.rstrip().endswith("')"):
                skipping_virtual_table_body = False
            continue
        yield line


def build_snapshot(db_path: Path, out_path: Path) -> str:
    conn = sqlite3.connect(str(db_path))
    try:
        sql_text = "\n".join(_filtered_dump(conn))
    finally:
        conn.close()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out_path, "wt", encoding="utf-8") as f:
        f.write(sql_text)
    return sql_text


def restore_check(sql_text: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        restored = Path(tmp) / "restored.sqlite"
        conn = sqlite3.connect(str(restored))
        try:
            conn.executescript(sql_text)
            n_items = conn.execute("select count(*) from knowledge_items").fetchone()[0]
            n_targets = conn.execute("select count(*) from export_targets").fetchone()[0]
        finally:
            conn.close()
    print(f"restore-check OK: knowledge_items={n_items} export_targets={n_targets}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True, type=Path, help="Path to the source sqlite database.")
    parser.add_argument("--out", required=True, type=Path, help="Path to write the compressed .sql.gz snapshot to.")
    parser.add_argument("--restore-check", action="store_true", help="Also restore into a temp DB and print sanity-check row counts.")
    args = parser.parse_args(argv)

    if not args.db.is_file():
        print(f"export_snapshot: no such database: {args.db}", file=sys.stderr)
        return 1

    sql_text = build_snapshot(args.db, args.out)
    print(f"wrote {args.out} ({args.out.stat().st_size} bytes, {len(sql_text)} chars uncompressed)")

    if args.restore_check:
        restore_check(sql_text)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
