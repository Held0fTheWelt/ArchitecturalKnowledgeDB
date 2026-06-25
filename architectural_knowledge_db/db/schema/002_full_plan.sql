ALTER TABLE uml_diagrams ADD COLUMN raw_source TEXT;
ALTER TABLE uml_diagrams ADD COLUMN diagram_kind TEXT NOT NULL DEFAULT 'unknown';

CREATE TABLE IF NOT EXISTS consistency_findings (
  finding_uid TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  finding_type TEXT NOT NULL,
  target_ref TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'info',
  message TEXT NOT NULL,
  evidence_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(project_id) REFERENCES projects(project_id)
);

CREATE INDEX IF NOT EXISTS idx_consistency_project_type
  ON consistency_findings(project_id, finding_type, severity);

CREATE INDEX IF NOT EXISTS idx_uml_diagrams_project_kind
  ON uml_diagrams(project_id, diagram_kind);
