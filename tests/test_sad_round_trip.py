from __future__ import annotations

import re
from pathlib import Path

from architectural_knowledge_db.services.import_export import ImportExportService
from tests.conftest import add_project


def _norm(s: str) -> str:
    return re.sub(r"[ \t]+\n", "\n", s).strip() + "\n"


def test_sad_round_trips(conn, tmp_path: Path) -> None:
    add_project(conn, "p")
    fixture = Path(__file__).parent / "fixtures" / "sample_architecture.md"
    src = tmp_path / "src"
    src.mkdir()
    (src / "architecture.md").write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    svc = ImportExportService(conn)
    svc.import_documents("p", src)
    out = tmp_path / "out"
    svc.export_sad("p", out)
    assert _norm((out / "architecture.md").read_text(encoding="utf-8")) == _norm(
        fixture.read_text(encoding="utf-8")
    )
