CREATE TABLE IF NOT EXISTS topics (
  item_uid  TEXT PRIMARY KEY REFERENCES knowledge_items(item_uid) ON DELETE CASCADE,
  topic_id  TEXT NOT NULL,
  lifecycle TEXT NOT NULL DEFAULT 'active' CHECK(lifecycle IN ('active','dormant','closed'))
);
CREATE TABLE IF NOT EXISTS mvps (
  item_uid   TEXT PRIMARY KEY REFERENCES knowledge_items(item_uid) ON DELETE CASCADE,
  mvp_id     TEXT NOT NULL,
  seq        INTEGER NOT NULL,
  lifecycle  TEXT NOT NULL DEFAULT 'planned'
             CHECK(lifecycle IN ('planned','in_progress','shipped','superseded')),
  intent_md  TEXT,
  shipped_at TEXT
);
CREATE TABLE IF NOT EXISTS specs (
  item_uid      TEXT PRIMARY KEY REFERENCES knowledge_items(item_uid) ON DELETE CASCADE,
  spec_id       TEXT NOT NULL,
  archetype     TEXT NOT NULL CHECK(archetype IN ('plugin','function','rule')),
  lifecycle     TEXT NOT NULL DEFAULT 'draft'
                CHECK(lifecycle IN ('draft','ready','implemented','superseded')),
  mvp_uid       TEXT REFERENCES knowledge_items(item_uid),
  sections_json TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS questions (
  item_uid    TEXT PRIMARY KEY REFERENCES knowledge_items(item_uid) ON DELETE CASCADE,
  question_id TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','answered','wontfix'))
);
CREATE INDEX IF NOT EXISTS idx_mvps_seq ON mvps(seq);
