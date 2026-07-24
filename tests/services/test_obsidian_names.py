from __future__ import annotations

from architectural_knowledge_db.services.obsidian_export import ObsidianNameRegistry


def test_registry_is_unique_stable_and_qualifies_collisions():
    reg = ObsidianNameRegistry()
    a = reg.register(
        item_uid="u1",
        item_type="sad",
        title="Software Architecture",
        repo="Git",
        section_key=None,
    )
    b = reg.register(
        item_uid="u2",
        item_type="sad",
        title="Software Architecture",
        repo="AKDB",
        section_key=None,
    )
    assert a != b  # collision qualified
    assert reg.resolve("u1") == a
    # stability: a fresh registry fed the same inputs in the same order yields identical names
    reg2 = ObsidianNameRegistry()
    a2 = reg2.register(
        item_uid="u1",
        item_type="sad",
        title="Software Architecture",
        repo="Git",
        section_key=None,
    )
    b2 = reg2.register(
        item_uid="u2",
        item_type="sad",
        title="Software Architecture",
        repo="AKDB",
        section_key=None,
    )
    assert (a, b) == (a2, b2)
