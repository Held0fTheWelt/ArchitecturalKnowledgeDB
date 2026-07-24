from __future__ import annotations

from architectural_knowledge_db.models import ProjectUpsert
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.projects import ProjectService


def _seed_two_projects_same_sad_title(conn) -> tuple[str, str, str, str]:
    """Two projects each with a 'Software Architecture' SAD; return (p1, p2, uid1, uid2)."""
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="ttd", display_name="TTD"))
    ProjectService(conn).upsert_project(ProjectUpsert(project_id="akdb", display_name="AKDB"))
    ks = KnowledgeService(conn)
    uid1 = ks._upsert_item(
        project_id="ttd",
        space_id=None,
        item_type="sad",
        local_id="gov",
        title="Software Architecture",
        status="current",
        authority_level="active_rule",
        summary="TTD SAD",
        source_uri="akdb://ttd/sad/gov",
        metadata={
            "repo_source_key": "docs/architecture/architecture.md",
            "repository_id": "Git",
            "system": "Governance",
            "body_text": "# Software Architecture\n\nTTD body.\n",
            "body_encoding": "utf-8",
        },
    )
    uid2 = ks._upsert_item(
        project_id="akdb",
        space_id=None,
        item_type="sad",
        local_id="gov",
        title="Software Architecture",
        status="current",
        authority_level="active_rule",
        summary="AKDB SAD",
        source_uri="akdb://akdb/sad/gov",
        metadata={
            "repo_source_key": "docs/architecture/architecture.md",
            "repository_id": "ArchitecturalKnowledgeDB",
            "system": "AKDB",
            "body_text": "# Software Architecture\n\nAKDB body.\n",
            "body_encoding": "utf-8",
        },
    )
    return "ttd", "akdb", uid1, uid2


def test_build_global_registry_qualifies_cross_project_title_collisions(conn):
    p1, p2, uid1, uid2 = _seed_two_projects_same_sad_title(conn)
    from architectural_knowledge_db.services.obsidian_export import build_global_registry

    reg = build_global_registry(conn, [p1, p2])
    name1 = reg.resolve(uid1)
    name2 = reg.resolve(uid2)
    assert name1 is not None and name2 is not None
    assert name1 != name2
    assert name1.casefold() != name2.casefold()
    # First holder keeps the bare title; the collision is repo-qualified (A1 / D4).
    qualified = {name1, name2} - {"Software Architecture"}
    assert qualified, "collision must produce a repo-qualified name"
    assert any("Git" in n or "ArchitecturalKnowledgeDB" in n for n in qualified)

    # Stability: same inputs → identical names.
    reg2 = build_global_registry(conn, [p1, p2])
    assert (reg2.resolve(uid1), reg2.resolve(uid2)) == (name1, name2)
