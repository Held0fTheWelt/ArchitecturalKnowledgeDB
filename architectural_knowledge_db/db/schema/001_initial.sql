PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS projects (
  project_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  description TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS knowledge_spaces (
  space_id TEXT PRIMARY KEY,
  project_id TEXT,
  space_type TEXT NOT NULL CHECK(space_type IN ('project','shared','archive')),
  display_name TEXT NOT NULL,
  description TEXT,
  FOREIGN KEY(project_id) REFERENCES projects(project_id)
);

CREATE TABLE IF NOT EXISTS project_imports (
  project_id TEXT NOT NULL,
  imported_space_id TEXT NOT NULL,
  import_policy TEXT NOT NULL DEFAULT 'read_only',
  PRIMARY KEY(project_id, imported_space_id),
  FOREIGN KEY(project_id) REFERENCES projects(project_id),
  FOREIGN KEY(imported_space_id) REFERENCES knowledge_spaces(space_id)
);

CREATE TABLE IF NOT EXISTS repositories (
  repository_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  local_path TEXT NOT NULL,
  remote_url_sanitized TEXT,
  default_branch TEXT,
  scan_policy TEXT NOT NULL DEFAULT 'manual',
  include_patterns_json TEXT NOT NULL DEFAULT '[]',
  exclude_patterns_json TEXT NOT NULL DEFAULT '[]',
  last_scanned_at TEXT,
  last_scan_status TEXT,
  FOREIGN KEY(project_id) REFERENCES projects(project_id)
);

CREATE TABLE IF NOT EXISTS knowledge_items (
  item_uid TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  space_id TEXT NOT NULL,
  item_type TEXT NOT NULL,
  local_id TEXT NOT NULL,
  title TEXT,
  status TEXT,
  authority_level TEXT NOT NULL DEFAULT 'project_note',
  summary TEXT,
  source_uri TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(project_id, item_type, local_id),
  FOREIGN KEY(project_id) REFERENCES projects(project_id),
  FOREIGN KEY(space_id) REFERENCES knowledge_spaces(space_id)
);

CREATE TABLE IF NOT EXISTS adrs (
  item_uid TEXT PRIMARY KEY,
  adr_id TEXT NOT NULL,
  status TEXT NOT NULL,
  context_md TEXT,
  decision_md TEXT,
  consequences_md TEXT,
  supersedes_json TEXT NOT NULL DEFAULT '[]',
  superseded_by_json TEXT NOT NULL DEFAULT '[]',
  raw_source TEXT,
  sections_json TEXT NOT NULL DEFAULT '[]',
  FOREIGN KEY(item_uid) REFERENCES knowledge_items(item_uid) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS definitions (
  item_uid TEXT PRIMARY KEY,
  term TEXT NOT NULL,
  canonical_meaning TEXT NOT NULL,
  anti_meanings_json TEXT NOT NULL DEFAULT '[]',
  examples_json TEXT NOT NULL DEFAULT '[]',
  FOREIGN KEY(item_uid) REFERENCES knowledge_items(item_uid) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS rules (
  item_uid TEXT PRIMARY KEY,
  rule_id TEXT NOT NULL,
  severity TEXT NOT NULL DEFAULT 'normal',
  rule_text TEXT NOT NULL,
  applies_to_json TEXT NOT NULL DEFAULT '[]',
  forbidden_changes_json TEXT NOT NULL DEFAULT '[]',
  FOREIGN KEY(item_uid) REFERENCES knowledge_items(item_uid) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS uml_diagrams (
  diagram_uid TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  space_id TEXT NOT NULL,
  diagram_id TEXT NOT NULL,
  title TEXT NOT NULL,
  notation TEXT NOT NULL CHECK(notation IN ('plantuml','mermaid','drawio','internal')),
  source_uri TEXT,
  model_json TEXT NOT NULL DEFAULT '{}',
  last_model_update_at TEXT,
  UNIQUE(project_id, diagram_id),
  FOREIGN KEY(project_id) REFERENCES projects(project_id),
  FOREIGN KEY(space_id) REFERENCES knowledge_spaces(space_id)
);

CREATE TABLE IF NOT EXISTS uml_elements (
  element_uid TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  diagram_uid TEXT,
  element_id TEXT NOT NULL,
  element_type TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(project_id, element_id),
  FOREIGN KEY(project_id) REFERENCES projects(project_id),
  FOREIGN KEY(diagram_uid) REFERENCES uml_diagrams(diagram_uid)
);

CREATE TABLE IF NOT EXISTS uml_relationships (
  relationship_uid TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  source_element_uid TEXT NOT NULL,
  target_element_uid TEXT NOT NULL,
  relationship_type TEXT NOT NULL,
  label TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY(project_id) REFERENCES projects(project_id),
  FOREIGN KEY(source_element_uid) REFERENCES uml_elements(element_uid),
  FOREIGN KEY(target_element_uid) REFERENCES uml_elements(element_uid)
);

CREATE TABLE IF NOT EXISTS source_areas (
  source_area_uid TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  repository_id TEXT,
  source_area_id TEXT NOT NULL,
  title TEXT NOT NULL,
  path_patterns_json TEXT NOT NULL DEFAULT '[]',
  description TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(project_id, source_area_id),
  FOREIGN KEY(project_id) REFERENCES projects(project_id),
  FOREIGN KEY(repository_id) REFERENCES repositories(repository_id)
);

CREATE TABLE IF NOT EXISTS knowledge_links (
  link_uid TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  source_item_uid TEXT NOT NULL,
  target_ref TEXT NOT NULL,
  link_type TEXT NOT NULL,
  authority_level TEXT NOT NULL DEFAULT 'evidence',
  confidence TEXT NOT NULL DEFAULT 'explicit',
  evidence TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY(project_id) REFERENCES projects(project_id),
  FOREIGN KEY(source_item_uid) REFERENCES knowledge_items(item_uid)
);

CREATE TABLE IF NOT EXISTS git_commits (
  commit_uid TEXT PRIMARY KEY,
  repository_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  commit_hash TEXT NOT NULL,
  short_hash TEXT NOT NULL,
  committed_at TEXT NOT NULL,
  author_name TEXT,
  author_email_hash TEXT,
  message_subject TEXT,
  message_body TEXT,
  is_merge INTEGER NOT NULL DEFAULT 0,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(repository_id, commit_hash),
  FOREIGN KEY(repository_id) REFERENCES repositories(repository_id),
  FOREIGN KEY(project_id) REFERENCES projects(project_id)
);

CREATE TABLE IF NOT EXISTS git_commit_files (
  commit_file_uid TEXT PRIMARY KEY,
  commit_uid TEXT NOT NULL,
  repository_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  file_path TEXT NOT NULL,
  previous_path TEXT,
  change_type TEXT NOT NULL DEFAULT 'unknown',
  additions INTEGER,
  deletions INTEGER,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY(commit_uid) REFERENCES git_commits(commit_uid) ON DELETE CASCADE,
  FOREIGN KEY(repository_id) REFERENCES repositories(repository_id),
  FOREIGN KEY(project_id) REFERENCES projects(project_id)
);

CREATE TABLE IF NOT EXISTS git_file_history (
  file_history_uid TEXT PRIMARY KEY,
  repository_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  file_path TEXT NOT NULL,
  first_seen_commit_hash TEXT,
  first_seen_at TEXT,
  last_changed_commit_hash TEXT,
  last_changed_at TEXT,
  change_count INTEGER NOT NULL DEFAULT 0,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(repository_id, file_path),
  FOREIGN KEY(repository_id) REFERENCES repositories(repository_id),
  FOREIGN KEY(project_id) REFERENCES projects(project_id)
);

CREATE TABLE IF NOT EXISTS staleness_reports (
  report_uid TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  target_ref TEXT NOT NULL,
  target_type TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('current','watch','review_recommended','likely_stale','unknown')),
  reason TEXT,
  evidence_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(project_id) REFERENCES projects(project_id)
);

CREATE TABLE IF NOT EXISTS context_pack_runs (
  context_pack_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  task TEXT NOT NULL,
  request_json TEXT NOT NULL,
  response_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(project_id) REFERENCES projects(project_id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS fts_knowledge USING fts5(
  item_uid UNINDEXED,
  project_id UNINDEXED,
  item_type UNINDEXED,
  title,
  body,
  tokenize = 'porter unicode61'
);

CREATE INDEX IF NOT EXISTS idx_knowledge_project_type ON knowledge_items(project_id, item_type);
CREATE INDEX IF NOT EXISTS idx_knowledge_space ON knowledge_items(space_id);
CREATE INDEX IF NOT EXISTS idx_git_commits_project_repo ON git_commits(project_id, repository_id, committed_at);
CREATE INDEX IF NOT EXISTS idx_git_files_project_path ON git_commit_files(project_id, file_path);
CREATE INDEX IF NOT EXISTS idx_source_areas_project ON source_areas(project_id);
CREATE INDEX IF NOT EXISTS idx_links_project_source ON knowledge_links(project_id, source_item_uid);
CREATE INDEX IF NOT EXISTS idx_links_project_target ON knowledge_links(project_id, target_ref);
