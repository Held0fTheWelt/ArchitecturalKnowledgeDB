CREATE TABLE IF NOT EXISTS item_memory (
  item_uid     TEXT PRIMARY KEY REFERENCES knowledge_items(item_uid) ON DELETE CASCADE,
  use_count    INTEGER NOT NULL DEFAULT 0,
  last_used_at TEXT,
  pinned       INTEGER NOT NULL DEFAULT 0,
  salience     REAL NOT NULL DEFAULT 0.0
);
