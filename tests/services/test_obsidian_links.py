from __future__ import annotations

from architectural_knowledge_db.services.obsidian_export import ObsidianNameRegistry, rewrite_links


def test_rewrite_resolved_and_unresolved():
    body = "See [D1](#d1-product-boundary) and [IIS](internalindexservice/architecture.md)."

    def resolve(href):
        if href.startswith("#d1"):
            return "IIS — Software Architecture#D1 Product boundary"
        return None  # the file link is unresolved

    out, unresolved = rewrite_links(body, registry=ObsidianNameRegistry(), resolve_target=resolve)
    assert "[[IIS — Software Architecture#D1 Product boundary]]" in out
    assert "[[" not in out.split("and")[1]  # unresolved link did NOT become a wikilink
    assert "IIS" in out  # its text survived as plain text
    assert any("architecture.md" in u for u in unresolved)
