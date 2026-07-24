from __future__ import annotations

from architectural_knowledge_db.models import AdrInput, ProjectUpsert
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.services.workspace import WorkspaceService


def _seed_crossrepo_link(conn) -> tuple[str, str, str]:
    """TTD ADR links to AKDB SAD via repo-qualified path; return (ttd, akdb, akdb_sad_uid)."""
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="ttd", display_name="TTD"))
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="akdb", display_name="AKDB"))
    ks = KnowledgeService(conn)
    akdb_uid = ks._upsert_item(
        project_id="akdb",
        space_id=None,
        item_type="sad",
        local_id="gov",
        title="AKDB Software Architecture",
        status="current",
        authority_level="active_rule",
        summary="AKDB SAD",
        source_uri="akdb://akdb/sad/gov",
        metadata={
            "repo_source_key": "docs/architecture/architecture.md",
            "repository_id": "ArchitecturalKnowledgeDB",
            "system": "AKDB",
            "body_text": "# AKDB Software Architecture\n\n## Overview\n\nBody.\n",
            "body_encoding": "utf-8",
        },
    )
    ks.upsert_adr(
        "ttd",
        AdrInput(
            adr_id="ADR-X1",
            title="ADR-X1 Cross-repo link",
            status="proposed",
            metadata={
                "repo_source_key": "docs/ADR/ADR-X1.md",
                "repository_id": "Git",
                "system": "Governance",
                "body_text": (
                    "# ADR-X1\n\n"
                    "See [AKDB](ArchitecturalKnowledgeDB/docs/architecture/architecture.md).\n"
                ),
                "body_encoding": "utf-8",
            },
        ),
    )
    # Seed workspace inventory so resolve_reference can find the path.
    conn.execute(
        "INSERT OR IGNORE INTO repositories(project_id, repository_id, local_path) VALUES (?,?,?)",
        ("akdb", "ArchitecturalKnowledgeDB", "D:/TinyToolDevelopment/ArchitecturalKnowledgeDB"),
    )
    conn.execute(
        "INSERT OR REPLACE INTO repository_files(repository_id, path, anchors_json) VALUES (?,?,?)",
        ("ArchitecturalKnowledgeDB", "docs/architecture/architecture.md", "[]"),
    )
    conn.commit()
    return "ttd", "akdb", akdb_uid


def test_crossrepo_wikilink_resolves_via_global_registry(conn):
    ttd, akdb, akdb_uid = _seed_crossrepo_link(conn)
    from architectural_knowledge_db.services.obsidian_export import (
        build_global_registry,
        expected_vault_files,
    )

    registry = build_global_registry(conn, [ttd, akdb])
    akdb_name = registry.resolve(akdb_uid)
    assert akdb_name is not None

    workspace = WorkspaceService(conn)
    ttd_files = expected_vault_files(
        conn, ttd, "TTD", workspace=workspace, global_registry=registry
    )
    akdb_files = expected_vault_files(
        conn, akdb, "AKDB", workspace=workspace, global_registry=registry
    )

    assert f"AKDB/{akdb_name}.md" in akdb_files
    adr = next(v for k, v in ttd_files.items() if "ADR-X1" in k).decode()
    assert f"[[{akdb_name}]]" in adr
