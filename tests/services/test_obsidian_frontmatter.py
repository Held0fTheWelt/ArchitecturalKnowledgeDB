from __future__ import annotations

from architectural_knowledge_db.services.obsidian_export import build_frontmatter


def test_frontmatter_includes_status_and_links():
    fm = build_frontmatter(
        kind="adr",
        status="proposed",
        repo="Git",
        system="Governance",
        source_key="docs/ADR/ADR-ARCH-0001.md",
        aliases=["ADR-ARCH-0001"],
        tags=["adr", "governance"],
        links=["[[Governance — Software Architecture]]"],
    )
    assert fm.startswith("---\n") and fm.rstrip().endswith("---")
    assert "kind: adr" in fm and "status: proposed" in fm
    assert '"[[Governance — Software Architecture]]"' in fm


def test_frontmatter_omits_status_for_presence_based_kind():
    fm = build_frontmatter(
        kind="sad_section",
        status=None,
        repo="Git",
        system="IIS",
        source_key=None,
        aliases=[],
        tags=["sad_section"],
        links=[],
    )
    assert "status:" not in fm
