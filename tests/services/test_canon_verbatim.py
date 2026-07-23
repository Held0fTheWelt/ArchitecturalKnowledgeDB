from __future__ import annotations

from pathlib import Path

from architectural_knowledge_db.services.import_export import ImportExportService
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.models import ProjectUpsert

# One fixture per byte-shape present in the canon (md, yml, json, csv, puml, log, uplugin).
CANON_FIXTURES = {
    "plugins/Demo/architecture.md": "# Demo SAD\n\n## 1. Introduction & Goals\n\nBody with trailing spaces.   \n",
    "plugins/Demo/product-facts.yml": "display_name: Demo\nversion: 1.2.3\n",
    "contracts/demo_contract.md": "# Contract\n\n- rule: x\n",
    "evidence/2026-01-01-demo.md": "# Evidence\n\nData: 42\n",
    "outer_tools/catalog.json": '{\n  "a": 1,\n  "b": [2, 3]\n}\n',
    "gates/worklist.csv": "id,status\n1,green\n2,red\n",
    "UML/Plugins/Demo/components/c4-context.puml": "@startuml\nDemo --> Db\n@enduml\n",
    "UML/Plugins/Demo/components/c4-context.md": "```plantuml\n@startuml\n@enduml\n```\n",
    "operations/notes.log": "2026-01-01 boot ok\n",
    "plugins/Demo/Demo.uplugin": '{ "FriendlyName": "Demo" }\n',
}


def _seed_tree(tmp_path: Path) -> None:
    # Fixture keys are repo-relative: "UML/..." keys live at the repo root's UML/
    # tree; everything else lives under docs/architecture/ (mirrors the real canon layout).
    tree = tmp_path / "docs" / "architecture"
    for rel, text in CANON_FIXTURES.items():
        p = tmp_path / rel if rel.startswith("UML/") else tree / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="")


def test_every_canon_class_stores_exact_bytes_and_repo_path(tmp_path, conn):
    tree = tmp_path / "docs" / "architecture"
    uml = tmp_path / "UML"
    _seed_tree(tmp_path)  # writes both docs/architecture/** and UML/**

    ProjectService(conn).upsert_project(
        ProjectUpsert(project_id="canon-test", display_name="Canon Test")
    )
    svc = ImportExportService(conn)
    # Import BOTH trees; include everything so no suffix is skipped.
    svc.import_documents("canon-test", tree, include=["**/*"])
    svc.import_documents("canon-test", uml, include=["**/*"])

    items = KnowledgeService(conn).list_items("canon-test", include_shared=False, limit=100000)
    by_repo_key = {
        (it.get("metadata") or {}).get("repo_source_key"): it
        for it in items
        if (it.get("metadata") or {}).get("body_text") is not None
    }

    for rel, expected in CANON_FIXTURES.items():
        # repo_source_key is repo-relative; assert one item round-trips this file's exact bytes.
        matches = [it for k, it in by_repo_key.items() if k and k.endswith(rel)]
        assert matches, f"no verbatim item ingested for {rel}"
        assert matches[0]["metadata"]["body_text"] == expected, f"bytes drift for {rel}"


def test_sad_children_are_not_mistaken_for_files(conn, tmp_path):
    tree = tmp_path / "docs" / "architecture"
    p = tree / "plugins" / "Demo" / "architecture.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "# Demo SAD\n\n## 1. Introduction\n\nText.\n\n"
        "## 9. Decisions\n\n### D1: Use X\n\n**Status:** accepted\n\nBecause.\n",
        encoding="utf-8", newline="",
    )
    ProjectService(conn).upsert_project(
        ProjectUpsert(project_id="child-test", display_name="Child Test")
    )
    ImportExportService(conn).import_documents("child-test", tree, include=["**/*"])

    items = KnowledgeService(conn).list_items("child-test", include_shared=False, limit=100000)
    file_items = [it for it in items if (it.get("metadata") or {}).get("body_text") is not None]
    child_items = [it for it in items if it["item_type"] in ("sad_section", "sad_decision", "sad_frontmatter")]

    # Exactly one raw file, and no child leaks a body_text.
    assert len(file_items) == 1
    assert all((it.get("metadata") or {}).get("body_text") is None for it in child_items)
    assert child_items, "SAD should still decompose into structured children (the value-add)"
