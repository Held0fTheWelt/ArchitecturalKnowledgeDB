from __future__ import annotations

import struct

from tests.conftest import add_project


class _StubEmbed:
    # deterministic 2-d vectors keyed by substring, no network
    def embed(self, texts):
        return [[1.0, 0.0] if "alpha" in t.lower() else [0.0, 1.0] for t in texts]


def test_vector_backend_ignores_other_model_embeddings(conn):
    """resolve() must score only the currently-configured model's vectors.

    Cross-space recall / a model switch can leave the table holding vectors
    from a different embedding space (often a different dim). Without a model
    filter those rows are cosine-compared anyway: a dim mismatch silently
    scores 0.0 (garbage, not an error) and a same-dim other-model row scores
    meaningless similarity. resolve() must exclude foreign-model rows.
    """
    from architectural_knowledge_db.models import AdrInput
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    from architectural_knowledge_db.services.recall_backend import VectorBackend

    add_project(conn, "p")
    ks = KnowledgeService(conn)
    a = ks.upsert_adr("p", AdrInput(adr_id="A", title="alpha topic"))["item_uid"]
    b = ks.upsert_adr("p", AdrInput(adr_id="B", title="beta topic"))["item_uid"]

    vb = VectorBackend(conn, _StubEmbed(), model="m1")
    vb.embed_project("p")  # embeds A and B under model m1, dim 2

    # Simulate a foreign-model embedding for B (different model + dim) as a
    # cross-space / model-switch would produce.
    conn.execute("DELETE FROM item_embeddings WHERE item_uid = ?", (b,))
    conn.execute(
        "INSERT INTO item_embeddings(item_uid, model, dim, vector) VALUES (?, ?, ?, ?)",
        (b, "m2", 3, struct.pack("3f", 0.1, 0.2, 0.3)),
    )
    conn.commit()

    ranked_uids = [uid for uid, _ in vb.resolve("p", "alpha please", None, 5)]
    assert a in ranked_uids          # current-model item is present
    assert b not in ranked_uids      # foreign-model item is excluded, not scored 0.0


class _CapturingUrlopen:
    """Replaces urllib.request.urlopen: captures the Request, returns a canned embedding response."""

    def __init__(self):
        self.request = None

    def __call__(self, request, timeout=None):
        import json

        self.request = request

        class _Resp:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *exc):
                return False

            def read(self_inner):
                return json.dumps({"embeddings": [[1.0, 2.0]]}).encode("utf-8")

        return _Resp()


def test_embedding_client_sends_bearer_token_when_configured(monkeypatch):
    """A UCM/UMCP route (the SAD's named target) requires a Bearer token; the
    client must send Authorization when a token is configured."""
    import urllib.request

    from architectural_knowledge_db.services.recall_backend import LLMStoreEmbeddingClient

    capture = _CapturingUrlopen()
    monkeypatch.setattr(urllib.request, "urlopen", capture)

    client = LLMStoreEmbeddingClient("http://bridge/embeddings", "m", token="secret-tok")
    result = client.embed(["hello"])

    assert result == [[1.0, 2.0]]
    assert capture.request.get_header("Authorization") == "Bearer secret-tok"


def test_embedding_client_omits_auth_when_no_token(monkeypatch):
    """The local autark case has no token: no Authorization header is sent."""
    import urllib.request

    from architectural_knowledge_db.services.recall_backend import LLMStoreEmbeddingClient

    capture = _CapturingUrlopen()
    monkeypatch.setattr(urllib.request, "urlopen", capture)

    client = LLMStoreEmbeddingClient("http://bridge/embeddings", "m")
    client.embed(["hello"])

    assert capture.request.get_header("Authorization") is None


def test_backend_from_env_passes_token(conn, monkeypatch):
    """_backend_from_env wires AKDB_EMBED_TOKEN into the embedding client."""
    from architectural_knowledge_db.mcp import _backend_from_env

    monkeypatch.setenv("AKDB_RECALL_BACKEND", "vector")
    monkeypatch.setenv("AKDB_EMBED_URL", "http://bridge/embeddings")
    monkeypatch.setenv("AKDB_EMBED_TOKEN", "env-tok")

    backend = _backend_from_env(conn)
    assert backend is not None
    assert backend.client.token == "env-tok"


class _RecordingEmbed:
    """Records the length of each embed() call so batching can be observed."""

    def __init__(self):
        self.calls: list[int] = []

    def embed(self, texts):
        self.calls.append(len(texts))
        return [[1.0, 0.0] for _ in texts]


def _add_adrs(conn, n):
    from architectural_knowledge_db.models import AdrInput
    from architectural_knowledge_db.services.knowledge import KnowledgeService

    ks = KnowledgeService(conn)
    return [ks.upsert_adr("p", AdrInput(adr_id=f"A{i}", title=f"topic {i}"))["item_uid"] for i in range(n)]


def test_embed_project_batches_requests(conn):
    """embed_project must batch items into few requests, not one HTTP call per item."""
    from architectural_knowledge_db.services.recall_backend import VectorBackend

    add_project(conn, "p")
    _add_adrs(conn, 3)
    stub = _RecordingEmbed()
    VectorBackend(conn, stub, model="m").embed_project("p")
    assert stub.calls == [3]  # one batched request for 3 items, not [1, 1, 1]


def test_embed_project_skips_unchanged(conn):
    """A re-run must skip items already embedded for the current model."""
    from architectural_knowledge_db.services.recall_backend import VectorBackend

    add_project(conn, "p")
    _add_adrs(conn, 2)
    stub = _RecordingEmbed()
    vb = VectorBackend(conn, stub, model="m")
    assert vb.embed_project("p")["embedded"] == 2

    second = vb.embed_project("p")
    assert second["embedded"] == 0   # nothing changed → nothing re-embedded
    assert second["skipped"] == 2
    assert stub.calls == [2]          # only the first run issued a request


def test_embed_project_reembeds_changed_content(conn):
    """Skip must be content-aware: a changed title/summary re-embeds the item."""
    from architectural_knowledge_db.models import AdrInput
    from architectural_knowledge_db.services.knowledge import KnowledgeService
    from architectural_knowledge_db.services.recall_backend import VectorBackend

    add_project(conn, "p")
    ks = KnowledgeService(conn)
    ks.upsert_adr("p", AdrInput(adr_id="A", title="original title"))
    vb = VectorBackend(conn, _RecordingEmbed(), model="m")
    assert vb.embed_project("p")["embedded"] == 1

    ks.upsert_adr("p", AdrInput(adr_id="A", title="rewritten title"))  # same item, new content
    second = vb.embed_project("p")
    assert second["embedded"] == 1   # content changed → re-embedded, not skipped


def test_embed_project_force_reembeds_everything(conn):
    """force=True bypasses the skip and re-embeds all items."""
    from architectural_knowledge_db.services.recall_backend import VectorBackend

    add_project(conn, "p")
    _add_adrs(conn, 2)
    vb = VectorBackend(conn, _RecordingEmbed(), model="m")
    assert vb.embed_project("p")["embedded"] == 2

    forced = vb.embed_project("p", force=True)
    assert forced["embedded"] == 2   # unchanged, but force re-embeds
    assert forced["skipped"] == 0


def test_mcp_embed_project_forwards_force_and_reports_skipped(conn):
    """The MCP tool forwards force to the backend and surfaces the skipped count."""
    from architectural_knowledge_db.mcp import McpDispatcher

    class _StubBackend:
        def __init__(self):
            self.last = None

        def embed_project(self, project_id, *, force=False, batch_size=64):
            self.last = {"project_id": project_id, "force": force}
            return {"project_id": project_id, "embedded": 3, "skipped": 5}

    add_project(conn, "p")
    backend = _StubBackend()
    out = McpDispatcher(conn, backend=backend).dispatch(
        "akdb_embed_project", {"project_id": "p", "force": True}
    )
    assert backend.last == {"project_id": "p", "force": True}
    assert out == {"embedded": 3, "skipped": 5, "backend": "vector"}
