from __future__ import annotations

from architectural_knowledge_db.models import AdrInput, ProjectUpsert
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.projects import ProjectService


def _seed_min_project(conn) -> str:
    """1 SAD + 1 ADR whose body markdown-links the SAD (for wikilink rewrite)."""
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="p", display_name="P"))
    ks = KnowledgeService(conn)
    ks._upsert_item(
        project_id="p",
        space_id=None,
        item_type="sad",
        local_id="gov",
        title="Software Architecture",
        status="current",
        authority_level="active_rule",
        summary="Governance SAD",
        source_uri="akdb://p/sad/gov",
        metadata={
            "repo_source_key": "docs/architecture/architecture.md",
            "repository_id": "Git",
            "system": "Governance",
            "body_text": (
                "# Software Architecture\n\n"
                "## D1 Product boundary\n\n"
                "Boundary text.\n"
            ),
            "body_encoding": "utf-8",
        },
    )
    ks.upsert_adr(
        "p",
        AdrInput(
            adr_id="ADR-0001",
            title="ADR-0001 Choose X",
            status="proposed",
            metadata={
                "repo_source_key": "docs/ADR/ADR-0001.md",
                "repository_id": "Git",
                "system": "Governance",
                "body_text": (
                    "# ADR-0001\n\n"
                    "See [SAD](docs/architecture/architecture.md#d1-product-boundary).\n"
                ),
                "body_encoding": "utf-8",
            },
        ),
    )
    return "p"


def test_expected_vault_files_are_namespaced_and_linked(conn):
    pid = _seed_min_project(conn)
    from architectural_knowledge_db.services.obsidian_export import expected_vault_files

    files = expected_vault_files(conn, pid, "TTD")
    assert all(rel.startswith("TTD/") and rel.endswith(".md") for rel in files)
    adr = next(v for k, v in files.items() if "ADR" in k).decode()
    assert "---" in adr and "kind: adr" in adr and "[[" in adr  # frontmatter + a resolved wikilink
