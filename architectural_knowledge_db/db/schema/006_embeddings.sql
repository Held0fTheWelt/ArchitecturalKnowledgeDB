CREATE TABLE IF NOT EXISTS item_embeddings (
  item_uid TEXT PRIMARY KEY REFERENCES knowledge_items(item_uid) ON DELETE CASCADE,
  model    TEXT NOT NULL,
  dim      INTEGER NOT NULL,
  vector   BLOB NOT NULL
);
