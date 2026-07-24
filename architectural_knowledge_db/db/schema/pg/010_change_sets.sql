CREATE TABLE IF NOT EXISTS change_items (
  id BIGSERIAL PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  spec_uid TEXT NOT NULL,
  op TEXT NOT NULL CHECK(op IN ('add','modify','supersede','remove')),
  target_kind TEXT NOT NULL CHECK(target_kind IN
    ('sad_decision','sad_section','adr','uml_element','uml_relationship','rule','definition')),
  target_ref TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'proposed'
    CHECK(state IN ('proposed','in_progress','done')),
  note TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(project_id, spec_uid, op, target_kind, target_ref)
);
CREATE INDEX IF NOT EXISTS idx_change_items_state ON change_items(project_id, state);
CREATE INDEX IF NOT EXISTS idx_change_items_spec ON change_items(spec_uid);
