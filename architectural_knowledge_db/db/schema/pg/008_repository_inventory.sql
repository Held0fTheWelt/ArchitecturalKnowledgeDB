-- Workspace / multi-repo cross-reference resolution (autark AKDB capability).
-- Path inventory per registered repository, so resolve_reference() can answer
-- <repo>/<path>#<anchor> from the DB alone -- the target repo need not be checked out.
CREATE TABLE IF NOT EXISTS repository_files (
  repository_id TEXT NOT NULL,
  path TEXT NOT NULL,
  anchors_json TEXT NOT NULL DEFAULT '[]',
  PRIMARY KEY (repository_id, path),
  FOREIGN KEY (repository_id) REFERENCES repositories(repository_id)
);
CREATE INDEX IF NOT EXISTS idx_repository_files_repo ON repository_files (repository_id);

CREATE TABLE IF NOT EXISTS repository_inventory_meta (
  repository_id TEXT PRIMARY KEY,
  head_sha TEXT,
  scanned_at TEXT,
  FOREIGN KEY (repository_id) REFERENCES repositories(repository_id)
);
