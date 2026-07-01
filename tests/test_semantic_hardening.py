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
