-- MVP-1 cognition layer (design spec 2026-06-22 §6/§10, SAD D6/D9).
-- Links-first / Approach A: relations live in knowledge_links. This index makes
-- neighbourhood traversal by (project_id, link_type) cheap for recall/explore.
CREATE INDEX IF NOT EXISTS idx_links_project_linktype
  ON knowledge_links(project_id, link_type);
