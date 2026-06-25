from __future__ import annotations

from tests.conftest import add_project


def test_survey_sections(conn):
    from architectural_knowledge_db.services.authoring import AuthoringService
    from architectural_knowledge_db.services.survey import SurveyService
    add_project(conn, "p")
    a = AuthoringService(conn)
    t = a.propose_topic("p", "t", "Theme")["topic"]["item_uid"]
    a.create_mvp("p", "M1", "first", topic_uid=t)
    s = SurveyService(conn).survey("p")
    assert {"topics", "changelog_tail", "specs_by_status", "health"} <= set(s)
    assert s["changelog_tail"][0]["mvp_id"] == "M1"


def test_authoring_context_and_brief(conn):
    from architectural_knowledge_db.services.authoring import AuthoringService
    from architectural_knowledge_db.services.survey import SurveyService
    add_project(conn, "p")
    a = AuthoringService(conn)
    t = a.propose_topic("p", "t", "Theme")["topic"]["item_uid"]
    a.create_mvp("p", "M1", "first", topic_uid=t)
    ctx = SurveyService(conn).spec_authoring_context("p", t, archetype="plugin")
    assert ctx["contract"]["file_map"] == "required" and ctx["timeline"]
    brief = SurveyService(conn).brief("p", t)
    assert {"what", "key_decisions", "lineage", "open_questions", "blind_spots"} <= set(brief)
