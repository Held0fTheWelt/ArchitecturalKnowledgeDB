from __future__ import annotations

import fnmatch
import re
import sqlite3
from typing import Any

from architectural_knowledge_db.ids import digest_uid, stable_uid
from architectural_knowledge_db.models import (
    AdrInput,
    DefinitionInput,
    KnowledgeLinkInput,
    MvpInput,
    QuestionInput,
    RuleInput,
    SourceAreaInput,
    SpecInput,
    TopicInput,
)
from architectural_knowledge_db.services.jsonutil import dumps, loads
from architectural_knowledge_db.services.projects import ProjectService, project_space_id


class KnowledgeService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.projects = ProjectService(conn)

    def upsert_adr(self, project_id: str, adr: AdrInput, space_id: str | None = None) -> dict[str, Any]:
        item_uid = self._upsert_item(
            project_id=project_id,
            space_id=space_id,
            item_type="adr",
            local_id=adr.adr_id,
            title=adr.title,
            status=adr.status,
            authority_level=adr.authority_level,
            summary=adr.summary,
            source_uri=adr.source_uri,
            metadata=adr.metadata,
        )
        self.conn.execute(
            """
            INSERT INTO adrs(
              item_uid, adr_id, status, context_md, decision_md, consequences_md,
              supersedes_json, superseded_by_json, raw_source, sections_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_uid) DO UPDATE SET
              adr_id = excluded.adr_id,
              status = excluded.status,
              context_md = excluded.context_md,
              decision_md = excluded.decision_md,
              consequences_md = excluded.consequences_md,
              supersedes_json = excluded.supersedes_json,
              superseded_by_json = excluded.superseded_by_json,
              raw_source = excluded.raw_source,
              sections_json = excluded.sections_json
            """,
            (
                item_uid,
                adr.adr_id,
                adr.status,
                adr.context_md,
                adr.decision_md,
                adr.consequences_md,
                dumps(adr.supersedes),
                dumps(adr.superseded_by),
                adr.raw_source,
                dumps(adr.sections),
            ),
        )
        self._index_item(item_uid)
        return self.get_adr(project_id, adr.adr_id)

    def list_adrs(self, project_id: str, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        self.projects.require_project(project_id)
        params: list[Any] = [project_id]
        status_clause = ""
        if status:
            status_clause = "AND lower(a.status) = lower(?)"
            params.append(status)
        params.append(limit)
        rows = self.conn.execute(
            f"""
            SELECT ki.*, a.adr_id, a.context_md, a.decision_md, a.consequences_md,
                   a.supersedes_json, a.superseded_by_json, a.raw_source, a.sections_json
            FROM knowledge_items ki
            JOIN adrs a ON a.item_uid = ki.item_uid
            WHERE ki.project_id = ? {status_clause}
            ORDER BY a.adr_id
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [self._hydrate_adr(row) for row in rows]

    def get_adr(self, project_id: str, adr_id: str) -> dict[str, Any]:
        self.projects.require_project(project_id)
        row = self.conn.execute(
            """
            SELECT ki.*, a.adr_id, a.context_md, a.decision_md, a.consequences_md,
                   a.supersedes_json, a.superseded_by_json, a.raw_source, a.sections_json
            FROM knowledge_items ki
            JOIN adrs a ON a.item_uid = ki.item_uid
            WHERE ki.project_id = ? AND ki.item_type = 'adr' AND ki.local_id = ?
            """,
            (project_id, adr_id),
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown ADR in project {project_id}: {adr_id}")
        return self._hydrate_adr(row)

    def upsert_rule(self, project_id: str, rule: RuleInput, space_id: str | None = None) -> dict[str, Any]:
        title = rule.title or rule.rule_id
        item_uid = self._upsert_item(
            project_id=project_id,
            space_id=space_id,
            item_type="rule",
            local_id=rule.rule_id,
            title=title,
            status="active",
            authority_level=rule.authority_level,
            summary=rule.summary,
            source_uri=rule.source_uri,
            metadata=rule.metadata,
        )
        self.conn.execute(
            """
            INSERT INTO rules(item_uid, rule_id, severity, rule_text, applies_to_json, forbidden_changes_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_uid) DO UPDATE SET
              rule_id = excluded.rule_id,
              severity = excluded.severity,
              rule_text = excluded.rule_text,
              applies_to_json = excluded.applies_to_json,
              forbidden_changes_json = excluded.forbidden_changes_json
            """,
            (
                item_uid,
                rule.rule_id,
                rule.severity,
                rule.rule_text,
                dumps(rule.applies_to),
                dumps(rule.forbidden_changes),
            ),
        )
        self._index_item(item_uid)
        return self.get_item_by_uid(item_uid)

    def upsert_definition(
        self, project_id: str, definition: DefinitionInput, space_id: str | None = None
    ) -> dict[str, Any]:
        item_uid = self._upsert_item(
            project_id=project_id,
            space_id=space_id,
            item_type="definition",
            local_id=definition.term,
            title=definition.term,
            status="active",
            authority_level=definition.authority_level,
            summary=definition.summary,
            source_uri=definition.source_uri,
            metadata=definition.metadata,
        )
        self.conn.execute(
            """
            INSERT INTO definitions(item_uid, term, canonical_meaning, anti_meanings_json, examples_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(item_uid) DO UPDATE SET
              term = excluded.term,
              canonical_meaning = excluded.canonical_meaning,
              anti_meanings_json = excluded.anti_meanings_json,
              examples_json = excluded.examples_json
            """,
            (
                item_uid,
                definition.term,
                definition.canonical_meaning,
                dumps(definition.anti_meanings),
                dumps(definition.examples),
            ),
        )
        self._index_item(item_uid)
        return self.get_item_by_uid(item_uid)

    def upsert_source_area(
        self, project_id: str, source_area: SourceAreaInput, space_id: str | None = None
    ) -> dict[str, Any]:
        item_uid = self._upsert_item(
            project_id=project_id,
            space_id=space_id,
            item_type="source_area",
            local_id=source_area.source_area_id,
            title=source_area.title,
            status="active",
            authority_level=source_area.authority_level,
            summary=source_area.description,
            source_uri=None,
            metadata=source_area.metadata,
        )
        source_area_uid = stable_uid(project_id, "source_area_record", source_area.source_area_id)
        self.conn.execute(
            """
            INSERT INTO source_areas(
              source_area_uid, project_id, repository_id, source_area_id, title,
              path_patterns_json, description, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, source_area_id) DO UPDATE SET
              repository_id = excluded.repository_id,
              title = excluded.title,
              path_patterns_json = excluded.path_patterns_json,
              description = excluded.description,
              metadata_json = excluded.metadata_json
            """,
            (
                source_area_uid,
                project_id,
                source_area.repository_id,
                source_area.source_area_id,
                source_area.title,
                dumps(source_area.path_patterns),
                source_area.description,
                dumps(source_area.metadata | {"item_uid": item_uid}),
            ),
        )
        self._index_item(item_uid)
        return self.get_item_by_uid(item_uid)

    def upsert_topic(self, project_id: str, topic: TopicInput, space_id: str | None = None) -> dict[str, Any]:
        item_uid = self._upsert_item(
            project_id=project_id, space_id=space_id, item_type="topic", local_id=topic.topic_id,
            title=topic.title, status=topic.lifecycle, authority_level="project_note",
            summary=topic.summary, source_uri=None, metadata=topic.metadata,
        )
        self.conn.execute(
            """
            INSERT INTO topics(item_uid, topic_id, lifecycle)
            VALUES (?, ?, ?)
            ON CONFLICT(item_uid) DO UPDATE SET
              topic_id=excluded.topic_id, lifecycle=excluded.lifecycle
            """,
            (item_uid, topic.topic_id, topic.lifecycle),
        )
        self._index_item(item_uid)
        return self.get_item_by_uid(item_uid)

    def upsert_mvp(self, project_id: str, mvp: MvpInput, space_id: str | None = None) -> dict[str, Any]:
        item_uid = self._upsert_item(
            project_id=project_id, space_id=space_id, item_type="mvp", local_id=mvp.mvp_id,
            title=mvp.title, status=mvp.lifecycle, authority_level="project_note",
            summary=mvp.summary, source_uri=None, metadata=mvp.metadata,
        )
        self.conn.execute(
            """
            INSERT INTO mvps(item_uid, mvp_id, seq, lifecycle, intent_md, shipped_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_uid) DO UPDATE SET
              mvp_id=excluded.mvp_id, seq=excluded.seq, lifecycle=excluded.lifecycle,
              intent_md=excluded.intent_md, shipped_at=excluded.shipped_at
            """,
            (item_uid, mvp.mvp_id, mvp.seq, mvp.lifecycle, mvp.intent_md, mvp.shipped_at),
        )
        self._index_item(item_uid)
        return self.get_item_by_uid(item_uid)

    def upsert_spec(self, project_id: str, spec: SpecInput, space_id: str | None = None) -> dict[str, Any]:
        item_uid = self._upsert_item(
            project_id=project_id, space_id=space_id, item_type="spec", local_id=spec.spec_id,
            title=spec.title, status=spec.lifecycle, authority_level="project_note",
            summary=spec.summary, source_uri=None, metadata=spec.metadata,
        )
        self.conn.execute(
            """
            INSERT INTO specs(item_uid, spec_id, archetype, lifecycle, mvp_uid, sections_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_uid) DO UPDATE SET
              spec_id=excluded.spec_id, archetype=excluded.archetype, lifecycle=excluded.lifecycle,
              mvp_uid=excluded.mvp_uid, sections_json=excluded.sections_json
            """,
            (item_uid, spec.spec_id, spec.archetype, spec.lifecycle, spec.mvp_uid, dumps(spec.sections)),
        )
        self._index_item(item_uid)
        return self.get_item_by_uid(item_uid)

    def upsert_question(self, project_id: str, question: QuestionInput, space_id: str | None = None) -> dict[str, Any]:
        item_uid = self._upsert_item(
            project_id=project_id, space_id=space_id, item_type="question", local_id=question.question_id,
            title=question.title, status=question.status, authority_level="project_note",
            summary=question.summary, source_uri=None, metadata=question.metadata,
        )
        self.conn.execute(
            """
            INSERT INTO questions(item_uid, question_id, status)
            VALUES (?, ?, ?)
            ON CONFLICT(item_uid) DO UPDATE SET
              question_id=excluded.question_id, status=excluded.status
            """,
            (item_uid, question.question_id, question.status),
        )
        self._index_item(item_uid)
        return self.get_item_by_uid(item_uid)

    def upsert_link(self, project_id: str, link: KnowledgeLinkInput) -> dict[str, Any]:
        self.projects.require_project(project_id)
        link_uid = digest_uid(
            "link",
            project_id,
            link.source_item_uid,
            link.target_ref,
            link.link_type,
            link.confidence,
        )
        self.conn.execute(
            """
            INSERT INTO knowledge_links(
              link_uid, project_id, source_item_uid, target_ref, link_type,
              authority_level, confidence, evidence, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(link_uid) DO UPDATE SET
              authority_level = excluded.authority_level,
              confidence = excluded.confidence,
              evidence = excluded.evidence,
              metadata_json = excluded.metadata_json
            """,
            (
                link_uid,
                project_id,
                link.source_item_uid,
                link.target_ref,
                link.link_type,
                link.authority_level,
                link.confidence,
                link.evidence,
                dumps(link.metadata),
            ),
        )
        return dict(
            self.conn.execute("SELECT * FROM knowledge_links WHERE link_uid = ?", (link_uid,)).fetchone()
        )

    def get_item_by_uid(self, item_uid: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM knowledge_items WHERE item_uid = ?", (item_uid,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown knowledge item: {item_uid}")
        item = dict(row)
        item["metadata"] = loads(item.pop("metadata_json"), {})
        item["details"] = self._details_for_item(item)
        return item

    def list_items(
        self,
        project_id: str,
        include_types: list[str] | None = None,
        include_shared: bool = True,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        space_ids = self.projects.scope_space_ids(project_id, include_shared=include_shared)
        params: list[Any] = list(space_ids)
        type_clause = ""
        if include_types:
            type_clause = f"AND item_type IN ({','.join('?' for _ in include_types)})"
            params.extend(include_types)
        params.append(limit)
        rows = self.conn.execute(
            f"""
            SELECT *
            FROM knowledge_items
            WHERE space_id IN ({','.join('?' for _ in space_ids)})
              {type_clause}
            ORDER BY
              CASE authority_level
                WHEN 'hard_guardrail' THEN 0
                WHEN 'accepted_adr' THEN 1
                WHEN 'active_rule' THEN 2
                WHEN 'canonical_definition' THEN 3
                WHEN 'current_uml_model' THEN 4
                ELSE 9
              END,
              item_type,
              local_id
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [self.get_item_by_uid(row["item_uid"]) for row in rows]

    def matching_source_areas(self, project_id: str, path: str, include_shared: bool = True) -> list[dict[str, Any]]:
        self.projects.require_project(project_id)
        rows = self.conn.execute(
            """
            SELECT *
            FROM source_areas
            WHERE project_id = ?
            ORDER BY source_area_id
            """,
            (project_id,),
        ).fetchall()
        matches: list[dict[str, Any]] = []
        normalized = normalize_path(path)
        for row in rows:
            patterns = loads(row["path_patterns_json"], [])
            if any(path_matches(pattern, normalized) for pattern in patterns):
                item_uid = loads(row["metadata_json"], {}).get("item_uid")
                area = dict(row)
                area["path_patterns"] = patterns
                area["metadata"] = loads(row["metadata_json"], {})
                if item_uid:
                    area["knowledge_item"] = self.get_item_by_uid(item_uid)
                matches.append(area)
        return matches

    def matching_rules_for_path(self, project_id: str, path: str, include_shared: bool = True) -> list[dict[str, Any]]:
        items = self.list_items(project_id, include_types=["rule"], include_shared=include_shared, limit=500)
        normalized = normalize_path(path)
        matches = []
        for item in items:
            applies_to = item.get("details", {}).get("applies_to", [])
            if not applies_to or any(path_matches(pattern, normalized) for pattern in applies_to):
                matches.append(item)
        return matches

    def rebuild_fts(self, project_id: str) -> dict[str, Any]:
        self.projects.require_project(project_id)
        rows = self.conn.execute(
            "SELECT item_uid FROM knowledge_items WHERE project_id = ?", (project_id,)
        ).fetchall()
        self.conn.execute("DELETE FROM fts_knowledge WHERE project_id = ?", (project_id,))
        for row in rows:
            self._index_item(row["item_uid"])
        return {"project_id": project_id, "indexed_items": len(rows)}

    def _upsert_item(
        self,
        project_id: str,
        space_id: str | None,
        item_type: str,
        local_id: str,
        title: str | None,
        status: str | None,
        authority_level: str,
        summary: str | None,
        source_uri: str | None,
        metadata: dict[str, Any],
    ) -> str:
        self.projects.require_project(project_id)
        resolved_space_id = space_id or project_space_id(project_id)
        if self.conn.execute("SELECT 1 FROM knowledge_spaces WHERE space_id = ?", (resolved_space_id,)).fetchone() is None:
            if resolved_space_id == project_space_id(project_id):
                self.projects.ensure_project_space(project_id)
            else:
                raise ValueError(f"Unknown knowledge space: {resolved_space_id}")
        item_uid = stable_uid(project_id, item_type, local_id)
        self.conn.execute(
            """
            INSERT INTO knowledge_items(
              item_uid, project_id, space_id, item_type, local_id, title, status,
              authority_level, summary, source_uri, metadata_json, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(project_id, item_type, local_id) DO UPDATE SET
              space_id = excluded.space_id,
              title = excluded.title,
              status = excluded.status,
              authority_level = excluded.authority_level,
              summary = excluded.summary,
              source_uri = excluded.source_uri,
              metadata_json = excluded.metadata_json,
              updated_at = CURRENT_TIMESTAMP
            """,
            (
                item_uid,
                project_id,
                resolved_space_id,
                item_type,
                local_id,
                title,
                status,
                authority_level,
                summary,
                source_uri,
                dumps(metadata),
            ),
        )
        row = self.conn.execute(
            """
            SELECT item_uid
            FROM knowledge_items
            WHERE project_id = ? AND item_type = ? AND local_id = ?
            """,
            (project_id, item_type, local_id),
        ).fetchone()
        from architectural_knowledge_db.services.export_flush import notify_item_write

        notify_item_write(self.conn, project_id, item_type, metadata, op="upsert")
        return row["item_uid"]

    def _aliases_for_item(self, item_uid: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT target_ref FROM knowledge_links WHERE source_item_uid = ? AND link_type = 'alias'",
            (item_uid,),
        ).fetchall()
        return [row["target_ref"] for row in rows if row["target_ref"]]

    def _index_item(self, item_uid: str) -> None:
        item = dict(self.conn.execute("SELECT * FROM knowledge_items WHERE item_uid = ?", (item_uid,)).fetchone())
        body = self._body_for_item(item)
        aliases = self._aliases_for_item(item_uid)
        if aliases:
            body = "\n".join([body, *aliases]) if body else "\n".join(aliases)
        self.conn.execute("DELETE FROM fts_knowledge WHERE item_uid = ?", (item_uid,))
        self.conn.execute(
            """
            INSERT INTO fts_knowledge(item_uid, project_id, item_type, title, body)
            VALUES (?, ?, ?, ?, ?)
            """,
            (item_uid, item["project_id"], item["item_type"], item["title"] or "", body),
        )

    def _body_for_item(self, item: dict[str, Any]) -> str:
        body_parts = [item.get("summary") or ""]
        metadata = loads(item.get("metadata_json", "{}"), {})
        if item["item_type"] == "adr":
            row = self.conn.execute("SELECT * FROM adrs WHERE item_uid = ?", (item["item_uid"],)).fetchone()
            if row:
                body_parts.extend(
                    [
                        row["status"] or "",
                        row["context_md"] or "",
                        row["decision_md"] or "",
                        row["consequences_md"] or "",
                    ]
                )
        elif item["item_type"] == "rule":
            row = self.conn.execute("SELECT * FROM rules WHERE item_uid = ?", (item["item_uid"],)).fetchone()
            if row:
                body_parts.extend([row["severity"] or "", row["rule_text"] or ""])
        elif item["item_type"] == "definition":
            row = self.conn.execute("SELECT * FROM definitions WHERE item_uid = ?", (item["item_uid"],)).fetchone()
            if row:
                body_parts.extend([row["term"] or "", row["canonical_meaning"] or ""])
        elif item["item_type"] == "source_area":
            row = self.conn.execute(
                "SELECT * FROM source_areas WHERE project_id = ? AND source_area_id = ?",
                (item["project_id"], item["local_id"]),
            ).fetchone()
            if row:
                body_parts.extend([row["description"] or "", " ".join(loads(row["path_patterns_json"], []))])
        elif item["item_type"] == "uml_diagram":
            row = self.conn.execute(
                "SELECT * FROM uml_diagrams WHERE project_id = ? AND diagram_id = ?",
                (item["project_id"], item["local_id"]),
            ).fetchone()
            if row:
                body_parts.extend([row["diagram_kind"] or "", row["raw_source"] or ""])
        elif item["item_type"] == "uml_element":
            row = self.conn.execute(
                "SELECT * FROM uml_elements WHERE project_id = ? AND element_id = ?",
                (item["project_id"], item["local_id"]),
            ).fetchone()
            if row:
                body_parts.extend([row["element_type"] or "", row["name"] or "", row["description"] or ""])
        elif item["item_type"] == "topic":
            row = self.conn.execute("SELECT * FROM topics WHERE item_uid = ?", (item["item_uid"],)).fetchone()
            if row:
                body_parts.append(row["topic_id"] or "")
        elif item["item_type"] == "mvp":
            row = self.conn.execute("SELECT * FROM mvps WHERE item_uid = ?", (item["item_uid"],)).fetchone()
            if row:
                body_parts.extend([row["mvp_id"] or "", row["intent_md"] or ""])
        elif item["item_type"] == "spec":
            row = self.conn.execute("SELECT * FROM specs WHERE item_uid = ?", (item["item_uid"],)).fetchone()
            if row:
                section_titles = " ".join(str(s.get("title", "")) for s in loads(row["sections_json"], []))
                body_parts.extend([row["spec_id"] or "", row["archetype"] or "", section_titles])
        elif item["item_type"] == "question":
            row = self.conn.execute("SELECT * FROM questions WHERE item_uid = ?", (item["item_uid"],)).fetchone()
            if row:
                body_parts.append(row["question_id"] or "")
        else:
            body_parts.extend(
                [
                    str(metadata.get("source_key") or ""),
                    str(metadata.get("body_md") or ""),
                    " ".join(str(heading.get("title", "")) for heading in metadata.get("headings", [])),
                ]
            )
        return "\n".join(part for part in body_parts if part)

    def _details_for_item(self, item: dict[str, Any]) -> dict[str, Any]:
        item_uid = item["item_uid"]
        if item["item_type"] == "adr":
            row = self.conn.execute("SELECT * FROM adrs WHERE item_uid = ?", (item_uid,)).fetchone()
            return self._hydrate_adr_details(row) if row else {}
        if item["item_type"] == "rule":
            row = self.conn.execute("SELECT * FROM rules WHERE item_uid = ?", (item_uid,)).fetchone()
            if row is None:
                return {}
            return {
                "rule_id": row["rule_id"],
                "severity": row["severity"],
                "rule_text": row["rule_text"],
                "applies_to": loads(row["applies_to_json"], []),
                "forbidden_changes": loads(row["forbidden_changes_json"], []),
            }
        if item["item_type"] == "definition":
            row = self.conn.execute("SELECT * FROM definitions WHERE item_uid = ?", (item_uid,)).fetchone()
            if row is None:
                return {}
            return {
                "term": row["term"],
                "canonical_meaning": row["canonical_meaning"],
                "anti_meanings": loads(row["anti_meanings_json"], []),
                "examples": loads(row["examples_json"], []),
            }
        if item["item_type"] == "source_area":
            row = self.conn.execute(
                "SELECT * FROM source_areas WHERE project_id = ? AND source_area_id = ?",
                (item["project_id"], item["local_id"]),
            ).fetchone()
            if row is None:
                return {}
            return {
                "source_area_id": row["source_area_id"],
                "repository_id": row["repository_id"],
                "path_patterns": loads(row["path_patterns_json"], []),
                "description": row["description"],
            }
        if item["item_type"] == "uml_diagram":
            row = self.conn.execute(
                "SELECT * FROM uml_diagrams WHERE project_id = ? AND diagram_id = ?",
                (item["project_id"], item["local_id"]),
            ).fetchone()
            if row is None:
                return {}
            return {
                "diagram_id": row["diagram_id"],
                "diagram_uid": row["diagram_uid"],
                "diagram_kind": row["diagram_kind"],
                "notation": row["notation"],
                "source_uri": row["source_uri"],
                "model": loads(row["model_json"], {}),
            }
        if item["item_type"] == "uml_element":
            row = self.conn.execute(
                """
                SELECT e.*, d.diagram_id
                FROM uml_elements e
                LEFT JOIN uml_diagrams d ON d.diagram_uid = e.diagram_uid
                WHERE e.project_id = ? AND e.element_id = ?
                """,
                (item["project_id"], item["local_id"]),
            ).fetchone()
            if row is None:
                return {}
            return {
                "diagram_id": row["diagram_id"],
                "diagram_uid": row["diagram_uid"],
                "element_id": row["element_id"],
                "element_type": row["element_type"],
                "name": row["name"],
                "description": row["description"],
                "metadata": loads(row["metadata_json"], {}),
            }
        if item["item_type"] == "topic":
            row = self.conn.execute("SELECT * FROM topics WHERE item_uid = ?", (item_uid,)).fetchone()
            return {"topic_id": row["topic_id"], "lifecycle": row["lifecycle"]} if row else {}
        if item["item_type"] == "mvp":
            row = self.conn.execute("SELECT * FROM mvps WHERE item_uid = ?", (item_uid,)).fetchone()
            if row is None:
                return {}
            return {
                "mvp_id": row["mvp_id"],
                "seq": row["seq"],
                "lifecycle": row["lifecycle"],
                "intent_md": row["intent_md"],
                "shipped_at": row["shipped_at"],
            }
        if item["item_type"] == "spec":
            row = self.conn.execute("SELECT * FROM specs WHERE item_uid = ?", (item_uid,)).fetchone()
            if row is None:
                return {}
            return {
                "spec_id": row["spec_id"],
                "archetype": row["archetype"],
                "lifecycle": row["lifecycle"],
                "mvp_uid": row["mvp_uid"],
                "sections": loads(row["sections_json"], []),
            }
        if item["item_type"] == "question":
            row = self.conn.execute("SELECT * FROM questions WHERE item_uid = ?", (item_uid,)).fetchone()
            return {"question_id": row["question_id"], "status": row["status"]} if row else {}
        if item["item_type"] == "document":
            return item.get("metadata", {})
        return {}

    def _hydrate_adr(self, row: sqlite3.Row) -> dict[str, Any]:
        base = dict(row)
        metadata_json = base.pop("metadata_json", "{}")
        result = {
            "item_uid": base["item_uid"],
            "project_id": base["project_id"],
            "space_id": base["space_id"],
            "item_type": base["item_type"],
            "local_id": base["local_id"],
            "adr_id": base["adr_id"],
            "title": base["title"],
            "status": base["status"],
            "authority_level": base["authority_level"],
            "summary": base["summary"],
            "source_uri": base["source_uri"],
            "metadata": loads(metadata_json, {}),
        }
        result.update(self._hydrate_adr_details(row))
        return result

    def _hydrate_adr_details(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "context_md": row["context_md"],
            "decision_md": row["decision_md"],
            "consequences_md": row["consequences_md"],
            "supersedes": loads(row["supersedes_json"], []),
            "superseded_by": loads(row["superseded_by_json"], []),
            "raw_source": row["raw_source"] if "raw_source" in row.keys() else None,
            "sections": loads(row["sections_json"] if "sections_json" in row.keys() else "[]", []),
        }


def normalize_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def path_matches(pattern: str, path: str) -> bool:
    normalized_pattern = normalize_path(pattern)
    normalized_path = normalize_path(path)
    if fnmatch.fnmatch(normalized_path, normalized_pattern):
        return True
    if normalized_pattern.endswith("/**"):
        return normalized_path.startswith(normalized_pattern[:-3].rstrip("/") + "/")
    return bool(re.fullmatch(fnmatch.translate(normalized_pattern), normalized_path))
