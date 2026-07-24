from __future__ import annotations

import csv
import json
import posixpath
import re
import shutil
import sqlite3
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

from architectural_knowledge_db.config import auto_export_root_for_database
from architectural_knowledge_db.models import (
    AdrInput,
    CanonicalDocumentCreate,
    CanonicalDocumentUpdate,
    DefinitionInput,
    KnowledgeLinkInput,
    RuleInput,
    SourceAreaInput,
    UMLDiagramUpdate,
)
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
MIRROR_MARKDOWN_LINK_RE = re.compile(
    r"(?P<prefix>!?\[[^\]\n]*\]\()(?P<target>[^)\n]+)(?P<suffix>\))"
)
MARKDOWN_FENCE_RE = re.compile(r"^\s*(?P<fence>`{3,}|~{3,})")
SAD_DECISION_RE = re.compile(
    r"^###\s+(?P<decision_id>D(?:\d+|-\w+))\s*[:.-]\s*(?P<title>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
SAD_MAIN_SECTION_RE = re.compile(r"^##(?!#)[ \t]+[^\r\n]+$", re.MULTILINE)
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
        from architectural_knowledge_db.services.export_flush import deferred_export

        with deferred_export(self.conn):
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
                        # Verbatim bytes alongside the structured decomposition
                        # (context_md/decision_md/...) so ADRs flow through the
                        # SAME generic byte-exact export path as SAD/documents
                        # (list_items()-based export_canon/_mirror_path never
                        # join the `adrs.raw_source` column). Real gap found
                        # 2026-07-24: without this, ADRs were silently invisible
                        # to export_canon()/verify_canon() -- see progress.md.
                        "body_text": text,
                        "body_encoding": "utf-8",
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

    def _sad_children(
        self,
        project_id: str,
        item_type: str,
        document_local_id: str | None,
    ) -> list[dict[str, Any]]:
        items = self.knowledge.list_items(
            project_id, include_types=[item_type], include_shared=False, limit=5000
        )
        if document_local_id is None:
            return items
        return [
            i
            for i in items
            if (i.get("metadata") or {}).get("source_key", "").endswith(document_local_id)
        ]

    def export_sad(
        self,
        project_id: str,
        folder: str | Path,
        document_local_id: str | None = None,
    ) -> dict[str, Any]:
        from architectural_knowledge_db.services.sad import SadService
        from architectural_knowledge_db.services.uml import UMLService, safe_filename

        root = Path(folder)
        root.mkdir(parents=True, exist_ok=True)
        sad = SadService(self.conn)
        all_documents = sad.list_documents(project_id)
        documents = all_documents
        if document_local_id is not None:
            documents = [
                item
                for item in documents
                if item["local_id"] == document_local_id
                or (item.get("metadata") or {}).get("source_key", "").endswith(document_local_id)
            ]
        if not documents:
            raise ValueError(
                f"No SAD document found in project {project_id}"
                + (f" for {document_local_id}" if document_local_id else "")
            )

        exported: list[str] = []
        reserved_targets: dict[str, str] = {}
        selected_document_ids: set[str] = set()
        for document_item in documents:
            document = sad.get_document(project_id, document_item["local_id"])
            selected_document_ids.add(document["local_id"])
            source_key = (document.get("metadata") or {}).get("source_key") or "architecture.md"
            target = _target_for_source_key(root, source_key, "architecture.md")
            self._reserve_sad_export_target(root, target, document["local_id"], reserved_targets)
            target.parent.mkdir(parents=True, exist_ok=True)
            self._render_sad_document(document, target)
            exported.append(str(target))

        uml = UMLService(self.conn)
        diagrams = uml.list_diagrams(project_id, limit=5000)
        unassigned_to_only_document = len(all_documents) == 1
        for diagram in diagrams:
            model = diagram.get("model") or {}
            assigned_document = model.get("sad_document_id")
            if assigned_document:
                if assigned_document not in selected_document_ids:
                    continue
            elif not unassigned_to_only_document:
                continue
            source_key = model.get("source_key") or f"UML/{safe_filename(diagram['diagram_id'])}.puml"
            target = _target_for_source_key(
                root, source_key, f"UML/{safe_filename(diagram['diagram_id'])}.puml"
            )
            self._reserve_sad_export_target(
                root, target, diagram["diagram_id"], reserved_targets
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            _write_text_exact(target, uml.render_diagram(project_id, diagram["diagram_id"]))
            exported.append(str(target))

        manifest_path: Path | None = None
        if document_local_id is None:
            manifest_path = self._write_sad_export_manifest(
                project_id, root, exported
            )
        return {
            "project_id": project_id,
            "folder": str(root),
            "documents": len(documents),
            "exported": len(exported),
            "files": exported,
            "manifest": str(manifest_path) if manifest_path is not None else None,
        }

    @staticmethod
    def _reserve_sad_export_target(
        root: Path, target: Path, owner: str, reserved: dict[str, str]
    ) -> None:
        relative = target.relative_to(root).as_posix()
        key = relative.casefold()
        previous = reserved.get(key)
        if previous is not None:
            raise ValueError(
                f"SAD export path collision for {relative}: {previous} and {owner}"
            )
        reserved[key] = owner

    @staticmethod
    def _write_sad_export_manifest(
        project_id: str, root: Path, exported: list[str]
    ) -> Path:
        manifest_path = root / ".akdb-sad-export.json"
        current = sorted(
            Path(path).relative_to(root).as_posix() for path in exported
        )
        previous: list[str] = []
        if manifest_path.is_file():
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                payload = {}
            if payload.get("project_id") == project_id:
                previous = [
                    value for value in payload.get("files", []) if isinstance(value, str)
                ]
        current_keys = {value.casefold() for value in current}
        for stale in previous:
            if stale.casefold() in current_keys:
                continue
            candidate = PurePosixPath(stale.replace("\\", "/"))
            if (
                candidate.is_absolute()
                or not candidate.parts
                or any(part in {"", ".", ".."} or ":" in part for part in candidate.parts)
            ):
                continue
            target = root / Path(*candidate.parts)
            if target.is_file():
                target.unlink()
                parent = target.parent
                while parent != root and parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent
        _write_text_exact(
            manifest_path,
            json.dumps(
                {
                    "format_version": 1,
                    "project_id": project_id,
                    "files": current,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )
        return manifest_path

    def _render_sad_document(self, document: dict[str, Any], target: Path) -> None:
        frontmatter = document.get("frontmatter") or []
        preambles = document.get("preamble") or []
        sections = document.get("sections") or []
        decisions = document.get("decisions") or []
        lines: list[str] = []
        if frontmatter:
            front = (frontmatter[0].get("metadata") or {}).get("frontmatter")
            if front:
                import yaml

                lines += [
                    "---",
                    yaml.safe_dump(front, sort_keys=False, allow_unicode=True).rstrip("\n"),
                    "---",
                    "",
                ]
        if preambles:
            preamble = (preambles[0].get("metadata") or {}).get("body_md", "").strip("\n")
            if preamble:
                lines += [preamble, ""]
        for sec in sections:
            md = sec.get("metadata") or {}
            lines += [f"{'#' * md.get('level', 2)} {sec['title']}", ""]
            if md.get("role") == "decisions":
                section_body = (md.get("body_md") or "").strip("\n")
                first_decision = SAD_DECISION_RE.search(section_body)
                prefix = section_body[: first_decision.start()].strip("\n") if first_decision else section_body
                if prefix:
                    lines += [_sync_decision_summary(prefix, decisions), ""]
                for d in decisions:
                    dm = d.get("metadata") or {}
                    did = dm.get("decision_id", "")
                    title = d["title"].split(":", 1)[1].strip() if ":" in d["title"] else d["title"]
                    body = (dm.get("body_md") or "").strip("\n")
                    status_match = re.match(r"\*\*Status:\*\*\s*([^\n]+)\n?", body)
                    if status_match:
                        status_text = status_match.group(1).strip()
                        body = body[status_match.end() :].lstrip("\n")
                    else:
                        status_text = d.get("status") or "proposed"
                        if isinstance(status_text, str) and status_text.islower():
                            status_text = status_text.capitalize()
                    lines += [f"### {did}: {title}", "", f"**Status:** {status_text}", ""]
                    if body:
                        lines += [body, ""]
            else:
                lines += [(md.get("body_md") or "").strip("\n"), ""]
        text = "\n".join(lines).rstrip("\n") + "\n"
        target.write_text(text, encoding="utf-8", newline="\n")

    def _seen_local_ids_for_project(self, project_id: str) -> dict[tuple[str, str], str]:
        """Seed the collision tracker from items already in the DB.

        Lets import_documents() detect a document_id collision against an
        EARLIER, separate call (e.g. docs/architecture then UML) rather than
        only within the current call's loop.
        """
        seen: dict[tuple[str, str], str] = {}
        rows = self.conn.execute(
            "SELECT item_type, local_id, metadata_json FROM knowledge_items WHERE project_id = ?",
            (project_id,),
        ).fetchall()
        for row in rows:
            metadata = json.loads(row["metadata_json"] or "{}")
            repo_key = metadata.get("repo_source_key")
            if repo_key:
                seen[(row["item_type"], row["local_id"])] = repo_key
        return seen

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
        # Disambiguate document_id collisions -- e.g. a UML `.puml` + `.md`
        # companion pair sharing the same basename (spec class B) would
        # otherwise upsert into the SAME item, silently discarding one file's
        # body_text. document_id_for() intentionally ignores suffix (so unrelated
        # single-file documents like "README.md" keep their stable short id); this
        # tracks (item_type, local_id) -> repo_source_key and only disambiguates
        # when a real collision (a DIFFERENT file) is detected. Keyed by
        # repo_source_key (not the import-root-relative source_key) so it also
        # catches CROSS-CALL collisions: docs/architecture/** and UML/** mirror
        # the same plugin folder names, so e.g. both trees' "Demo/README.md"
        # produce the identical document_id_for() result relative to their own
        # call's root -- a real Phase 4 gap (2026-07-23) where the second
        # import_documents() call (UML) silently overwrote the first's (docs)
        # body_text. _seen_local_ids_for_project() seeds this from the live DB
        # so it also catches collisions against an EARLIER, separate call.
        seen_local_ids = self._seen_local_ids_for_project(project_id)
        from architectural_knowledge_db.services.export_flush import deferred_export

        with deferred_export(self.conn):
            for path in sorted(root.rglob("*")):
                if not path.is_file():
                    continue
                source_key = path.relative_to(root).as_posix()
                if include_patterns == ["**/*"]:
                    # Explicit "every file" include: fnmatch's "**/*" requires a literal
                    # "/" (glob-style ** is not special to fnmatch), so top-level files
                    # like "START-HERE.md" would otherwise be silently skipped. An
                    # explicit "**/*" means "every file" — bypass the suffix allowlist
                    # entirely rather than trying to out-glob fnmatch. Default behavior
                    # (DEFAULT_DOCUMENT_PATTERNS) is unchanged.
                    matched = not _matches_any(source_key, exclude_patterns)
                else:
                    matched = _matches_any(source_key, include_patterns) and not _matches_any(source_key, exclude_patterns)
                if not matched:
                    continue
                text, encoding = _read_text_exact_any_encoding(path)
                document = parse_document_file(path, text, source_uri=str(path), source_key=source_key)
                classification = classify_document(source_key, path, document)
                local_id = document["document_id"]
                repo_key = repo_relative_key(path)
                collision_key = (classification["item_type"], local_id)
                previous_repo_key = seen_local_ids.get(collision_key)
                if previous_repo_key is not None and previous_repo_key != repo_key:
                    suffix = path.suffix.lstrip(".").lower() or "file"
                    local_id = f"{local_id}--{suffix}"
                    collision_key = (classification["item_type"], local_id)
                    previous_repo_key = seen_local_ids.get(collision_key)
                    if previous_repo_key is not None and previous_repo_key != repo_key:
                        # Same-suffix collision (e.g. two different trees' README.md):
                        # the suffix alone can't disambiguate -- fall back to the
                        # top-level repo tree segment (e.g. "docs" vs "uml").
                        tree_segment = repo_key.split("/", 1)[0].lower() or "root"
                        local_id = f"{local_id}--{tree_segment}"
                        collision_key = (classification["item_type"], local_id)
                seen_local_ids[collision_key] = repo_key
                metadata = {
                    **document.get("metadata", {}),
                    "source_key": document["source_key"],
                    "repo_source_key": repo_key,
                    "format": document["format"],
                    "doc_kind": classification["doc_kind"],
                    "body_text": text,
                    "body_encoding": encoding,
                    "headings": document.get("headings", []),
                }
                item_uid = self.knowledge._upsert_item(
                    project_id=project_id,
                    space_id=None,
                    item_type=classification["item_type"],
                    local_id=local_id,
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

    def create_canonical_document(
        self,
        project_id: str,
        request: CanonicalDocumentCreate,
    ) -> dict[str, Any]:
        """Create one new DB-owned canonical file and its structured records."""
        from architectural_knowledge_db.services.export_flush import deferred_export
        from architectural_knowledge_db.services.repositories import RepositoryService
        from architectural_knowledge_db.services.uml import (
            UMLService,
            parse_mermaid,
            parse_plantuml,
        )

        repo_key = _safe_repo_source_key(request.repo_source_key)
        if self._body_owner_rows(project_id, repo_key):
            raise ValueError(
                f"Canonical document already exists for repo_source_key {repo_key}; "
                "use update_canonical_document"
            )
        repository = RepositoryService(self.conn).get_repository(
            project_id,
            request.repository_id,
        )
        repository_root = Path(repository["local_path"]).expanduser().resolve()
        if not repository_root.is_dir():
            raise ValueError(
                f"Registered repository path does not exist: {repository_root}"
            )
        virtual_path = repository_root.joinpath(*PurePosixPath(repo_key).parts)
        source_key = _canonical_source_key(repo_key)
        source_uri = f"akdb://{project_id}/canon/{repo_key}"
        document = parse_document_file(
            virtual_path,
            request.body_text,
            source_uri=source_uri,
            source_key=source_key,
        )
        classification = classify_document(source_key, virtual_path, document)
        if _is_canonical_adr_source_key(repo_key):
            classification = {
                "item_type": "adr",
                "authority_level": "accepted_adr",
                "status": "proposed",
                "doc_kind": "adr",
            }
        local_id = self._available_document_local_id(
            project_id,
            classification["item_type"],
            document["document_id"],
            repo_key,
            virtual_path,
        )
        uml_suffix = virtual_path.suffix.lower()
        parsed_uml: dict[str, Any] | None = None
        if uml_suffix in {".puml", ".plantuml", ".mmd", ".mermaid"}:
            parsed_uml = (
                parse_mermaid(
                    request.body_text,
                    source_uri=source_uri,
                    source_key=source_key,
                )
                if uml_suffix in {".mmd", ".mermaid"}
                else parse_plantuml(
                    request.body_text,
                    source_uri=source_uri,
                    source_key=source_key,
                )
            )
            diagram_collision = self.conn.execute(
                """
                SELECT diagram_id
                FROM uml_diagrams
                WHERE project_id = ? AND diagram_id = ?
                """,
                (project_id, parsed_uml["diagram_id"]),
            ).fetchone()
            if diagram_collision is not None:
                raise ValueError(
                    "Canonical UML identity collision for "
                    f"{repo_key}: {parsed_uml['diagram_id']} already exists"
                )

        with deferred_export(self.conn):
            if classification["item_type"] == "adr":
                parsed_adr = parse_adr_markdown(
                    request.body_text,
                    source_uri=source_uri,
                    source_key=source_key,
                )
                collision = self.conn.execute(
                    """
                    SELECT item_uid
                    FROM knowledge_items
                    WHERE project_id = ?
                      AND item_type = 'adr'
                      AND local_id = ?
                    """,
                    (project_id, parsed_adr.adr_id),
                ).fetchone()
                if collision is not None:
                    raise ValueError(
                        "Canonical ADR identity collision for "
                        f"{repo_key}: {parsed_adr.adr_id} already exists"
                    )
                parsed_adr.metadata.update(
                    {
                        "source_key": source_key,
                        "repo_source_key": repo_key,
                        "repository_id": request.repository_id,
                        "body_text": request.body_text,
                        "body_encoding": request.body_encoding,
                        "authored_in": "akdb",
                    }
                )
                item = self.knowledge.upsert_adr(project_id, parsed_adr)
                self._link_targets(
                    project_id,
                    item["item_uid"],
                    _markdown_link_targets(request.body_text, virtual_path),
                    evidence=f"canonical ADR create {repo_key}",
                )
                derived: list[dict[str, Any]] = []
            else:
                metadata = {
                    **document.get("metadata", {}),
                    "source_key": source_key,
                    "repo_source_key": repo_key,
                    "repository_id": request.repository_id,
                    "format": document["format"],
                    "doc_kind": classification["doc_kind"],
                    "body_text": request.body_text,
                    "body_encoding": request.body_encoding,
                    "headings": document.get("headings", []),
                    "authored_in": "akdb",
                }
                item_uid = self.knowledge._upsert_item(
                    project_id=project_id,
                    space_id=None,
                    item_type=classification["item_type"],
                    local_id=local_id,
                    title=document["title"],
                    status=classification["status"],
                    authority_level=classification["authority_level"],
                    summary=document["summary"],
                    source_uri=source_uri,
                    metadata=metadata,
                )
                self.knowledge._index_item(item_uid)
                item = self.knowledge.get_item_by_uid(item_uid)
                self._link_document(
                    item,
                    virtual_path,
                    repository_root,
                    request.body_text,
                    document,
                )
                derived = self._import_derived_architecture_records(
                    project_id,
                    item,
                    virtual_path,
                    repository_root,
                    request.body_text,
                    document,
                )
            diagram_id: str | None = None
            if parsed_uml is not None:
                parsed_uml["model"].update(
                    {
                        "source_key": source_key,
                        "repo_source_key": repo_key,
                        "sad_document_id": request.sad_document_id,
                        "authored_in": "akdb",
                    }
                )
                diagram = UMLService(self.conn).upsert_diagram(
                    project_id,
                    parsed_uml,
                )
                diagram_id = diagram["diagram_id"]

        return self._with_auto_export(
            project_id,
            {
                "project_id": project_id,
                "repository_id": request.repository_id,
                "repo_source_key": repo_key,
                "item_uid": item["item_uid"],
                "item_type": item["item_type"],
                "derived_records": len(derived),
                "structured_uml_diagram_id": diagram_id,
            },
        )

    def _available_document_local_id(
        self,
        project_id: str,
        item_type: str,
        local_id: str,
        repo_key: str,
        path: Path,
    ) -> str:
        seen = self._seen_local_ids_for_project(project_id)
        previous = seen.get((item_type, local_id))
        if previous is None or previous == repo_key:
            return local_id
        suffix = path.suffix.lstrip(".").lower() or "file"
        candidate = f"{local_id}--{suffix}"
        previous = seen.get((item_type, candidate))
        if previous is None or previous == repo_key:
            return candidate
        tree_segment = repo_key.split("/", 1)[0].lower() or "root"
        candidate = f"{candidate}--{tree_segment}"
        previous = seen.get((item_type, candidate))
        if previous is not None and previous != repo_key:
            raise ValueError(
                f"Canonical document identity collision for {repo_key}: "
                f"{item_type}/{candidate} already belongs to {previous}"
            )
        return candidate

    def update_canonical_document(
        self,
        project_id: str,
        request: CanonicalDocumentUpdate,
    ) -> dict[str, Any]:
        """Update one existing DB-canonical file without recreating a source file.

        The operation preserves the canonical body's stable knowledge-item
        identity, replaces stale links and imported SAD children, and keeps a
        matching structured ADR or UML record synchronized in the same
        transaction.
        """
        from architectural_knowledge_db.services.export_flush import deferred_export
        from architectural_knowledge_db.services.repositories import RepositoryService
        from architectural_knowledge_db.services.uml import UMLService

        repo_key = _safe_repo_source_key(request.repo_source_key)
        repository = RepositoryService(self.conn).get_repository(
            project_id,
            request.repository_id,
        )
        repository_root = Path(repository["local_path"]).expanduser().resolve()
        if not repository_root.is_dir():
            raise ValueError(
                f"Registered repository path does not exist: {repository_root}"
            )
        virtual_path = repository_root.joinpath(*PurePosixPath(repo_key).parts)
        owners = self._body_owner_rows(project_id, repo_key)
        if not owners:
            raise ValueError(
                f"Canonical document does not exist for repo_source_key {repo_key}"
            )
        if len(owners) > 1:
            owner_ids = ", ".join(row["item_uid"] for row in owners)
            raise ValueError(
                "Multiple canonical body_text owners for repo_source_key "
                f"{repo_key}: {owner_ids}"
            )

        owner = self.knowledge.get_item_by_uid(owners[0]["item_uid"])
        metadata = owner.get("metadata") or {}
        source_key = metadata.get("source_key") or repo_key
        source_uri = f"akdb://{project_id}/canon/{repo_key}"
        text = request.body_text
        self._reject_projected_mirror_body(
            project_id,
            repo_key,
            metadata.get("body_text"),
            text,
        )
        document = parse_document_file(
            virtual_path,
            text,
            source_uri=source_uri,
            source_key=source_key,
        )
        classification = classify_document(source_key, virtual_path, document)
        is_adr = owner["item_type"] == "adr"
        if not is_adr and classification["item_type"] != owner["item_type"]:
            raise ValueError(
                "Canonical update would change item classification from "
                f"{owner['item_type']} to {classification['item_type']}"
            )

        with deferred_export(self.conn):
            if is_adr:
                updated = self._update_canonical_adr(
                    project_id,
                    owner,
                    repo_key,
                    source_key,
                    source_uri,
                    virtual_path,
                    request,
                )
                derived: list[dict[str, Any]] = []
            else:
                self._delete_outgoing_links(owner["item_uid"])
                self._delete_imported_sad_children(owner["item_uid"])
                updated_metadata = {
                    **metadata,
                    **document.get("metadata", {}),
                    "source_key": source_key,
                    "repo_source_key": repo_key,
                    "format": document["format"],
                    "doc_kind": classification["doc_kind"],
                    "body_text": text,
                    "body_encoding": request.body_encoding,
                    "headings": document.get("headings", []),
                    "authored_in": "akdb",
                }
                item_uid = self.knowledge._upsert_item(
                    project_id=project_id,
                    space_id=owner["space_id"],
                    item_type=owner["item_type"],
                    local_id=owner["local_id"],
                    title=document["title"],
                    status=classification["status"],
                    authority_level=classification["authority_level"],
                    summary=document["summary"],
                    source_uri=source_uri,
                    metadata=updated_metadata,
                )
                self.knowledge._index_item(item_uid)
                updated = self.knowledge.get_item_by_uid(item_uid)
                self._link_document(
                    updated,
                    virtual_path,
                    repository_root,
                    text,
                    document,
                )
                derived = self._import_derived_architecture_records(
                    project_id,
                    updated,
                    virtual_path,
                    repository_root,
                    text,
                    document,
                )

            uml = self._update_matching_structured_uml(
                project_id,
                repo_key,
                text,
                UMLService(self.conn),
            )

        return self._with_auto_export(
            project_id,
            {
                "project_id": project_id,
                "repository_id": request.repository_id,
                "repo_source_key": repo_key,
                "item_uid": updated["item_uid"],
                "item_type": updated["item_type"],
                "derived_records": len(derived),
                "structured_uml_updated": uml,
            },
        )

    def _reject_projected_mirror_body(
        self,
        project_id: str,
        repo_source_key: str,
        canonical_body: Any,
        candidate_body: str,
    ) -> None:
        """Reject an exact generated projection presented as canonical input."""
        if not isinstance(canonical_body, str) or candidate_body == canonical_body:
            return
        from architectural_knowledge_db.services.export_targets import (
            ExportTargetsService,
        )

        targets = ExportTargetsService(self.conn)
        for target in targets.list_targets(project_id, enabled_only=True):
            dest_root = targets.resolve_dest_root(project_id, target["target_id"])
            mirror_path = _mirror_path(dest_root, repo_source_key)
            if mirror_path is None:
                continue
            relative_path = mirror_path.relative_to(dest_root).as_posix()
            mirror_root_key = _target_mirror_root_key(target)
            mirror_repo_path = posixpath.join(mirror_root_key, relative_path)
            projected = _project_mirror_body(
                canonical_body,
                repo_source_key,
                mirror_repo_path,
                mirror_root_key,
            )
            if projected != canonical_body and candidate_body == projected:
                raise ValueError(
                    "body_text is the generated projection for export target "
                    f"{target['target_id']}, not canonical authoring text; "
                    "read and edit the AKDB body_text owner instead"
                )

    def _body_owner_rows(
        self,
        project_id: str,
        repo_source_key: str,
    ) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT item_uid, metadata_json
            FROM knowledge_items
            WHERE project_id = ?
              AND json_extract(metadata_json, '$.repo_source_key') = ?
              AND json_extract(metadata_json, '$.body_text') IS NOT NULL
            ORDER BY item_uid
            """,
            (project_id, repo_source_key),
        ).fetchall()

    def _delete_outgoing_links(self, item_uid: str) -> None:
        self.conn.execute(
            "DELETE FROM knowledge_links WHERE source_item_uid = ?",
            (item_uid,),
        )

    def _delete_imported_sad_children(self, parent_item_uid: str) -> None:
        children = self.conn.execute(
            """
            SELECT item_uid
            FROM knowledge_items
            WHERE item_type IN (
                'sad_frontmatter', 'sad_preamble', 'sad_section', 'sad_decision'
            )
              AND json_extract(metadata_json, '$.parent_item_uid') = ?
            """,
            (parent_item_uid,),
        ).fetchall()
        for child in children:
            self.conn.execute(
                "DELETE FROM knowledge_links WHERE source_item_uid = ?",
                (child["item_uid"],),
            )
            self.conn.execute(
                "DELETE FROM fts_knowledge WHERE item_uid = ?",
                (child["item_uid"],),
            )
            self.conn.execute(
                "DELETE FROM knowledge_items WHERE item_uid = ?",
                (child["item_uid"],),
            )

    def _update_canonical_adr(
        self,
        project_id: str,
        owner: dict[str, Any],
        repo_key: str,
        source_key: str,
        source_uri: str,
        virtual_path: Path,
        request: CanonicalDocumentUpdate,
    ) -> dict[str, Any]:
        parsed = parse_adr_markdown(
            request.body_text,
            source_uri=source_uri,
            source_key=source_key,
        )
        if parsed.adr_id != owner["local_id"]:
            raise ValueError(
                "Canonical ADR update would change identity from "
                f"{owner['local_id']} to {parsed.adr_id}"
            )
        self._delete_outgoing_links(owner["item_uid"])
        parsed.metadata.update(
            {
                **(owner.get("metadata") or {}),
                "source_key": source_key,
                "repo_source_key": repo_key,
                "body_text": request.body_text,
                "body_encoding": request.body_encoding,
                "authored_in": "akdb",
            }
        )
        updated = self.knowledge.upsert_adr(
            project_id,
            parsed,
            space_id=owner["space_id"],
        )
        self._link_targets(
            project_id,
            updated["item_uid"],
            _markdown_link_targets(request.body_text, virtual_path),
            evidence=f"canonical ADR update {repo_key}",
        )
        return updated

    def _update_matching_structured_uml(
        self,
        project_id: str,
        repo_key: str,
        body_text: str,
        uml_service: Any,
    ) -> bool:
        if PurePosixPath(repo_key).suffix.lower() not in {
            ".puml",
            ".plantuml",
            ".mmd",
            ".mermaid",
        }:
            return False
        rows = self.conn.execute(
            """
            SELECT diagram_id
            FROM uml_diagrams
            WHERE project_id = ?
              AND (
                  json_extract(model_json, '$.repo_source_key') = ?
                  OR json_extract(model_json, '$.source_key') = ?
              )
            ORDER BY diagram_id
            """,
            (project_id, repo_key, repo_key),
        ).fetchall()
        if len(rows) != 1:
            raise ValueError(
                f"Canonical UML update requires exactly one structured diagram for {repo_key}; "
                f"found {len(rows)}"
            )
        current = uml_service.get_diagram(project_id, rows[0]["diagram_id"])
        model = current.get("model") or {}
        uml_service.update_diagram(
            project_id,
            current["diagram_id"],
            UMLDiagramUpdate(
                title=current["title"],
                notation=current["notation"],
                diagram_kind=current["diagram_kind"],
                source_key=model.get("source_key") or repo_key,
                sad_document_id=model.get("sad_document_id"),
                raw_source=body_text,
            ),
        )
        return True

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

    def export_canon(
        self,
        project_id: str,
        folder: str | Path,
        *,
        clean: bool = True,
        exclude: tuple[str, ...] = ("**/product-facts.yml", "**/product-facts.yaml"),
    ) -> dict[str, Any]:
        """Reproduce the canon at its original repo paths (byte-faithful whole-tree mirror).

        Class H (product-facts.yml) is out of scope for the canon mirror (it
        stays in Git) -- excluded here too because the project may also carry
        unrelated pre-existing "product_fact_sheet" items (a separate AKDB
        feature) that happen to reuse the repo_source_key/body_text metadata
        shape; without this filter their (possibly stale) body_text would
        leak into the mirror and cause spurious verify_canon "mismatched"
        results against the live, since-edited file.
        """
        import fnmatch

        root = Path(folder)
        root.mkdir(parents=True, exist_ok=True)
        if clean:
            _clean_canon_export_root(root)
        items = self.knowledge.list_items(project_id, include_shared=False, limit=100000)
        exported: list[str] = []
        for item in sorted(items, key=lambda it: (it.get("metadata") or {}).get("repo_source_key") or ""):
            metadata = item.get("metadata") or {}
            repo_key = metadata.get("repo_source_key")
            body_text = metadata.get("body_text")
            if not repo_key or body_text is None:
                continue
            if any(fnmatch.fnmatch(repo_key, pat) for pat in exclude):
                continue
            target = _target_for_source_key(root, repo_key, f"{item['local_id']}.md")
            target.parent.mkdir(parents=True, exist_ok=True)
            _write_text_exact_with_encoding(target, body_text, metadata.get("body_encoding", "utf-8"))
            exported.append(target.relative_to(root).as_posix())
        self._write_canon_export_manifest(root, project_id, exported)
        return {"project_id": project_id, "folder": str(root), "exported": len(exported), "files": exported}

    def _write_canon_export_manifest(self, root: Path, project_id: str, files: list[str]) -> None:
        manifest = {"files": sorted(files), "format_version": 1, "project_id": project_id}
        (root / ".akdb-canon-export.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    def verify_canon(
        self,
        project_id: str,
        live_root: str | Path,
        *,
        exclude: tuple[str, ...] = ("**/product-facts.yml", "**/product-facts.yaml"),
    ) -> dict[str, Any]:
        """Byte-diff a fresh canon export against the live repo tree (class-H excluded)."""
        import fnmatch
        import tempfile

        live = Path(live_root)

        def _excluded(rel: str) -> bool:
            return any(fnmatch.fnmatch(rel, pat) for pat in exclude)

        with tempfile.TemporaryDirectory() as tmp:
            fresh = Path(tmp) / "export"
            self.export_canon(project_id, fresh)
            fresh_files = {
                p.relative_to(fresh).as_posix(): p
                for p in fresh.rglob("*")
                if p.is_file() and p.name != ".akdb-canon-export.json"
            }
            live_files = {
                p.relative_to(live).as_posix(): p
                for p in live.rglob("*")
                if p.is_file()
                and (p.relative_to(live).as_posix().startswith("docs/architecture/")
                     or p.relative_to(live).as_posix().startswith("UML/"))
                and not _excluded(p.relative_to(live).as_posix())
            }
            matched = 0
            mismatched: list[str] = []
            for rel, fresh_path in sorted(fresh_files.items()):
                live_path = live / rel
                if live_path.is_file() and live_path.read_bytes() == fresh_path.read_bytes():
                    matched += 1
                else:
                    mismatched.append(rel)
            missing = sorted(set(live_files) - set(fresh_files))
            extra = sorted(set(fresh_files) - set(live_files))
        return {
            "project_id": project_id,
            "live_root": str(live),
            "matched": matched,
            "mismatched": mismatched,
            "missing": missing,
            "extra": extra,
        }

    def export_incremental(self, project_id: str, target_id: str) -> dict[str, Any]:
        """Drain the target's dirty queue, writing/deleting only the changed mirror files.

        A speed optimization over export_sync: correctness never depends on
        this queue (verify_export is the safety net; export_sync the repair).
        """
        from architectural_knowledge_db.services.export_targets import ExportTargetsService

        targets = ExportTargetsService(self.conn)
        target = targets.get_target(project_id, target_id)
        if target is None:
            raise ValueError(f"Unknown export target {target_id} in project {project_id}")
        dest_root = targets.resolve_dest_root(project_id, target_id)
        mirror_root_key = _target_mirror_root_key(target)
        rows = targets.drain_dirty(project_id, target_id)
        written: list[str] = []
        deleted: list[str] = []
        skipped: list[str] = []
        # Coalesce multiple dirty rows for the same item_ref to its LAST
        # recorded op (rows are FIFO-ordered by id; a later dict insert wins).
        latest_by_ref: dict[str, dict[str, Any]] = {}
        for row in rows:
            latest_by_ref[row["item_ref"]] = row
        for item_ref, row in latest_by_ref.items():
            mirror_path = _mirror_path(dest_root, item_ref)
            if mirror_path is None:
                skipped.append(item_ref)
                continue
            if row["op"] == "delete":
                if mirror_path.exists():
                    mirror_path.unlink()
                    _prune_empty_dirs(mirror_path.parent, dest_root)
                deleted.append(str(mirror_path))
                continue
            record = self._find_by_repo_source_key(project_id, item_ref)
            if record is None:
                # The item no longer exists (e.g. upsert-then-delete raced the
                # queue) -- treat as a delete so the mirror doesn't go stale.
                if mirror_path.exists():
                    mirror_path.unlink()
                    _prune_empty_dirs(mirror_path.parent, dest_root)
                deleted.append(str(mirror_path))
                continue
            body_text, encoding = record
            relative_path = mirror_path.relative_to(dest_root).as_posix()
            mirror_repo_path = posixpath.join(mirror_root_key, relative_path)
            body_text = _project_mirror_body(
                body_text,
                item_ref,
                mirror_repo_path,
                mirror_root_key,
            )
            mirror_path.parent.mkdir(parents=True, exist_ok=True)
            _write_text_exact_with_encoding(mirror_path, body_text, encoding)
            written.append(str(mirror_path))
        pending = self._sync_pending_view(project_id, dest_root)
        written.extend(pending["written"])
        deleted.extend(pending["deleted"])
        return {"written": written, "deleted": deleted, "skipped": skipped}

    def _sync_pending_view(self, project_id: str, dest_root: Path) -> dict[str, list[str]]:
        """Write/prune the synthetic `_pending/` mirror (D7) — re-rendered every call.

        Unlike the knowledge-item mirror, `change_items` carry no
        `repo_source_key`/dirty-queue entry, so this is a full (cheap)
        recompute rather than a dirty-queue drain; `verify_export` is still
        the correctness backstop if this hasn't run since a spec closed.
        """
        from architectural_knowledge_db.services.change_sets import ChangeSetService

        expected = ChangeSetService(self.conn).render_pending(project_id, "")
        written: list[str] = []
        deleted: list[str] = []
        for rel, text in expected.items():
            target_path = dest_root / Path(*PurePosixPath(rel).parts)
            encoded = text.encode("utf-8")
            if not target_path.is_file() or target_path.read_bytes() != encoded:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_bytes(encoded)
                written.append(str(target_path))
        pending_dir = dest_root / "_pending"
        if pending_dir.is_dir():
            for existing in list(pending_dir.rglob("*")):
                if not existing.is_file():
                    continue
                rel = existing.relative_to(dest_root).as_posix()
                if rel not in expected:
                    existing.unlink()
                    deleted.append(str(existing))
            _prune_empty_dirs(pending_dir, dest_root)
        return {"written": written, "deleted": deleted}

    def _expected_mirror_files(
        self,
        project_id: str,
        dest_root: Path,
        mirror_root_key: str = "",
    ) -> dict[str, tuple[str, str]]:
        """{mirror-relative path: (body_text, body_encoding)} for every item mappable into dest_root.

        Same source of truth as export_canon: every project item carrying
        repo_source_key + body_text, routed through _mirror_path. This is the
        full-rebuild set used by both verify_export (byte compare) and
        export_sync (full write); export_incremental only ever writes a subset
        of this same mapping, so all three are provably consistent.
        """
        items = self.knowledge.list_items(project_id, include_shared=False, limit=100000)
        expected: dict[str, tuple[str, str]] = {}
        body_owners: dict[str, str] = {}
        for item in items:
            metadata = item.get("metadata") or {}
            repo_key = metadata.get("repo_source_key")
            body_text = metadata.get("body_text")
            if not repo_key or body_text is None:
                continue
            previous_owner = body_owners.get(repo_key)
            if previous_owner is not None:
                raise ValueError(
                    "Multiple canonical body_text owners for repo_source_key "
                    f"{repo_key}: {previous_owner}, {item['item_uid']}"
                )
            body_owners[repo_key] = item["item_uid"]
            mirror_path = _mirror_path(dest_root, repo_key)
            if mirror_path is None:
                continue
            rel = mirror_path.relative_to(dest_root).as_posix()
            mirror_repo_path = posixpath.join(mirror_root_key, rel)
            projected_text = _project_mirror_body(
                body_text,
                repo_key,
                mirror_repo_path,
                mirror_root_key,
            )
            expected[rel] = (projected_text, metadata.get("body_encoding", "utf-8"))
        return expected

    def verify_export(self, project_id: str, target_id: str) -> dict[str, Any]:
        """Byte-compare a fresh regeneration against the committed target mirror.

        The correctness engine behind the freshness gate: matched/mismatched/
        missing/extra, independent of the (speed-only) dirty queue.
        """
        from architectural_knowledge_db.services.export_targets import ExportTargetsService

        target = ExportTargetsService(self.conn).get_target(project_id, target_id)
        if target is None:
            raise ValueError(f"Unknown export target {target_id} in project {project_id}")
        dest_root = ExportTargetsService(self.conn).resolve_dest_root(project_id, target_id)
        expected = self._expected_mirror_files(
            project_id,
            dest_root,
            _target_mirror_root_key(target),
        )
        actual = (
            {
                p.relative_to(dest_root).as_posix(): p
                for p in dest_root.rglob("*")
                if p.is_file() and p.name not in _MIRROR_RESERVED_NAMES
            }
            if dest_root.is_dir()
            else {}
        )
        matched = 0
        mismatched: list[str] = []
        for rel, (body_text, encoding) in sorted(expected.items()):
            actual_path = actual.get(rel)
            if actual_path is None:
                continue
            expected_bytes = _encode_text_exact(body_text, encoding)
            if actual_path.read_bytes() == expected_bytes:
                matched += 1
            else:
                mismatched.append(rel)

        # `_pending/*` (D7) is a synthetic projection re-rendered fresh here,
        # NOT a body_text round-trip -- keep it out of `expected`/_expected_mirror_files
        # (the byte-exact canon set) and compare separately.
        from architectural_knowledge_db.services.change_sets import ChangeSetService

        pending_expected = ChangeSetService(self.conn).render_pending(project_id, "")
        for rel, text in sorted(pending_expected.items()):
            actual_path = actual.get(rel)
            if actual_path is None:
                continue
            if actual_path.read_bytes() == text.encode("utf-8"):
                matched += 1
            else:
                mismatched.append(rel)

        expected_keys = set(expected) | set(pending_expected)
        missing = sorted(expected_keys - set(actual))
        extra = sorted(set(actual) - expected_keys)
        return {
            "project_id": project_id,
            "target_id": target_id,
            "dest_root": str(dest_root),
            "matched": matched,
            "mismatched": mismatched,
            "missing": missing,
            "extra": extra,
        }

    def export_sync(self, project_id: str, target_id: str) -> dict[str, Any]:
        """Full rebuild of a target's mirror: write everything expected, prune extras, clear its dirty queue."""
        from architectural_knowledge_db.services.export_targets import ExportTargetsService

        targets = ExportTargetsService(self.conn)
        target = targets.get_target(project_id, target_id)
        if target is None:
            raise ValueError(f"Unknown export target {target_id} in project {project_id}")
        dest_root = targets.resolve_dest_root(project_id, target_id)
        dest_root.mkdir(parents=True, exist_ok=True)
        expected = self._expected_mirror_files(
            project_id,
            dest_root,
            _target_mirror_root_key(target),
        )
        written: list[str] = []
        for rel, (body_text, encoding) in expected.items():
            target_path = dest_root / Path(*PurePosixPath(rel).parts)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            _write_text_exact_with_encoding(target_path, body_text, encoding)
            written.append(str(target_path))
        pruned: list[str] = []
        for existing in list(dest_root.rglob("*")):
            if not existing.is_file() or existing.name in _MIRROR_RESERVED_NAMES:
                continue
            rel = existing.relative_to(dest_root).as_posix()
            if rel in expected or rel.startswith("_pending/"):
                continue
            existing.unlink()
            pruned.append(str(existing))
        pending = self._sync_pending_view(project_id, dest_root)
        written.extend(pending["written"])
        pruned.extend(pending["deleted"])
        for existing in sorted(dest_root.rglob("*"), reverse=True):
            if existing.is_dir() and not any(existing.iterdir()):
                existing.rmdir()
        targets.drain_dirty(project_id, target_id)
        return {"written": written, "pruned": pruned}

    def _find_by_repo_source_key(self, project_id: str, repo_source_key: str) -> tuple[str, str] | None:
        rows = self.conn.execute(
            """
            SELECT item_uid, metadata_json FROM knowledge_items
            WHERE project_id = ? AND json_extract(metadata_json, '$.repo_source_key') = ?
            ORDER BY item_uid
            """,
            (project_id, repo_source_key),
        ).fetchall()
        payloads: list[tuple[str, str]] = []
        for row in rows:
            metadata = json.loads(row["metadata_json"] or "{}")
            body_text = metadata.get("body_text")
            if body_text is not None:
                payloads.append((body_text, metadata.get("body_encoding", "utf-8")))
        if not payloads:
            return None
        if len(payloads) > 1:
            raise ValueError(
                f"Multiple canonical body_text owners for repo_source_key {repo_source_key}"
            )
        return payloads[0]

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

        preamble = parse_sad_preamble(text)
        if preamble:
            local_id = f"{document['document_id']}:preamble"
            item_uid = self.knowledge._upsert_item(
                project_id=project_id,
                space_id=None,
                item_type="sad_preamble",
                local_id=local_id,
                title=f"{document['title']} preamble",
                status=None,
                authority_level="project_note",
                summary=first_sentence(preamble),
                source_uri=str(path),
                metadata={
                    "source_key": document["source_key"],
                    "repo_source_key": repo_relative_key(path),
                    "parent_item_uid": parent_item["item_uid"],
                    "body_md": preamble,
                },
            )
            self.knowledge._index_item(item_uid)
            created.append(self.knowledge.get_item_by_uid(item_uid))

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
                    "order": decision["order"],
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

        for section in parse_sad_sections(text):
            local_id = f"{document['document_id']}:section:{section['order']:02d}"
            item_uid = self.knowledge._upsert_item(
                project_id=project_id,
                space_id=None,
                item_type="sad_section",
                local_id=local_id,
                title=section["title"],
                status=None,
                authority_level="project_note",
                summary=None,
                source_uri=str(path),
                metadata={
                    "source_key": document["source_key"],
                    "repo_source_key": repo_relative_key(path),
                    "parent_item_uid": parent_item["item_uid"],
                    "order": section["order"],
                    "level": section["level"],
                    "role": section["role"],
                    "body_md": section["body_md"],
                },
            )
            self.knowledge._index_item(item_uid)
            created.append(self.knowledge.get_item_by_uid(item_uid))
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
    bare = re.sub(r"^\d+_", "", normalized)
    roles = {
        "status": "status",
        "context": "context",
        "decision": "decision",
        "consequences": "consequences",
        "supersedes": "supersedes",
        "superseded_by": "superseded_by",
        "decisions": "decisions",
        "architecture_decisions": "decisions",
        "architecture_decision": "decisions",
    }
    if bare in roles:
        return roles[bare]
    if bare.endswith("_decisions") or "architecture_decision" in bare:
        return "decisions"
    return roles.get(normalized, "other")


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


def parse_sad_decisions(text: str) -> list[dict[str, Any]]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    decisions = []
    matches = list(SAD_DECISION_RE.finditer(text))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        next_main_section = SAD_MAIN_SECTION_RE.search(text, start, end)
        if next_main_section:
            end = next_main_section.start()
        body = text[start:end].strip()
        status_match = re.search(r"\*\*Status:\*\*\s*([A-Za-z_ -]+)", body)
        decisions.append(
            {
                "decision_id": match.group("decision_id"),
                "order": index,
                "title": match.group("title").strip(),
                "status": (status_match.group(1).strip().lower() if status_match else "accepted"),
                "summary": first_sentence(body) or match.group("title").strip(),
                "body_md": body,
            }
        )
    return decisions


def parse_sad_preamble(text: str) -> str:
    """Return structured content between optional frontmatter and the first main section."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    frontmatter_match = FRONTMATTER_RE.match(text)
    start = frontmatter_match.end() if frontmatter_match else 0
    first_section = SAD_MAIN_SECTION_RE.search(text, start)
    end = first_section.start() if first_section else len(text)
    return text[start:end].strip("\n")


def _decision_status(item: dict[str, Any]) -> str:
    body = ((item.get("metadata") or {}).get("body_md") or "").strip("\n")
    status_match = re.match(r"\*\*Status:\*\*\s*([^\n]+)", body)
    if status_match:
        return status_match.group(1).strip()
    status = item.get("status") or "proposed"
    return status.capitalize() if isinstance(status, str) and status.islower() else str(status)


def _sync_decision_summary(prefix: str, decisions: list[dict[str, Any]]) -> str:
    """Keep a Markdown decision summary table consistent with structured decision items."""
    lines = prefix.splitlines()
    table_rows: dict[str, int] = {}
    separator_index: int | None = None
    last_row_index: int | None = None
    for index, line in enumerate(lines):
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if len(cells) < 3:
            continue
        if set(cells[0]) <= {"-", ":"}:
            separator_index = index
            continue
        if cells[0].lower() == "id":
            continue
        table_rows[cells[0].lower()] = index
        last_row_index = index

    if separator_index is None:
        return prefix

    missing: list[str] = []
    for decision in decisions:
        metadata = decision.get("metadata") or {}
        decision_id = str(metadata.get("decision_id") or "")
        row_index = table_rows.get(decision_id.lower())
        if row_index is None:
            title = decision["title"].split(":", 1)[1].strip() if ":" in decision["title"] else decision["title"]
            missing.append(f"| {decision_id} | {title} | {_decision_status(decision)} |")
            continue
        cells = [cell.strip() for cell in lines[row_index].split("|")[1:-1]]
        cells[2] = _decision_status(decision)
        lines[row_index] = "| " + " | ".join(cells) + " |"

    if missing:
        insert_at = (last_row_index if last_row_index is not None else separator_index) + 1
        lines[insert_at:insert_at] = missing
    return "\n".join(lines)


def parse_sad_sections(text: str) -> list[dict[str, Any]]:
    """Split a SAD into its '## ' main sections with verbatim body text and order."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.splitlines(keepends=True)
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    order = 0
    for line in lines:
        m = HEADING_RE.match(line.rstrip("\n"))
        if m and len(m.group(1)) == 2:
            if current is not None:
                current["body_md"] = "".join(current.pop("_body")).strip("\n")
                sections.append(current)
            title = m.group(2).strip()
            current = {
                "order": order,
                "level": 2,
                "title": title,
                "role": section_role(title),
                "_body": [],
            }
            order += 1
        elif current is not None:
            current["_body"].append(line)
    if current is not None:
        current["body_md"] = "".join(current.pop("_body")).strip("\n")
        sections.append(current)
    return sections


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


def _safe_repo_source_key(value: str) -> str:
    normalized = str(value or "").strip().replace("\\", "/")
    candidate = PurePosixPath(normalized)
    if (
        not normalized
        or candidate.is_absolute()
        or any(part in {"", ".", ".."} for part in candidate.parts)
        or any(":" in part for part in candidate.parts)
    ):
        raise ValueError(
            "repo_source_key must be a safe repository-relative path without traversal"
        )
    return candidate.as_posix()


def _canonical_source_key(repo_source_key: str) -> str:
    normalized = repo_source_key.replace("\\", "/")
    lowered = normalized.lower()
    for prefix in ("docs/architecture/", "docs/adr/", "uml/"):
        if lowered.startswith(prefix):
            return normalized[len(prefix):]
    return normalized


def _is_canonical_adr_source_key(repo_source_key: str) -> bool:
    normalized = repo_source_key.replace("\\", "/").lower()
    return normalized.endswith(".md") and (
        normalized.startswith("docs/adr/") or normalized.startswith("adr/")
    )


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


# BOM-prefixed encodings found in the real canon (e.g. Windows PowerShell
# `> file.log` redirection emits UTF-16 LE). Kept as explicit byte prefixes
# (rather than relying on the "utf-16"/"utf-8-sig" codecs' own BOM-on-encode
# behavior, which is native-byte-order-dependent) so decode -> encode is a
# deterministic, byte-exact round trip regardless of host architecture.
_UTF16_LE_BOM = b"\xff\xfe"
_UTF16_BE_BOM = b"\xfe\xff"
_UTF8_BOM = b"\xef\xbb\xbf"


def _decode_text_exact(raw: bytes) -> tuple[str, str]:
    """Decode raw file bytes, returning (text, encoding) for an exact re-encode later."""
    if raw.startswith(_UTF16_LE_BOM):
        return raw[len(_UTF16_LE_BOM):].decode("utf-16-le"), "utf-16-le-bom"
    if raw.startswith(_UTF16_BE_BOM):
        return raw[len(_UTF16_BE_BOM):].decode("utf-16-be"), "utf-16-be-bom"
    if raw.startswith(_UTF8_BOM):
        return raw[len(_UTF8_BOM):].decode("utf-8"), "utf-8-sig"
    return raw.decode("utf-8"), "utf-8"


def _read_text_exact_any_encoding(path: Path) -> tuple[str, str]:
    """Like _read_text_exact, but detects non-UTF-8 canon files instead of raising."""
    return _decode_text_exact(path.read_bytes())


def _encode_text_exact(text: str, encoding: str) -> bytes:
    """Byte-encode text using the exact encoding+BOM it was ingested with."""
    if encoding == "utf-16-le-bom":
        return _UTF16_LE_BOM + text.encode("utf-16-le")
    if encoding == "utf-16-be-bom":
        return _UTF16_BE_BOM + text.encode("utf-16-be")
    if encoding == "utf-8-sig":
        return _UTF8_BOM + text.encode("utf-8")
    return text.encode("utf-8")


def _write_text_exact_with_encoding(path: Path, text: str, encoding: str) -> None:
    """Write text back using the exact encoding+BOM it was ingested with."""
    path.write_bytes(_encode_text_exact(text, encoding))


_MIRROR_ROOT_RULES: tuple[tuple[str, str], ...] = (
    ("docs/architecture/", ""),
    ("UML/", "UML/"),
    ("docs/ADR/", "ADR/"),
)
_MIRROR_EXCLUDE: tuple[str, ...] = ("**/product-facts.yml", "**/product-facts.yaml")
# Hand-written, non-DB-backed marker files that are expected to live alongside a
# mirror (e.g. the Plan B "do not edit, regenerated from AKDB" banner). Never
# flagged as verify_export "extra" and never pruned by export_sync.
_MIRROR_RESERVED_NAMES: frozenset[str] = frozenset({"GENERATED.md"})


def _mirror_path(dest_root: str | Path, repo_source_key: str) -> Path | None:
    """Map a repo-relative source key to its path under a target's mirror root.

    docs/architecture/<rest> -> <dest_root>/<rest>
    UML/<rest>               -> <dest_root>/UML/<rest>
    docs/ADR/<rest>          -> <dest_root>/ADR/<rest>
    class-H (product-facts.yml) and anything outside these three roots -> None (skip).
    """
    import fnmatch

    normalized = repo_source_key.replace("\\", "/")
    if any(fnmatch.fnmatch(normalized, pattern) for pattern in _MIRROR_EXCLUDE):
        return None
    for prefix, mirror_prefix in _MIRROR_ROOT_RULES:
        if normalized.startswith(prefix):
            rest = normalized[len(prefix):]
            if not rest:
                return None
            rel = f"{mirror_prefix}{rest}"
            candidate = PurePosixPath(rel)
            if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
                return None
            return Path(dest_root) / Path(*candidate.parts)
    return None


def _target_mirror_root_key(target: dict[str, Any]) -> str:
    configured = str(target.get("dest_root") or "").replace("\\", "/")
    if not configured or Path(configured).is_absolute():
        return ""
    return str(PurePosixPath(configured))


_REPO_ROOT_LINK_PREFIXES = frozenset(
    {
        "AIPlugins",
        "Automation",
        "BridgePlugins",
        "Config",
        "docs",
        "EnginePlugins",
        "Gates",
        "GovernanceDevelopmentPlugins",
        "ScenePlugins",
        "Source",
        "Tools",
        "UML",
    }
)


def _project_mirror_body(
    body_text: str,
    repo_source_key: str,
    mirror_relative_path: str,
    mirror_root_key: str,
) -> str:
    source_suffix = PurePosixPath(repo_source_key.replace("\\", "/")).suffix.lower()
    mirror_suffix = PurePosixPath(mirror_relative_path.replace("\\", "/")).suffix.lower()
    if source_suffix not in {".md", ".markdown"} or mirror_suffix != source_suffix:
        return body_text
    source_parent = posixpath.dirname(repo_source_key.replace("\\", "/"))
    mirror_parent = posixpath.dirname(mirror_relative_path.replace("\\", "/"))
    if source_parent == mirror_parent:
        return body_text

    lines: list[str] = []
    fence_char = ""
    fence_length = 0
    for line in body_text.splitlines(keepends=True):
        fence = MARKDOWN_FENCE_RE.match(line)
        if fence_char:
            if fence:
                marker = fence.group("fence")
                if marker[0] == fence_char and len(marker) >= fence_length:
                    fence_char = ""
                    fence_length = 0
            lines.append(line)
            continue
        if fence:
            marker = fence.group("fence")
            fence_char = marker[0]
            fence_length = len(marker)
            lines.append(line)
            continue
        lines.append(
            MIRROR_MARKDOWN_LINK_RE.sub(
                lambda match: (
                    f"{match.group('prefix')}"
                    f"{_rebase_markdown_target(
                        match.group('target'),
                        source_parent,
                        mirror_parent,
                        mirror_root_key,
                    )}"
                    f"{match.group('suffix')}"
                ),
                line,
            )
        )
    return "".join(lines)


def _rebase_markdown_target(
    raw_target: str,
    source_parent: str,
    mirror_parent: str,
    mirror_root_key: str,
) -> str:
    leading = raw_target[: len(raw_target) - len(raw_target.lstrip())]
    trailing = raw_target[len(raw_target.rstrip()) :]
    value = raw_target.strip()
    if not value or value.startswith("#"):
        return raw_target

    wrapped = value.startswith("<")
    target_value = value
    title_suffix = ""
    if wrapped:
        closing = value.find(">")
        if closing < 0:
            return raw_target
        target_value = value[1:closing]
        title_suffix = value[closing + 1 :]
    else:
        match = re.fullmatch(r"(?P<target>\S+)(?P<title>\s+(?:\"[^\"]*\"|'[^']*'))?", value)
        if not match:
            return raw_target
        target_value = match.group("target")
        title_suffix = match.group("title") or ""

    parsed = urlsplit(target_value)
    if parsed.scheme or parsed.netloc or not parsed.path or parsed.path.startswith("/"):
        return raw_target
    normalized_path = parsed.path.replace("\\", "/")
    first_segment = normalized_path.split("/", 1)[0]
    if not normalized_path.startswith(".") and first_segment in _REPO_ROOT_LINK_PREFIXES:
        return raw_target

    canonical_target = posixpath.normpath(posixpath.join(source_parent, normalized_path))
    mapped_target = _mirror_path(Path("."), canonical_target)
    if mapped_target is not None:
        mapped_relative = mapped_target.as_posix()
        if mapped_relative.startswith("./"):
            mapped_relative = mapped_relative[2:]
        projected_target = posixpath.join(mirror_root_key, mapped_relative)
    elif mirror_root_key:
        projected_target = canonical_target
    else:
        # An absolute export destination may live outside the registered
        # repository, so its relative route back to a non-mirrored source is
        # unknowable. Preserve that source link instead of fabricating one.
        return raw_target

    rebased_path = posixpath.relpath(projected_target, mirror_parent)
    if normalized_path.endswith("/") and not rebased_path.endswith("/"):
        rebased_path += "/"
    rebased_target = urlunsplit(("", "", rebased_path, parsed.query, parsed.fragment))
    if wrapped:
        rebased_target = f"<{rebased_target}>{title_suffix}"
    else:
        rebased_target = f"{rebased_target}{title_suffix}"
    return f"{leading}{rebased_target}{trailing}"


def _prune_empty_dirs(start: Path, stop_at: Path) -> None:
    stop = Path(stop_at)
    current = start
    while current != stop and current.is_dir() and not any(current.iterdir()):
        parent = current.parent
        current.rmdir()
        if parent == current:
            break
        current = parent


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


def _clean_canon_export_root(root: Path) -> None:
    """Full wipe for export_canon()'s whole-tree mirror.

    Real gap found in Phase 4 (2026-07-23): _clean_export_root() only clears
    MANAGED_EXPORT_ENTRIES ("adr", "documents", "uml", ...) -- the OLDER,
    separate per-type export layout used by export_corpus(). export_canon()
    instead reproduces the live repo's own top-level layout ("docs/", "UML/"),
    which is never in that allowlist, so a file whose source item was later
    removed from the project (deleted/renamed live, or cleaned up as a stale
    DB orphan) stayed on disk forever -- a silent, permanent drift in the
    byte-faithful mirror that verify_canon() never catches (it exports into
    a fresh temp dir, not this persistent root). export_canon() owns its
    entire root exclusively, so a full wipe is correct here.
    """
    if not root.is_dir():
        return
    for entry in root.iterdir():
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()


def _auto_export_root_for_connection(conn: Any) -> Path | None:
    # Resolves the on-disk SQLite file for workspace auto-export layout.
    # PostgreSQL has no local DB file / PRAGMA; still honor explicit env export roots.
    if getattr(conn, "is_postgres", False):
        from architectural_knowledge_db.config import Settings

        return Settings.from_env().auto_export_root
    row = conn.execute("PRAGMA database_list").fetchone()
    if row is None:
        return None
    database_file = row["file"] if isinstance(row, sqlite3.Row) else row[2]
    if not database_file:
        return None
    return auto_export_root_for_database(database_file)
