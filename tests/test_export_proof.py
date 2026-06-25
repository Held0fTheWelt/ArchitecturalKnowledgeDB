from __future__ import annotations

import hashlib
from pathlib import Path

from architectural_knowledge_db.db.connection import initialize_database
from architectural_knowledge_db.models import AdrInput, ProjectUpsert
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.import_export import ImportExportService


def _project(tmp_path: Path):
    conn = initialize_database(tmp_path / "akdb.sqlite")
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="p", display_name="P"))
    conn.commit()
    return conn


def _make_docs(src: Path) -> None:
    (src / "sub").mkdir(parents=True)
    (src / "a.md").write_text("# A\n\nbody A\n", encoding="utf-8", newline="\n")
    (src / "sub" / "b.md").write_text("# B\n\nbody B\n", encoding="utf-8", newline="\n")


def test_export_documents_reproduces_source(tmp_path):
    conn = _project(tmp_path)
    src = tmp_path / "docs"
    _make_docs(src)
    ImportExportService(conn).import_documents("p", src)
    conn.commit()

    out = tmp_path / "export"
    result = ImportExportService(conn).export_documents("p", out)

    assert result["exported"] >= 2
    assert (out / "a.md").read_text(encoding="utf-8") == (src / "a.md").read_text(encoding="utf-8")
    assert (out / "sub" / "b.md").read_text(encoding="utf-8") == (src / "sub" / "b.md").read_text(encoding="utf-8")


def test_export_corpus_populates_layout(tmp_path):
    conn = _project(tmp_path)
    src = tmp_path / "docs"
    _make_docs(src)
    ImportExportService(conn).import_documents("p", src)
    KnowledgeService(conn).upsert_adr(
        "p", AdrInput(adr_id="ADR-0001", title="First", status="accepted", decision_md="Decision.")
    )
    conn.commit()

    out = tmp_path / "corpus"
    report = ImportExportService(conn).export_corpus("p", out)

    assert (out / "documents" / "a.md").exists()
    assert report["documents"]["exported"] >= 2
    assert (out / "adr").is_dir()
    assert report["adr"]["exported"] >= 1


def _tree_digest(folder: Path) -> list[tuple[str, str]]:
    out = []
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        out.append((path.relative_to(folder).as_posix(), digest))
    return out


def test_export_corpus_is_deterministic(tmp_path):
    conn = _project(tmp_path)
    src = tmp_path / "docs"
    _make_docs(src)
    ImportExportService(conn).import_documents("p", src)
    conn.commit()

    a = tmp_path / "a"
    b = tmp_path / "b"
    ImportExportService(conn).export_corpus("p", a)
    ImportExportService(conn).export_corpus("p", b)
    assert _tree_digest(a) == _tree_digest(b)


def test_verify_corpus_reports_full_fidelity(tmp_path):
    conn = _project(tmp_path)
    src = tmp_path / "docs"
    _make_docs(src)
    ImportExportService(conn).import_documents("p", src)
    conn.commit()

    canonical = tmp_path / "canonical"
    ImportExportService(conn).export_corpus("p", canonical)

    report = ImportExportService(conn).verify_corpus("p", canonical)
    assert report["matched"] > 0
    assert report["mismatched"] == []

    # tamper with one exported file -> verifier must catch it
    (canonical / "documents" / "a.md").write_text("CORRUPTED\n", encoding="utf-8", newline="\n")
    bad = ImportExportService(conn).verify_corpus("p", canonical)
    assert "documents/a.md" in bad["mismatched"]


def test_cli_export_run_and_verify(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from architectural_knowledge_db.cli import app

    monkeypatch.setenv("AKDB_DATABASE_PATH", str(tmp_path / "cli.sqlite"))
    runner = CliRunner()

    conn = initialize_database(tmp_path / "cli.sqlite")
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="p", display_name="P"))
    src = tmp_path / "docs"
    src.mkdir()
    (src / "a.md").write_text("# A\n\nbody\n", encoding="utf-8", newline="\n")
    ImportExportService(conn).import_documents("p", src)
    conn.commit()
    conn.close()

    out = tmp_path / "corpus"
    r1 = runner.invoke(app, ["export", "run", "--project", "p", "--folder", str(out)])
    assert r1.exit_code == 0, r1.output
    r2 = runner.invoke(app, ["export", "verify", "--project", "p", "--folder", str(out)])
    assert r2.exit_code == 0, r2.output
    assert '"mismatched": []' in r2.stdout or "'mismatched': []" in r2.stdout


def test_export_includes_links_and_roadmap(conn, tmp_path):
    from architectural_knowledge_db.services.authoring import AuthoringService
    from architectural_knowledge_db.services.import_export import ImportExportService
    from tests.conftest import add_project
    add_project(conn, "p"); conn.commit()
    AuthoringService(conn).create_mvp("p", "M1", "first"); conn.commit()
    out = ImportExportService(conn).export_corpus("p", tmp_path / "exp")
    assert (tmp_path / "exp" / "links" / "links.json").exists()
    assert (tmp_path / "exp" / "roadmap" / "ROADMAP.md").exists()
    v = ImportExportService(conn).verify_corpus("p", tmp_path / "exp")
    assert v["mismatched"] == []
