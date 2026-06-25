from __future__ import annotations

from tests.conftest import add_project


def test_check_change_flags_forbidden(conn):
    from architectural_knowledge_db.models import RuleInput
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    from architectural_knowledge_db.services.guardrail import GuardrailService
    add_project(conn, "p")
    KnowledgeService(conn).upsert_rule("p", RuleInput(
        rule_id="R1", rule_text="no raw stdout in stdio servers",
        applies_to=["**/mcp_stdio.py"], forbidden_changes=["print("], authority_level="hard_guardrail"))
    out = GuardrailService(conn).check_change("p", {"path": "pkg/mcp_stdio.py", "summary": "add print( debug"})
    assert out["ok"] is False
    assert out["violations"][0]["rule_id"] == "R1"
    clean = GuardrailService(conn).check_change("p", {"path": "pkg/other.py", "summary": "add print( debug"})
    assert clean["ok"] is True   # path not in applies_to


def test_review_draft_spec_not_sound(conn):
    from architectural_knowledge_db.models import SpecInput
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    from architectural_knowledge_db.services.review import ReviewService
    add_project(conn, "p")
    suid = KnowledgeService(conn).upsert_spec("p", SpecInput(spec_id="S1", title="x", archetype="function"))["item_uid"]
    out = ReviewService(conn).review("p", suid)
    assert out["sound"] is False
    assert out["completeness"] is not None and out["completeness"]["ok"] is False
