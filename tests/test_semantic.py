from __future__ import annotations

from tests.conftest import add_project, catalog_table_names


class _StubEmbed:
    # deterministic 2-d vectors keyed by substring, no network
    def embed(self, texts):
        return [[1.0, 0.0] if "alpha" in t.lower() else [0.0, 1.0] for t in texts]


def test_item_embeddings_table_exists(conn):
    assert "item_embeddings" in catalog_table_names(conn)


def test_fts_backend_resolves(conn):
    from architectural_knowledge_db.models import AdrInput
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    from architectural_knowledge_db.services.recall_backend import FtsBackend
    add_project(conn, "p")
    uid = KnowledgeService(conn).upsert_adr("p", AdrInput(adr_id="A", title="Boundary"))["item_uid"]
    ranked = FtsBackend(conn).resolve("p", "Boundary", None, 5)
    assert ranked and ranked[0][0] == uid and ranked[0][1] > 0


def test_vector_backend_ranks_by_similarity(conn):
    from architectural_knowledge_db.models import AdrInput
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    from architectural_knowledge_db.services.recall_backend import VectorBackend
    add_project(conn, "p")
    ks = KnowledgeService(conn)
    a = ks.upsert_adr("p", AdrInput(adr_id="A", title="alpha topic"))["item_uid"]
    ks.upsert_adr("p", AdrInput(adr_id="B", title="beta topic"))
    vb = VectorBackend(conn, _StubEmbed(), model="stub")
    vb.embed_project("p")
    ranked = vb.resolve("p", "alpha please", None, 5)
    assert ranked[0][0] == a   # query embeds to alpha-vector → A first


def test_recall_semantic_falls_back_without_backend(conn):
    from architectural_knowledge_db.models import AdrInput, RecallRequest
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    from architectural_knowledge_db.services.cognition import CognitionService
    add_project(conn, "p")
    KnowledgeService(conn).upsert_adr("p", AdrInput(adr_id="A", title="alpha topic"))
    out = CognitionService(conn).recall("p", RecallRequest(query="alpha", semantic=True))  # no backend
    assert out["concepts"]  # FTS still resolves; no crash


def test_recall_hybrid_uses_backend(conn):
    from architectural_knowledge_db.models import AdrInput, RecallRequest
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    from architectural_knowledge_db.services.cognition import CognitionService
    from architectural_knowledge_db.services.recall_backend import VectorBackend
    add_project(conn, "p")
    ks = KnowledgeService(conn)
    a = ks.upsert_adr("p", AdrInput(adr_id="A", title="alpha topic"))["item_uid"]
    vb = VectorBackend(conn, _StubEmbed(), model="stub")
    vb.embed_project("p")
    cog = CognitionService(conn, backend=vb)
    out = cog.recall("p", RecallRequest(query="alpha please", semantic=True))
    assert a in [c["item_uid"] for c in out["concepts"]]


def test_mcp_embed_project_noops_without_backend(conn):
    from architectural_knowledge_db.mcp import McpDispatcher, MCP_MANIFEST
    add_project(conn, "p")
    names = {t["name"] for t in MCP_MANIFEST["tools"]}
    assert "akdb_embed_project" in names
    out = McpDispatcher(conn).dispatch("akdb_embed_project", {"project_id": "p"})
    assert out == {"embedded": 0, "backend": "none"}
