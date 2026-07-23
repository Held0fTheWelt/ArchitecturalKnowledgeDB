-- Auto-export / always-fresh mirror: registered export targets + dirty tracking queue.
CREATE TABLE IF NOT EXISTS export_targets (
    project_id    TEXT    NOT NULL,
    target_id     TEXT    NOT NULL,
    repository_id TEXT    NOT NULL,
    dest_root     TEXT    NOT NULL,
    layout        TEXT    NOT NULL,
    content_kinds TEXT    NOT NULL,                 -- JSON array of item kinds
    auto_export   INTEGER NOT NULL DEFAULT 1,
    enabled       INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (project_id, target_id)
);

CREATE TABLE IF NOT EXISTS export_dirty (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT    NOT NULL,
    target_id  TEXT,                                -- NULL = all targets of the project
    item_kind  TEXT    NOT NULL,                    -- sad|sad_section|sad_decision|uml|adr|document
    item_ref   TEXT    NOT NULL,                    -- stable id or repo_source_key
    op         TEXT    NOT NULL,                    -- upsert|delete
    marked_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_export_dirty_scope ON export_dirty(project_id, target_id);
