from __future__ import annotations

import subprocess
from pathlib import Path

from architectural_knowledge_db.services.import_export import ImportExportService
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.models import ProjectUpsert

FIXTURES = {
    "docs/architecture/plugins/Demo/architecture.md": "# Demo\n\n## 1. Goals\n\nBody.   \n",
    "docs/architecture/START-HERE.md": "# Start Here\n\nNav.\n",
    "docs/architecture/contracts/x.md": "# X\n",
    "UML/Plugins/Demo/components/c4-context.puml": "@startuml\n@enduml\n",
    "UML/Plugins/Demo/components/c4-context.md": "```plantuml\n@startuml\n@enduml\n```\n",
}


def _seed(root: Path):
    # repo_relative_key() (import_export.py) walks up looking for a ".git" marker
    # to compute the repo-relative path; a real git repo makes this fixture behave
    # like the real PluginProject checkout instead of falling back to an absolute
    # path (which would defeat the whole-tree mirror layout under test).
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    for rel, text in FIXTURES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="")


def test_export_canon_reproduces_repo_tree_byte_for_byte(conn, tmp_path):
    src = tmp_path / "repo"
    _seed(src)
    ProjectService(conn).upsert_project(
        ProjectUpsert(project_id="canon", display_name="Canon")
    )
    svc = ImportExportService(conn)
    svc.import_documents("canon", src / "docs" / "architecture", include=["**/*"])
    svc.import_documents("canon", src / "UML", include=["**/*"])

    out = tmp_path / "export"
    result = svc.export_canon("canon", out)

    assert result["exported"] == len(FIXTURES)
    for rel, text in FIXTURES.items():
        target = out / rel
        assert target.is_file(), f"missing {rel}"
        assert target.read_text(encoding="utf-8") == text, f"bytes drift for {rel}"
    manifest = out / ".akdb-canon-export.json"
    assert manifest.is_file()


def test_export_canon_preserves_non_utf8_encodings_byte_exact(conn, tmp_path):
    # Real canon gap found in Phase 4 (2026-07-23): a captured build log
    # (docs/architecture/evidence/2026-07-02-apm-build.log) is UTF-16 LE with a
    # BOM (a common artifact of Windows PowerShell `> file.log` redirection).
    # import_documents() must not crash on non-UTF-8 text, and export_canon()
    # must reproduce the exact original bytes (encoding + BOM), not re-encode
    # as UTF-8 -- verify_canon() byte-diffs raw bytes, so any transcoding would
    # be a permanent, undetected drift the moment this file is ingested.
    src = tmp_path / "repo"
    src.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=src, check=True)
    target = src / "docs" / "architecture" / "evidence" / "build.log"
    target.parent.mkdir(parents=True, exist_ok=True)
    original_bytes = b"\xff\xfe" + "2026-01-01 boot ok\r\n".encode("utf-16-le")
    target.write_bytes(original_bytes)

    ProjectService(conn).upsert_project(
        ProjectUpsert(project_id="canon-enc", display_name="Canon Enc")
    )
    svc = ImportExportService(conn)
    svc.import_documents("canon-enc", src / "docs" / "architecture", include=["**/*"])

    out = tmp_path / "export"
    svc.export_canon("canon-enc", out)

    exported = out / "docs" / "architecture" / "evidence" / "build.log"
    assert exported.is_file(), "missing docs/architecture/evidence/build.log"
    assert exported.read_bytes() == original_bytes, "UTF-16 bytes drifted on export"


def test_export_canon_excludes_product_fact_sheet_items(conn, tmp_path):
    # Real gap found in Phase 4 (2026-07-23): the live tiny-tool-development
    # project already carries unrelated "product_fact_sheet" items (an older,
    # separate AKDB feature) that happen to reuse the same repo_source_key +
    # body_text metadata shape as canon documents. Class H (product-facts.yml)
    # is explicitly excluded from THIS canon migration and stays in Git --
    # export_canon() must not sweep those items into the byte-mirror, or a
    # stale product_fact_sheet body_text silently becomes a verify_canon
    # "mismatched" false-positive against the live (edited-since) file.
    src = tmp_path / "repo"
    _seed(src)
    ProjectService(conn).upsert_project(
        ProjectUpsert(project_id="canon-pf", display_name="Canon PF")
    )
    svc = ImportExportService(conn)
    svc.import_documents("canon-pf", src / "docs" / "architecture", include=["**/*"])
    svc.import_documents("canon-pf", src / "UML", include=["**/*"])

    # Simulate the pre-existing, unrelated product_fact_sheet item.
    svc.knowledge._upsert_item(
        project_id="canon-pf",
        space_id=None,
        item_type="product_fact_sheet",
        local_id="demo-product-facts",
        title="Demo product facts",
        status=None,
        authority_level="project_note",
        summary=None,
        source_uri=str(src / "docs" / "architecture" / "plugins" / "Demo" / "product-facts.yml"),
        metadata={
            "repo_source_key": "docs/architecture/plugins/Demo/product-facts.yml",
            "body_text": "display_name: Demo\nversion: 9.9.9-stale\n",
        },
    )

    out = tmp_path / "export"
    result = svc.export_canon("canon-pf", out)

    assert result["exported"] == len(FIXTURES), "product-facts.yml leaked into the canon export"
    assert not (out / "docs" / "architecture" / "plugins" / "Demo" / "product-facts.yml").exists()
