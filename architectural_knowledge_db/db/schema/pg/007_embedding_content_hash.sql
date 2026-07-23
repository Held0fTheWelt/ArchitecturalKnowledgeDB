-- MVP-6 incremental embedding (SAD §7.1 improvement).
-- Stores the hash of the embedded text so embed_project can skip items whose
-- content is unchanged and re-embed only changed ones. Additive: existing rows
-- get NULL and are re-embedded (and hashed) on the next run.
ALTER TABLE item_embeddings ADD COLUMN content_hash TEXT;
