-- Auto-export / always-fresh mirror: registered export targets + dirty tracking queue.
CREATE TABLE IF NOT EXISTS export_targets (
    project_id    TEXT        NOT NULL,
    target_id     TEXT        NOT NULL,
    repository_id TEXT        NOT NULL,
    dest_root     TEXT        NOT NULL,
    layout        TEXT        NOT NULL,
    content_kinds JSONB       NOT NULL,
    auto_export   BOOLEAN     NOT NULL DEFAULT TRUE,
    enabled       BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, target_id)
);

CREATE TABLE IF NOT EXISTS export_dirty (
    id         BIGSERIAL   PRIMARY KEY,
    project_id TEXT        NOT NULL,
    target_id  TEXT,
    item_kind  TEXT        NOT NULL,
    item_ref   TEXT        NOT NULL,
    op         TEXT        NOT NULL,
    marked_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_export_dirty_scope ON export_dirty(project_id, target_id);
