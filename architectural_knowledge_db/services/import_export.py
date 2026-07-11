from __future__ import annotations

import csv
import json
import posixpath
import re
import shutil
import sqlite3
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote

from architectural_knowledge_db.config import auto_export_root_for_database
from architectural_knowledge_db.models import AdrInput, DefinitionInput, KnowledgeLinkInput, RuleInput, SourceAreaInput
from architectural_knowledge_db.services.knowledge import KnowledgeService


ADR_ID_RE = re.compile(
    r"\bADR(?:[-_ ](?:(?P<domain>[A-Za-z][A-Za-z0-9]{1,12})[-_ ])?)?(?P<number>\d{3,6})\b",
    re.IGNORECASE,
)
ADR_TITLE_PREFIX_RE = re.compile(
    r"^\s*ADR(?:[-_ ](?:(?:[A-Za-z][A-Za-z0-9]{1,12})[-_ ])?)?(?:[-_ ])?\d{3,6}\s*[:\-]\s*",
    re.IGNORECASE,
)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
FRONTMATTER_RE = re.compile(r"\A---\s*\n(?P<body>.*?)\n---\s*\n", re.DOTALL)
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]\n]+\]\(([^)\n]+)\)")
SAD_DECISION_RE = re.compile(
    r"^###\s+(?P<decision_id>D\d+)\s*[:.-]\s*(?P<title>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
DEFAULT_DOCUMENT_PATTERNS = ["*.md", "*.markdown", "*.yml", "*.yaml", "*.json", "*.csv"]
TEMPLATE_PARTS = {"_template", "_templates"}
MANAGED_EXPORT_ENTRIES = ("adr", "documents", "items", "uml", "links", "roadmap", "topics", "specs")


class ImportExportService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.knowledge = KnowledgeService(conn)

    def import_adrs(self, project_id: str, folder: str | Path) -> dict[str, Any]:
        root = Path(folder)
        if not root.exists():
            raise ValueError(f"ADR folder does not exist: {root}")
        imported = []
        skipped = []
        for path in sorted(root.rglob("*.md")):
            source_key = path.relative_to(root).as_posix()
            text = _read_text_exact(path)
            if is_template_or_readme_adr(path, source_key, text):
                skipped.append(source_key)
                continue
            adr = parse_adr_markdown(
                text,
                source_uri=str(path),
                source_key=source_key,
            )
            adr.metadata.update(
                {
                    "source_key": source_key,
                    "repo_source_key": repo_relative_key(path),
                }
            )
            item = self.knowledge.upsert_adr(project_id, adr)
            self._link_targets(
                project_id,
                item["item_uid"],
                [
                    *_markdown_link_targets(text, path),
                ],
                evidence=f"ADR import {source_key}",
            )
            imported.append(item)
        return self._with_auto_export(project_id, {
            "project_id": project_id,
            "folder": str(root),
            "imported": len(imported),
            "skipped": skipped,
            "adrs": [
                {"adr_id": adr["adr_id"], "title": adr["title"], "source_uri": adr.get("source_uri")}
                for adr in imported
            ],
        })

    def export_adrs(self, project_id: str, folder: str | Path) -> dict[str, Any]:
        root = Path(folder)
        root.mkdir(parents=True, exist_ok=True)
        adrs = self.knowledge.list_adrs(project_id, limit=1000)
        exported = []
        for adr in adrs:
            metadata = adr.get("metadata") or {}
            fallback = adr_filename(adr["adr_id"], adr["title"] or adr["adr_id"])
            path = _target_for_source_key(root, metadata.get("source_key"), fallback)
            path.parent.mkdir(parents=True, exist_ok=True)
            text = adr.get("raw_source") or render_adr_markdown(adr)
            _write_text_exact(path, text)
            exported.append(str(path))
        return {"project_id": project_id, "folder": str(root), "exported": len(exported), "files": exported}

    def import_documents(
        self,
        project_id: str,
        folder: str | Path,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
    ) -> dict[str, Any]:
        root = Path(folder)
        if not root.exists():
            raise ValueError(f"Document folder does not exist: {root}")
        include_patterns = include or DEFAULT_DOCUMENT_PATTERNS
        exclude_patterns = exclude or []
        imported = []
        derived = []
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            source_key = path.relative_to(root).as_posix()
            if not _matches_any(source_key, include_patterns) or _matches_any(source_key, exclude_patterns):
                continue
            text = _read_text_exact(path)
            document = parse_document_file(path, text, source_uri=str(path), source_key=source_key)
            classification = classify_document(source_key, path, document)
            metadata = {
                **document.get("metadata", {}),
                "source_key": document["source_key"],
                "repo_source_key": repo_relative_key(path),
                "format": document["format"],
                "doc_kind": classification["doc_kind"],
                "body_text": text,
                "headings": document.get("headings", []),
            }
            item_uid = self.knowledge._upsert_item(
                project_id=project_id,
                space_id=None,
                item_type=classification["item_type"],
                local_id=document["document_id"],
                title=document["title"],
                status=classification["status"],
                authority_level=classification["authority_level"],
                summary=document["summary"],
                source_uri=document["source_uri"],
                metadata=metadata,
            )
            self.knowledge._index_item(item_uid)
            item = self.knowledge.get_item_by_uid(item_uid)
            self._link_document(item, path, root, text, document)
            imported.append(item)
            derived.extend(self._import_derived_architecture_records(project_id, item, path, root, text, document))
        return self._with_auto_export(project_id, {
            "project_id": project_id,
            "folder": str(root),
            "include": include_patterns,
            "exclude": exclude_patterns,
            "imported": len(imported),
            "derived": len(derived),
            "documents": [
                {
                    "document_id": item["local_id"],
                    "item_type": item["item_type"],
                    "title": item["title"],
                    "source_uri": item.get("source_uri"),
                    "authority_level": item["authority_level"],
                }
                for item in imported
            ],
            "derived_records": [
                {
                    "local_id": item["local_id"],
                    "item_type": item["item_type"],
                    "title": item["title"],
                    "authority_level": item["authority_level"],
                }
                for item in derived
            ],
        })

    def import_rules(self, project_id: str, path: str | Path) -> dict[str, Any]:
        records = _records_from_file(path)
        rules = []
        for record in records:
            rules.append(self.knowledge.upsert_rule(project_id, RuleInput(**record)))
        return self._with_auto_export(project_id, {"project_id": project_id, "imported": len(rules), "rules": rules})

    def import_definitions(self, project_id: str, path: str | Path) -> dict[str, Any]:
        records = _records_from_file(path)
        definitions = []
        for record in records:
            definitions.append(self.knowledge.upsert_definition(project_id, DefinitionInput(**record)))
        return self._with_auto_export(
            project_id,
            {"project_id": project_id, "imported": len(definitions), "definitions": definitions},
        )

    def import_source_areas(self, project_id: str, path: str | Path) -> dict[str, Any]:
        records = _records_from_file(path)
        source_areas = []
        for record in records:
            source_areas.append(self.knowledge.upsert_source_area(project_id, SourceAreaInput(**record)))
        return self._with_auto_export(
            project_id,
            {"project_id": project_id, "imported": len(source_areas), "source_areas": source_areas},
        )

    def export_items(self, project_id: str, path: str | Path, item_type: str | None = None) -> dict[str, Any]:
        include_types = [item_type] if item_type else None
        items = self.knowledge.list_items(project_id, include_types=include_types, include_shared=False, limit=5000)
        payload = {"project_id": project_id, "items": items}
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.suffix.lower() in {".yaml", ".yml"}:
            import yaml

            target.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
        else:
            target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"project_id": project_id, "exported": len(items), "path": str(target)}

    def export_documents(self, project_id: str, folder: str | Path) -> dict[str, Any]:
        root = Path(folder)
        root.mkdir(parents=True, exist_ok=True)
        items = self.knowledge.list_items(project_id, include_shared=False, limit=5000)
        exported: list[str] = []
        for item in sorted(items, key=lambda it: (it.get("metadata") or {}).get("source_key") or ""):
            metadata = item.get("metadata") or {}
            source_key = metadata.get("source_key")
            body_text = metadata.get("body_text")
            if not source_key or body_text is None:
                continue
            fallback = f"{item['local_id']}.md"
            target = _target_for_source_key(root, source_key, fallback)
            target.parent.mkdir(parents=True, exist_ok=True)
            _write_text_exact(target, body_text)
            exported.append(target.relative_to(root).as_posix())
        return {"project_id": project_id, "folder": str(root), "exported": len(exported), "files": exported}

    def export_links(self, project_id: str, folder: str | Path) -> dict[str, Any]:
        root = Path(folder)
        root.mkdir(parents=True, exist_ok=True)
        rows = self.conn.execute(
            """
            SELECT source_item_uid, target_ref, link_type, authority_level, confidence, evidence, metadata_json
            FROM knowledge_links
            WHERE project_id = ?
            ORDER BY link_type, source_item_uid, target_ref
            """,
            (project_id,),
        ).fetchall()
        payload = [
            {
                "source_item_uid": row["source_item_uid"],
                "target_ref": row["target_ref"],
                "link_type": row["link_type"],
                "authority_level": row["authority_level"],
                "confidence": row["confidence"],
                "evidence": row["evidence"],
                "metadata": json.loads(row["metadata_json"] or "{}"),
            }
            for row in rows
        ]
        target = root / "links.json"
        target.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return {"project_id": project_id, "exported": len(payload), "path": str(target)}

    def export_roadmap(self, project_id: str, folder: str | Path) -> dict[str, Any]:
        from architectural_knowledge_db.services.roadmap import RoadmapService

        root = Path(folder)
        root.mkdir(parents=True, exist_ok=True)
        entries = RoadmapService(self.conn).roadmap(project_id)
        lines = ["# Roadmap", ""]
        for entry in entries:
            lines.append(f"## {entry['seq']}. {entry['mvp_id']} — {entry['title']}")
            lines.append("")
            lines.append(f"- lifecycle: {entry['lifecycle']}")
            if entry["shipped_at"]:
                lines.append(f"- shipped_at: {entry['shipped_at']}")
            if entry["topics"]:
                lines.append("- topics: " + ", ".join(t["topic_id"] for t in entry["topics"]))
            if entry["specs"]:
                lines.append("- specs: " + ", ".join(s["spec_id"] for s in entry["specs"]))
            for edge in entry["edges"]:
                lines.append(f"- {edge['link_type']}: {edge['target_ref']}")
            lines.append("")
        text = "\n".join(lines).rstrip("\n") + "\n"
        target = root / "ROADMAP.md"
        target.write_text(text, encoding="utf-8", newline="\n")
        return {"project_id": project_id, "exported": len(entries), "path": str(target)}

    def export_topics(self, project_id: str, folder: str | Path) -> dict[str, Any]:
        root = Path(folder)
        root.mkdir(parents=True, exist_ok=True)
        rows = self.conn.execute(
            """
            SELECT t.topic_id, t.lifecycle, ki.title, ki.summary
            FROM topics t JOIN knowledge_items ki ON ki.item_uid = t.item_uid
            WHERE ki.project_id = ?
            ORDER BY t.topic_id
            """,
            (project_id,),
        ).fetchall()
        exported: list[str] = []
        for row in rows:
            lines = [f"# {row['title']}", "", f"- topic_id: {row['topic_id']}", f"- lifecycle: {row['lifecycle']}"]
            if row["summary"]:
                lines.extend(["", row["summary"]])
            text = "\n".join(lines).rstrip("\n") + "\n"
            target = root / f"{row['topic_id']}.md"
            target.write_text(text, encoding="utf-8", newline="\n")
            exported.append(str(target))
        return {"project_id": project_id, "exported": len(exported), "files": exported}

    def export_specs(self, project_id: str, folder: str | Path) -> dict[str, Any]:
        root = Path(folder)
        root.mkdir(parents=True, exist_ok=True)
        rows = self.conn.execute(
            """
            SELECT s.item_uid, s.spec_id, s.archetype, s.lifecycle, s.mvp_uid, ki.title
            FROM specs s JOIN knowledge_items ki ON ki.item_uid = s.item_uid
            WHERE ki.project_id = ?
            ORDER BY s.spec_id
            """,
            (project_id,),
        ).fetchall()
        exported: list[str] = []
        for row in rows:
            lines = [
                f"# {row['title']}",
                "",
                f"- spec_id: {row['spec_id']}",
                f"- archetype: {row['archetype']}",
                f"- lifecycle: {row['lifecycle']}",
            ]
            if row["mvp_uid"]:
                lines.append(f"- mvp_uid: {row['mvp_uid']}")
            text = "\n".join(lines).rstrip("\n") + "\n"
            (root / f"{row['spec_id']}.md").write_text(text, encoding="utf-8", newline="\n")
            exported.append(str(root / f"{row['spec_id']}.md"))
            maps = self.conn.execute(
                """
                SELECT target_ref, metadata_json
                FROM knowledge_links
                WHERE project_id = ? AND source_item_uid = ? AND link_type = 'element_maps_to_file'
                ORDER BY target_ref
                """,
                (project_id, row["item_uid"]),
            ).fetchall()
            puml = ["@startuml", f"' file-map for {row['spec_id']}"]
            for mapping in maps:
                symbol = json.loads(mapping["metadata_json"] or "{}").get("symbol") or ""
                puml.append(f'file "{mapping["target_ref"]}" as {_puml_alias(mapping["target_ref"])}' + (f" : {symbol}" if symbol else ""))
            puml.append("@enduml")
            spec_dir = root / row["spec_id"]
            spec_dir.mkdir(parents=True, exist_ok=True)
            (spec_dir / "file-map.puml").write_text("\n".join(puml) + "\n", encoding="utf-8", newline="\n")
            exported.append(str(spec_dir / "file-map.puml"))
        return {"project_id": project_id, "exported": len(rows), "files": exported}

    def export_corpus(self, project_id: str, folder: str | Path, clean: bool = True) -> dict[str, Any]:
        from architectural_knowledge_db.services.uml import UMLService

        root = Path(folder)
        root.mkdir(parents=True, exist_ok=True)
        if clean:
            _clean_export_root(root)
        adr = self.export_adrs(project_id, root / "adr")
        documents = self.export_documents(project_id, root / "documents")
        items = self.export_items(project_id, root / "items" / "items.json")
        uml = UMLService(self.conn).export_diagrams(project_id, root / "uml")
        links = self.export_links(project_id, root / "links")
        roadmap = self.export_roadmap(project_id, root / "roadmap")
        topics = self.export_topics(project_id, root / "topics")
        specs = self.export_specs(project_id, root / "specs")
        return {
            "project_id": project_id,
            "folder": str(root),
            "adr": adr,
            "documents": documents,
            "uml": uml,
            "items": items,
            "links": links,
            "roadmap": roadmap,
            "topics": topics,
            "specs": specs,
        }

    def verify_corpus(self, project_id: str, folder: str | Path) -> dict[str, Any]:
        import tempfile

        expected_root = Path(folder)
        with tempfile.TemporaryDirectory() as tmp:
            fresh_root = Path(tmp) / "verify"
            self.export_corpus(project_id, fresh_root)
            matched = 0
            mismatched: list[str] = []
            fresh_files = {
                p.relative_to(fresh_root).as_posix(): p
                for p in fresh_root.rglob("*")
                if p.is_file()
            }
            expected_files = {
                p.relative_to(expected_root).as_posix(): p
                for p in expected_root.rglob("*")
                if p.is_file()
            }
            for rel, fresh_path in sorted(fresh_files.items()):
                expected_path = expected_root / rel
                if expected_path.is_file() and expected_path.read_bytes() == fresh_path.read_bytes():
                    matched += 1
                else:
                    mismatched.append(rel)
            extra = sorted(set(expected_files) - set(fresh_files))
        return {
            "project_id": project_id,
            "folder": str(expected_root),
            "checked": matched + len(mismatched),
            "matched": matched,
            "mismatched": mismatched,
            "extra": extra,
        }

    def _with_auto_export(self, project_id: str, result: dict[str, Any]) -> dict[str, Any]:
        export_root = _auto_export_root_for_connection(self.conn)
        if export_root is None:
            return result
        export = self.export_corpus(project_id, export_root, clean=True)
        verification = self.verify_corpus(project_id, export_root)
        return {
            **result,
            "auto_export": {
                "folder": str(export_root),
                "export": export,
                "verification": verification,
            },
        }

    def _link_document(
        self,
        item: dict[str, Any],
        path: Path,
        root: Path,
        text: str,
        document: dict[str, Any],
    ) -> None:
        targets = [
            *_markdown_link_targets(text, path),
        ]
        data = document.get("metadata", {}).get("data")
        if isinstance(data, dict):
            targets.extend(_fact_sheet_targets(data))
        if path.name == "architecture.md":
            product_facts = path.parent / "product-facts.yml"
            if product_facts.exists():
                targets.append(repo_relative_key(product_facts))
        self._link_targets(item["project_id"], item["item_uid"], targets, evidence=f"document import {document['source_key']}")

    def _import_derived_architecture_records(
        self,
        project_id: str,
        parent_item: dict[str, Any],
        path: Path,
        root: Path,
        text: str,
        document: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not is_sad_document(path, document):
            return []
        created: list[dict[str, Any]] = []
        frontmatter = parse_frontmatter(text)
        if frontmatter:
            local_id = f"{document['document_id']}:frontmatter"
            title = f"{document['title']} frontmatter"
            summary = ", ".join(str(key) for key in sorted(frontmatter)[:8])
            item_uid = self.knowledge._upsert_item(
                project_id=project_id,
                space_id=None,
                item_type="sad_frontmatter",
                local_id=local_id,
                title=title,
                status=str(frontmatter.get("status") or "current"),
                authority_level="active_rule",
                summary=summary or title,
                source_uri=str(path),
                metadata={
                    "source_key": document["source_key"],
                    "repo_source_key": repo_relative_key(path),
                    "parent_item_uid": parent_item["item_uid"],
                    "frontmatter": frontmatter,
                },
            )
            self.knowledge._index_item(item_uid)
            item = self.knowledge.get_item_by_uid(item_uid)
            self._link_targets(
                project_id,
                item_uid,
                [
                    parent_item["item_uid"],
                    *_frontmatter_targets(frontmatter),
                ],
                evidence=f"SAD frontmatter import {document['source_key']}",
            )
            created.append(item)

        for decision in parse_sad_decisions(text):
            local_id = f"{document['document_id']}:decision:{decision['decision_id'].lower()}"
            item_uid = self.knowledge._upsert_item(
                project_id=project_id,
                space_id=None,
                item_type="sad_decision",
                local_id=local_id,
                title=f"{decision['decision_id']}: {decision['title']}",
                status=decision["status"],
                authority_level="active_rule",
                summary=decision["summary"],
                source_uri=str(path),
                metadata={
                    "source_key": document["source_key"],
                    "repo_source_key": repo_relative_key(path),
                    "parent_item_uid": parent_item["item_uid"],
                    "decision_id": decision["decision_id"],
                    "body_md": decision["body_md"],
                },
            )
            self.knowledge._index_item(item_uid)
            item = self.knowledge.get_item_by_uid(item_uid)
            self._link_targets(
                project_id,
                item_uid,
                [
                    parent_item["item_uid"],
                    *_markdown_link_targets(decision["body_md"], path),
                ],
                evidence=f"SAD decision import {document['source_key']}#{decision['decision_id']}",
            )
            created.append(item)
        return created

    def _link_targets(
        self,
        project_id: str,
        source_item_uid: str,
        targets: list[str],
        evidence: str,
    ) -> None:
        seen: set[str] = set()
        for raw_target in targets:
            target = str(raw_target or "").strip()
            if not target or target in seen:
                continue
            seen.add(target)
            self.knowledge.upsert_link(
                project_id,
                KnowledgeLinkInput(
                    source_item_uid=source_item_uid,
                    target_ref=target,
                    link_type=link_type_for_target(target),
                    authority_level="evidence",
                    confidence="explicit",
                    evidence=evidence,
                    metadata={"importer": "tiny_tool_architecture"},
                ),
            )


def parse_adr_markdown(text: str, source_uri: str | None = None, source_key: str | None = None) -> AdrInput:
    lines = text.splitlines(keepends=True)
    title = None
    h1_seen = False
    preamble: list[str] = []
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for line in lines:
        match = HEADING_RE.match(line.rstrip("\n"))
        if match:
            level = len(match.group(1))
            heading_title = match.group(2).strip()
            if level == 1 and not h1_seen:
                h1_seen = True
                title = heading_title
                if preamble:
                    sections.append({"kind": "preamble", "text": "".join(preamble)})
                    preamble = []
                sections.append({"kind": "heading", "level": 1, "title": heading_title, "role": "title"})
                current = None
                continue
            if current is not None:
                current["body_md"] = "".join(current.pop("_body"))
                sections.append(current)
            current = {
                "kind": "section",
                "level": level,
                "title": heading_title,
                "role": section_role(heading_title),
                "_body": [],
            }
            continue
        if current is not None:
            current["_body"].append(line)
        elif not h1_seen:
            preamble.append(line)
        elif line.strip():
            sections.append({"kind": "preamble", "text": line})

    if current is not None:
        current["body_md"] = "".join(current.pop("_body"))
        sections.append(current)
    elif preamble:
        sections.append({"kind": "preamble", "text": "".join(preamble)})

    source_name = source_key or (Path(source_uri).name if source_uri else "ADR-0000.md")
    adr_id = derive_adr_id(title or source_name, source_name)
    clean_title = clean_adr_title(title or adr_id, adr_id)
    status = section_body(sections, "status").strip() or "proposed"
    supersedes = extract_adr_refs(section_body(sections, "supersedes") or status)
    superseded_by = extract_adr_refs(section_body(sections, "superseded_by"))
    summary = first_sentence(section_body(sections, "decision") or section_body(sections, "context"))
    return AdrInput(
        adr_id=adr_id,
        title=clean_title,
        status=status.splitlines()[0].strip() if status else "proposed",
        context_md=section_body(sections, "context").strip("\n") or None,
        decision_md=section_body(sections, "decision").strip("\n") or None,
        consequences_md=section_body(sections, "consequences").strip("\n") or None,
        supersedes=supersedes,
        superseded_by=superseded_by,
        summary=summary,
        source_uri=source_uri,
        raw_source=text,
        sections=sections,
    )


def render_adr_markdown(adr: dict[str, Any]) -> str:
    sections = adr.get("sections") or []
    if sections:
        rendered: list[str] = []
        for part in sections:
            kind = part.get("kind")
            if kind == "preamble":
                rendered.append(part.get("text", ""))
            elif kind == "heading":
                title = part.get("title") or f"{adr['adr_id']}: {adr['title']}"
                rendered.append(f"{'#' * int(part.get('level', 1))} {title}\n")
            elif kind == "section":
                role = part.get("role")
                body = _section_body_for_render(adr, role, part.get("body_md", ""))
                rendered.append(f"{'#' * int(part.get('level', 2))} {part.get('title')}\n")
                if body and not body.startswith("\n"):
                    rendered.append("\n")
                rendered.append(body)
                if body and not body.endswith("\n"):
                    rendered.append("\n")
        text = "".join(rendered)
        return text if text.endswith("\n") else f"{text}\n"

    parts = [
        f"# {adr['adr_id']}: {adr['title']}\n",
        "\n## Status\n\n",
        adr.get("status") or "proposed",
        "\n\n## Context\n\n",
        adr.get("context_md") or "",
        "\n\n## Decision\n\n",
        adr.get("decision_md") or "",
        "\n\n## Consequences\n\n",
        adr.get("consequences_md") or "",
        "\n",
    ]
    return "".join(parts)


def section_role(title: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    return {
        "status": "status",
        "context": "context",
        "decision": "decision",
        "consequences": "consequences",
        "supersedes": "supersedes",
        "superseded_by": "superseded_by",
    }.get(normalized, "other")


def section_body(sections: list[dict[str, Any]], role: str) -> str:
    for section in sections:
        if section.get("kind") == "section" and section.get("role") == role:
            return section.get("body_md", "")
    return ""


def derive_adr_id(title: str, filename: str) -> str:
    match = ADR_ID_RE.search(title) or ADR_ID_RE.search(filename)
    if match:
        return canonical_adr_id(match)
    without_suffix = str(Path(filename).with_suffix(""))
    return re.sub(r"[^A-Za-z0-9]+", "-", without_suffix).strip("-").upper()


def clean_adr_title(title: str, adr_id: str) -> str:
    cleaned = re.sub(rf"^\s*{re.escape(adr_id)}\s*[:\-]\s*", "", title, flags=re.IGNORECASE)
    cleaned = ADR_TITLE_PREFIX_RE.sub("", cleaned)
    return cleaned.strip() or adr_id


def extract_adr_refs(text: str) -> list[str]:
    refs = []
    for match in ADR_ID_RE.finditer(text):
        ref = canonical_adr_id(match)
        if ref not in refs:
            refs.append(ref)
    return refs


def canonical_adr_id(match: re.Match[str]) -> str:
    number = int(match.group("number"))
    domain = match.groupdict().get("domain")
    if domain:
        return f"ADR-{domain.upper()}-{number:04d}"
    return f"ADR-{number:04d}"


def first_sentence(text: str) -> str | None:
    compact = " ".join(line.strip() for line in text.splitlines() if line.strip())
    if not compact:
        return None
    match = re.match(r"(.{1,240}?[.!?])(?:\s|$)", compact)
    return (match.group(1) if match else compact[:240]).strip()


def parse_markdown_document(text: str, source_uri: str | None = None, source_key: str | None = None) -> dict[str, Any]:
    source_name = source_key or (Path(source_uri).name if source_uri else "document.md")
    headings = []
    title = None
    body_lines = []
    for line in text.splitlines():
        match = HEADING_RE.match(line)
        if match:
            level = len(match.group(1))
            heading_title = match.group(2).strip()
            headings.append({"level": level, "title": heading_title})
            if title is None and level == 1:
                title = heading_title
            continue
        body_lines.append(line)
    if title is None:
        title = Path(source_name).stem.replace("_", " ").replace("-", " ").strip().title() or source_name
    summary = first_sentence("\n".join(body_lines)) or first_sentence(text) or title
    return {
        "document_id": document_id_for(source_name),
        "title": title,
        "summary": summary,
        "source_uri": source_uri,
        "source_key": source_name,
        "headings": headings,
    }


def parse_document_file(path: Path, text: str, source_uri: str | None = None, source_key: str | None = None) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        document = parse_markdown_document(text, source_uri=source_uri, source_key=source_key)
        document["format"] = "markdown"
        document["metadata"] = {"body_md": text, "headings": document["headings"]}
        return document
    if suffix in {".yml", ".yaml"}:
        data = load_yaml_documents(text)
        return parse_structured_document(path, text, data, "yaml", source_uri, source_key)
    if suffix == ".json":
        data = json.loads(text)
        return parse_structured_document(path, text, data, "json", source_uri, source_key)
    if suffix == ".csv":
        rows = list(csv.DictReader(text.splitlines()))
        return parse_structured_document(path, text, {"rows": rows, "row_count": len(rows)}, "csv", source_uri, source_key)
    return parse_structured_document(path, text, {}, "text", source_uri, source_key)


def load_yaml_documents(text: str) -> Any:
    import yaml

    documents = [document for document in yaml.safe_load_all(text) if document is not None]
    if not documents:
        return {}
    if len(documents) == 1:
        return documents[0]
    return {"document_count": len(documents), "documents": documents}


def parse_structured_document(
    path: Path,
    text: str,
    data: Any,
    fmt: str,
    source_uri: str | None,
    source_key: str | None,
) -> dict[str, Any]:
    source_name = source_key or (Path(source_uri).name if source_uri else path.name)
    title = Path(source_name).stem.replace("_", " ").replace("-", " ").strip().title() or source_name
    summary = first_sentence(text) or title
    if isinstance(data, dict):
        title = str(data.get("display_name") or data.get("title") or data.get("plugin") or title)
        summary = str(data.get("summary") or data.get("description") or summary)
    return {
        "document_id": document_id_for(source_name),
        "title": title,
        "summary": summary,
        "source_uri": source_uri,
        "source_key": source_name,
        "format": fmt,
        "headings": [],
        "metadata": {
            "data": data,
            "body_text": text,
        },
    }


def classify_document(source_key: str, path: Path, document: dict[str, Any]) -> dict[str, str]:
    lower = source_key.replace("\\", "/").lower()
    template = is_template_document(path, source_key)
    if lower == "quality-standard.md":
        return {"item_type": "document", "authority_level": "hard_guardrail", "status": "active_rule", "doc_kind": "quality_standard"}
    if template:
        return {"item_type": "document", "authority_level": "historical_context", "status": "template", "doc_kind": "template"}
    if lower.endswith("/architecture.md") or lower == "architecture.md":
        return {"item_type": "sad", "authority_level": "active_rule", "status": "current", "doc_kind": "sad"}
    if lower.endswith("product-facts.yml") or lower.endswith("product-facts.yaml"):
        return {"item_type": "product_fact_sheet", "authority_level": "active_rule", "status": "current", "doc_kind": "product_facts"}
    if lower.endswith(".schema.json"):
        return {"item_type": "json_schema", "authority_level": "active_rule", "status": "current", "doc_kind": "json_schema"}
    if lower.endswith(".csv"):
        return {"item_type": "csv_worklist", "authority_level": "evidence", "status": "current", "doc_kind": "csv_worklist"}
    if lower.startswith("evidence/") or "/evidence/" in lower:
        return {"item_type": "evidence_report", "authority_level": "evidence", "status": "current", "doc_kind": "evidence_report"}
    if lower.startswith("contracts/") or "/contracts/" in lower:
        return {"item_type": "contract", "authority_level": "active_rule", "status": "current", "doc_kind": "contract"}
    if lower.startswith("gates/") or "/gates/" in lower or "gate" in path.stem.lower():
        return {"item_type": "gate_result", "authority_level": "evidence", "status": "current", "doc_kind": "gate_result"}
    return {"item_type": "document", "authority_level": "project_note", "status": "current", "doc_kind": "document"}


def parse_frontmatter(text: str) -> dict[str, Any]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    import yaml

    data = yaml.safe_load(match.group("body")) or {}
    return data if isinstance(data, dict) else {}


def parse_sad_decisions(text: str) -> list[dict[str, str]]:
    decisions = []
    matches = list(SAD_DECISION_RE.finditer(text))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        status_match = re.search(r"\*\*Status:\*\*\s*([A-Za-z_ -]+)", body)
        decisions.append(
            {
                "decision_id": match.group("decision_id").upper(),
                "title": match.group("title").strip(),
                "status": (status_match.group(1).strip().lower() if status_match else "accepted"),
                "summary": first_sentence(body) or match.group("title").strip(),
                "body_md": body,
            }
        )
    return decisions


def is_sad_document(path: Path, document: dict[str, Any]) -> bool:
    return path.name == "architecture.md" and document.get("format") == "markdown"


def is_template_document(path: Path, source_key: str) -> bool:
    parts = {part.lower() for part in Path(source_key).parts}
    return bool(parts & TEMPLATE_PARTS) or path.name.endswith(".template.md") or "template" in path.stem.lower()


def is_template_or_readme_adr(path: Path, source_key: str, text: str) -> bool:
    if path.name.lower() == "readme.md" and "## Decision" not in text:
        return True
    return is_template_document(path, source_key)


def _markdown_link_targets(text: str, source_path: Path) -> list[str]:
    targets: list[str] = []
    for match in MARKDOWN_LINK_RE.finditer(text):
        target = _normalize_markdown_target(match.group(1), source_path)
        if target:
            targets.append(target)
    return targets


def _normalize_markdown_target(raw_target: str, source_path: Path) -> str | None:
    target = raw_target.strip()
    if not target or target.startswith("#"):
        return None
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
        return None
    path_part = target.split("#", 1)[0].split("?", 1)[0].strip()
    if not path_part:
        return None
    if path_part.startswith("<") and path_part.endswith(">"):
        path_part = path_part[1:-1]
    if "<" in path_part or ">" in path_part:
        return None
    path_part = unquote(path_part)
    normalized_part = path_part.replace("\\", "/")
    if normalized_part.startswith("Git/"):
        return normalized_part.removeprefix("Git/")
    candidate = (source_path.parent / path_part).resolve()
    if candidate.exists():
        return repo_relative_key(candidate)
    source_repo_key = repo_relative_key(source_path)
    normalized = posixpath.normpath(posixpath.join(posixpath.dirname(source_repo_key), path_part))
    if normalized == ".":
        return None
    return normalized.replace("\\", "/")


def _fact_sheet_targets(data: dict[str, Any]) -> list[str]:
    targets: list[str] = []
    for key in ("sad", "folder"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            targets.append(value.strip())
    for section in ("documentation", "verification", "compatibility"):
        payload = data.get(section)
        if isinstance(payload, dict):
            targets.extend(_string_paths(payload.values()))
    return targets


def _frontmatter_targets(frontmatter: dict[str, Any]) -> list[str]:
    targets: list[str] = []
    for key in ("owns-adrs", "supersedes", "links"):
        value = frontmatter.get(key)
        if isinstance(value, list):
            targets.extend(str(item) for item in value if str(item).strip())
        elif isinstance(value, str):
            targets.append(value)
    plugins = frontmatter.get("plugins")
    if isinstance(plugins, list):
        for plugin in plugins:
            if isinstance(plugin, str) and plugin.strip():
                targets.append(f"docs/architecture/plugins/{plugin.strip()}/architecture.md")
    elif isinstance(plugins, str) and plugins.strip():
        targets.append(f"docs/architecture/plugins/{plugins.strip()}/architecture.md")
    uml_package = frontmatter.get("uml-package")
    if isinstance(uml_package, str) and uml_package.strip():
        targets.append(uml_package.strip())
    return [canonicalize_target(target) for target in targets if canonicalize_target(target)]


def _string_paths(values: Any) -> list[str]:
    targets: list[str] = []
    for value in values:
        if isinstance(value, str) and ("/" in value or "\\" in value):
            targets.append(value.strip())
        elif isinstance(value, dict):
            targets.extend(_string_paths(value.values()))
        elif isinstance(value, list):
            targets.extend(_string_paths(value))
    return targets


def canonicalize_target(target: str) -> str:
    target = target.strip()
    match = ADR_ID_RE.fullmatch(target)
    if match:
        return canonical_adr_id(match)
    return target.replace("\\", "/")


def link_type_for_target(target: str) -> str:
    normalized = target.replace("\\", "/")
    if ADR_ID_RE.fullmatch(normalized):
        return "references_adr"
    if normalized.startswith("UML/") or "/UML/" in normalized:
        return "references_uml"
    if normalized.endswith("product-facts.yml") or normalized.endswith("product-facts.yaml"):
        return "references_product_facts"
    if normalized.endswith("architecture.md"):
        return "references_sad"
    if normalized.endswith(".schema.json"):
        return "references_schema"
    if "/" in normalized or "\\" in normalized:
        return "references_source"
    return "references"


def repo_relative_key(path: Path) -> str:
    resolved = path.resolve()
    repo_root = find_repository_root(resolved)
    if repo_root:
        try:
            return resolved.relative_to(repo_root).as_posix()
        except ValueError:
            pass
    return resolved.as_posix()


def find_repository_root(path: Path) -> Path | None:
    probe = path if path.is_dir() else path.parent
    for parent in [probe, *probe.parents]:
        if (parent / ".git").exists() or ((parent / "docs").is_dir() and (parent / "PluginProject.uproject").exists()):
            return parent
    return None


def document_id_for(source_key: str) -> str:
    without_suffix = str(Path(source_key).with_suffix(""))
    return re.sub(r"[^A-Za-z0-9]+", "-", without_suffix).strip("-").lower() or "document"


def adr_filename(adr_id: str, title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80]
    return f"{adr_id.lower()}-{slug}.md" if slug else f"{adr_id.lower()}.md"


def _section_body_for_render(adr: dict[str, Any], role: str, fallback: str) -> str:
    if role == "status":
        return str(adr.get("status") or fallback)
    if role == "context":
        return str(adr.get("context_md") or fallback)
    if role == "decision":
        return str(adr.get("decision_md") or fallback)
    if role == "consequences":
        return str(adr.get("consequences_md") or fallback)
    return fallback


def _records_from_file(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    text = _read_text_exact(source)
    if source.suffix.lower() in {".yaml", ".yml"}:
        import yaml

        payload = yaml.safe_load(text)
    else:
        payload = json.loads(text)
    if isinstance(payload, dict):
        for key in ("rules", "definitions", "source_areas", "items", "records"):
            if key in payload:
                payload = payload[key]
                break
    if not isinstance(payload, list):
        raise ValueError(f"Expected a list of records in {source}")
    return payload


def _matches_any(path: str, patterns: list[str]) -> bool:
    import fnmatch

    return any(fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(Path(path).name, pattern) for pattern in patterns)


def _puml_alias(target: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", target).strip("_") or "node"


def _read_text_exact(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return handle.read()


def _write_text_exact(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _target_for_source_key(root: Path, source_key: Any, fallback: str) -> Path:
    rel = _safe_relative_export_path(str(source_key or ""), fallback)
    return root / Path(*rel.parts)


def _safe_relative_export_path(source_key: str, fallback: str) -> PurePosixPath:
    normalized = source_key.replace("\\", "/").strip()
    candidate = PurePosixPath(normalized) if normalized else PurePosixPath(fallback)
    if candidate.is_absolute() or not candidate.parts or any(part in {"", ".", ".."} or ":" in part for part in candidate.parts):
        candidate = PurePosixPath(fallback)
    return candidate


def _clean_export_root(root: Path) -> None:
    for name in MANAGED_EXPORT_ENTRIES:
        target = root / name
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()


def _auto_export_root_for_connection(conn: sqlite3.Connection) -> Path | None:
    row = conn.execute("PRAGMA database_list").fetchone()
    if row is None:
        return None
    database_file = row["file"] if isinstance(row, sqlite3.Row) else row[2]
    if not database_file:
        return None
    return auto_export_root_for_database(database_file)
