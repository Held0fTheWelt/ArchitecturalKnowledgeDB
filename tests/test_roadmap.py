from __future__ import annotations

from tests.conftest import add_project


def test_roadmap_orders_by_seq(conn):
    from architectural_knowledge_db.services.authoring import AuthoringService
    from architectural_knowledge_db.services.roadmap import RoadmapService
    add_project(conn, "p")
    a = AuthoringService(conn)
    a.create_mvp("p", "M1", "first")
    a.create_mvp("p", "M2", "second")
    rm = RoadmapService(conn).roadmap("p")
    assert [e["mvp_id"] for e in rm] == ["M1", "M2"]
    assert [e["seq"] for e in rm] == [1, 2]
