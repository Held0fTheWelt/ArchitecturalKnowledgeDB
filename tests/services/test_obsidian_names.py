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


def test_registry_uid_suffix_is_filesystem_safe():
    """Windows forbids ':' (and <>"|?*) in filenames; uid suffixes must be sanitized."""
    reg = ObsidianNameRegistry()
    reg.register(
        item_uid="proj:sad:a",
        item_type="sad",
        title="Dup",
        repo="Git",
        section_key="00",
    )
    reg.register(
        item_uid="proj:sad:b",
        item_type="sad",
        title="Dup",
        repo="Git",
        section_key="00",
    )
    # Third collision shares base+repo+section → appends item_uid
    name = reg.register(
        item_uid="proj:sad:c:with:colons",
        item_type="sad",
        title="Dup",
        repo="Git",
        section_key="00",
    )
    forbidden = '<>:"|?*\\/'
    assert ":" not in name
    assert not any(ch in name for ch in forbidden)


def test_registry_treats_case_variants_as_collisions():
    """Windows/Obsidian vaults are case-insensitive; 'Foo' and 'foo' must not share a path."""
    reg = ObsidianNameRegistry()
    a = reg.register(
        item_uid="u1",
        item_type="sad",
        title="D1 Product Boundary And Package Contract",
        repo="Git",
        section_key=None,
    )
    b = reg.register(
        item_uid="u2",
        item_type="sad",
        title="D1 Product boundary and package contract",
        repo="Git",
        section_key="D1",
    )
    assert a.casefold() != b.casefold()
    assert a != b
