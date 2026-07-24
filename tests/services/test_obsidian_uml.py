from __future__ import annotations

from architectural_knowledge_db.services.obsidian_export import ObsidianNameRegistry, render_uml_note


def test_uml_renders_as_plantuml_fence():
    item = {
        "item_uid": "d1",
        "item_type": "uml_diagram",
        "title": "IIS Components",
        "metadata": {"body_text": "@startuml\nA --> B\n@enduml\n"},
    }
    note = render_uml_note(item, registry=ObsidianNameRegistry())
    assert "```plantuml" in note and "@startuml" in note and "A --> B" in note
    assert "```" in note.rstrip()[-3:]
