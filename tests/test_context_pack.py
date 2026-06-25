from __future__ import annotations

from architectural_knowledge_db.models import AdrInput, ContextPackRequest, RuleInput, SourceAreaInput
from architectural_knowledge_db.services.context import ContextPackBuilder
from architectural_knowledge_db.services.knowledge import KnowledgeService
from tests.conftest import add_project


def test_context_pack_separates_normative_items_from_evidence(conn) -> None:
    add_project(conn, "akdb")
    knowledge = KnowledgeService(conn)
    knowledge.upsert_adr(
        "akdb",
        AdrInput(
            adr_id="ADR-0002",
            title="DB First",
            status="accepted",
            decision_md="SQLite is the primary local state.",
        ),
    )
    knowledge.upsert_rule(
        "akdb",
        RuleInput(
            rule_id="db-first",
            rule_text="Do not replace DB primary state with file-only logic.",
            severity="high",
            applies_to=["architectural_knowledge_db/services/knowledge.py"],
        ),
    )
    knowledge.upsert_source_area(
        "akdb",
        SourceAreaInput(
            source_area_id="knowledge-store",
            title="Knowledge Store",
            path_patterns=["architectural_knowledge_db/services/knowledge.py"],
            description="Persistence layer.",
        ),
    )

    pack = ContextPackBuilder(conn).build(
        "akdb",
        ContextPackRequest(
            task="Modify SQLite knowledge store",
            source_paths=["architectural_knowledge_db/services/knowledge.py"],
        ),
    )

    assert [item["local_id"] for item in pack["accepted_adrs"]] == ["ADR-0002"]
    assert [item["local_id"] for item in pack["active_rules"]] == ["db-first"]
    assert [item["local_id"] for item in pack["source_areas"]] == ["knowledge-store"]
    assert pack["accepted_adrs"][0]["authority_kind"] == "normative"
    assert pack["source_areas"][0]["authority_kind"] == "evidence"


def test_validate_task_context_reports_forbidden_change(conn) -> None:
    add_project(conn, "akdb")
    KnowledgeService(conn).upsert_rule(
        "akdb",
        RuleInput(
            rule_id="db-first",
            rule_text="Do not replace DB primary state with file-only logic.",
            forbidden_changes=["file-only"],
        ),
    )

    result = ContextPackBuilder(conn).validate_task_context("akdb", "Switch to file-only ADR storage")

    assert result["verdict"] == "review"
    assert result["findings"][0]["item_uid"] == "akdb:rule:db-first"


def test_validate_task_context_surfaces_relevant_adr_as_advisory(conn) -> None:
    # An accepted ADR whose decision conflicts with the task — but encoded as
    # prose, not a rule forbidden_changes list. validate must still flag it.
    add_project(conn, "akdb")
    KnowledgeService(conn).upsert_adr(
        "akdb",
        AdrInput(
            adr_id="ADR-0009",
            title="Index Service Boundary",
            status="accepted",
            decision_md="The index service must remain read-only and must never become a mutation authority.",
        ),
    )

    result = ContextPackBuilder(conn).validate_task_context(
        "akdb", "Convert the index service into a mutation authority that writes files"
    )

    assert result["verdict"] == "review_advised"
    advisory = [f for f in result["findings"] if f.get("kind") == "advisory"]
    assert any(f["item_uid"] == "akdb:adr:ADR-0009" for f in advisory)


def test_validate_task_context_clean_when_unrelated(conn) -> None:
    add_project(conn, "akdb")
    KnowledgeService(conn).upsert_adr(
        "akdb",
        AdrInput(
            adr_id="ADR-0010",
            title="Logging Format",
            status="accepted",
            decision_md="Use structured JSON logs for the telemetry pipeline.",
        ),
    )

    result = ContextPackBuilder(conn).validate_task_context(
        "akdb", "Add a new keyboard shortcut to the colour picker widget"
    )

    assert result["verdict"] == "no_known_conflict"
    assert result["findings"] == []


def test_context_pack_routes_active_rule_authority_records(conn) -> None:
    add_project(conn, "akdb")
    knowledge = KnowledgeService(conn)
    item_uid = knowledge._upsert_item(
        project_id="akdb",
        space_id=None,
        item_type="sad_decision",
        local_id="demo:decision:d1",
        title="D1: Route Governance",
        status="accepted",
        authority_level="active_rule",
        summary="Route governance requires explicit approval.",
        source_uri=None,
        metadata={},
    )
    knowledge._index_item(item_uid)

    pack = ContextPackBuilder(conn).build("akdb", ContextPackRequest(task="Review route governance"))

    assert [item["local_id"] for item in pack["active_rules"]] == ["demo:decision:d1"]
