import pytest

from architectural_knowledge_db.services.change_sets import ImpactParseError, parse_impact_section


DOC = """
# Some spec
## Architektur-Impact
- modify     SAD:UGE-Comp decision D7   — tighten resolve
- add        UML:element CompositionResolver in comp-diagram
- supersede  ADR-PLUG-0012
- add        rule NoDirectMeshAccess
## Next section
- not a change item
"""


def test_parses_all_kinds():
    items = parse_impact_section(DOC)
    assert [(i.op, i.target_kind) for i in items] == [
        ("modify", "sad_decision"),
        ("add", "uml_element"),
        ("supersede", "adr"),
        ("add", "rule"),
    ]
    assert items[0].target_ref == "UGE-Comp:D7"
    assert items[0].note == "tighten resolve"


def test_unknown_op_raises():
    with pytest.raises(ImpactParseError):
        parse_impact_section("## Architektur-Impact\n- destroy ADR-1\n")


def test_missing_section_returns_empty():
    assert parse_impact_section("# spec\nno impact here\n") == []
