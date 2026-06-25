from __future__ import annotations

import re
import sqlite3
import posixpath
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from architectural_knowledge_db.ids import digest_uid
from architectural_knowledge_db.services.jsonutil import dumps, loads
from architectural_knowledge_db.services.knowledge import normalize_path
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.services.repositories import RepositoryService


class StalenessService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.projects = ProjectService(conn)
        self.repositories = RepositoryService(conn)

    def add_report(
        self,
        project_id: str,
        target_ref: str,
        target_type: str,
        status: str,
        reason: str | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.projects.require_project(project_id)
        report_uid = digest_uid("staleness", project_id, target_ref, target_type, status, reason or "")
        self.conn.execute(
            """
            INSERT INTO staleness_reports(report_uid, project_id, target_ref, target_type, status, reason, evidence_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(report_uid) DO UPDATE SET
              status = excluded.status,
              reason = excluded.reason,
              evidence_json = excluded.evidence_json,
              created_at = CURRENT_TIMESTAMP
            """,
            (report_uid, project_id, target_ref, target_type, status, reason, dumps(evidence or {})),
        )
        return self.get_report(report_uid)

    def get_report(self, report_uid: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM staleness_reports WHERE report_uid = ?", (report_uid,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown staleness report: {report_uid}")
        result = dict(row)
        result["evidence"] = loads(result.pop("evidence_json"), {})
        return result

    def list_reports(
        self,
        project_id: str,
        target: str | None = None,
        status_filter: list[str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self.projects.require_project(project_id)
        clauses = ["project_id = ?"]
        params: list[Any] = [project_id]
        if target:
            clauses.append("target_ref = ?")
            params.append(target)
        if status_filter:
            clauses.append(f"status IN ({','.join('?' for _ in status_filter)})")
            params.extend(status_filter)
        params.append(limit)
        rows = self.conn.execute(
            f"""
            SELECT *
            FROM staleness_reports
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        results = []
        for row in rows:
            result = dict(row)
            result["evidence"] = loads(result.pop("evidence_json"), {})
            results.append(result)
        return results

    def compute(
        self,
        project_id: str,
        mode: str = "status_quo",
        target: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        normalized_mode = mode.replace("-", "_").lower()
        if normalized_mode in {"status_quo", "statusquo", "current"}:
            return self.compute_status_quo(project_id, target=target, limit=limit)
        if normalized_mode in {"git", "git_timeline", "timeline", "history"}:
            return self.compute_project(project_id)
        if normalized_mode == "combined":
            return self.run_drift_check(project_id, target=target, limit=limit)
        raise ValueError(f"Unknown staleness mode: {mode}")

    def run_drift_check(
        self,
        project_id: str,
        target: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Run the complete drift script and return an agent-sized summary.

        This executes every drift signal:

        - status-quo content checks against the current repository snapshot
        - Git timeline checks for provenance and evolution context

        The database receives every generated report. The returned payload is
        intentionally summarized so agents can use it without suppressing a
        mode or flooding their context with tens of thousands of low-level
        timeline rows.
        """

        status_quo = self.compute_status_quo(project_id, target=target, limit=None)
        git_timeline = self.compute_project(project_id)
        persisted_counts = self._report_counts(project_id)
        status_quo_findings = status_quo["findings"]
        returned_limit = max(limit, 0)
        return {
            "project_id": project_id,
            "mode": "complete_drift_run",
            "modes_run": ["status_quo", "git_timeline"],
            "completeness": {
                "status_quo_candidates_persisted": status_quo["candidate_count"],
                "git_timeline_reports_persisted": git_timeline["generated"],
                "returned_findings_limit": returned_limit,
                "returned_payload_is_summary": True,
            },
            "status_quo": {
                "documents_checked": status_quo["documents_checked"],
                "files_indexed": status_quo["files_indexed"],
                "code_symbols_indexed": status_quo["code_symbols_indexed"],
                "candidate_count": status_quo["candidate_count"],
                "generated_reports": status_quo["generated"],
                "summary": status_quo["summary"],
                "top_areas": _top_areas(status_quo_findings, limit=12),
                "top_documents": _top_documents(status_quo_findings, limit=12),
                "top_findings": status_quo_findings[:returned_limit],
            },
            "git_timeline": {
                "generated_reports": git_timeline["generated"],
                "summary": _git_timeline_summary(persisted_counts),
            },
            "database_report_counts": persisted_counts,
            "agent_guidance": {
                "primary_mode": "Use status_quo to find current document/code drift.",
                "provenance_mode": "Use git_timeline to explain when or why a suspected drift emerged.",
                "knowledgebase_mode": "Use search/context-pack first when the task is architectural understanding rather than drift triage.",
            },
        }

    def compute_project(self, project_id: str) -> dict[str, Any]:
        self.projects.require_project(project_id)
        generated = []
        linked_rows = self.conn.execute(
            """
            SELECT ki.item_uid, ki.item_type, ki.local_id, ki.updated_at,
                   kl.target_ref
            FROM knowledge_items ki
            JOIN knowledge_links kl ON kl.source_item_uid = ki.item_uid
            WHERE ki.project_id = ?
              AND (kl.target_ref LIKE '%.%' OR kl.target_ref LIKE '%/%')
            """,
            (project_id,),
        ).fetchall()
        for row in linked_rows:
            history = self.conn.execute(
                """
                SELECT *
                FROM git_file_history
                WHERE project_id = ? AND file_path = ?
                ORDER BY last_changed_at DESC
                LIMIT 1
                """,
                (project_id, row["target_ref"]),
            ).fetchone()
            if history is None:
                continue
            status = "current"
            reason = f"{row['target_ref']} has no newer scanned changes than {row['local_id']}."
            if str(history["last_changed_at"]) > str(row["updated_at"]):
                status = "review_recommended"
                reason = f"{row['target_ref']} changed after {row['item_type']} {row['local_id']} was updated."
            generated.append(
                self.add_report(
                    project_id,
                    row["item_uid"],
                    row["item_type"],
                    status,
                    reason,
                    {
                        "target_ref": row["target_ref"],
                        "last_changed_at": history["last_changed_at"],
                        "last_changed_commit_hash": history["last_changed_commit_hash"],
                        "knowledge_updated_at": row["updated_at"],
                    },
                )
            )
        return {"project_id": project_id, "mode": "git_timeline", "generated": len(generated), "reports": generated}

    def find_status_quo_drifts(
        self,
        project_id: str,
        target: str | None = None,
        limit: int | None = 100,
    ) -> dict[str, Any]:
        """Find current-content drift without using Git timestamps as the signal.

        Git can explain when or why a drift happened. This path checks whether
        the current documents still point at files and symbols that exist in the
        current repository snapshot.
        """

        self.projects.require_project(project_id)
        snapshot = _RepositorySnapshot.build(self.repositories.list_repositories(project_id))
        documents = _load_documents(self.conn, project_id, target)
        findings: list[dict[str, Any]] = []
        checked_documents = 0
        for document in documents:
            if not document.body.strip():
                continue
            checked_documents += 1
            findings.extend(_file_reference_findings(document, snapshot))
            findings.extend(_symbol_reference_findings(document, snapshot))
            findings.extend(_implementation_status_findings(document, snapshot))

        findings = _dedupe_findings(findings)
        findings.sort(key=_finding_sort_key)
        limited = findings if limit is None else findings[: max(limit, 0)]
        return {
            "project_id": project_id,
            "mode": "status_quo",
            "repositories_checked": len(snapshot.repositories),
            "files_indexed": len(snapshot.files_by_lower),
            "code_symbols_indexed": len(snapshot.symbol_locations),
            "documents_checked": checked_documents,
            "candidate_count": len(findings),
            "summary": _summarize_findings(findings),
            "findings": limited,
        }

    def compute_status_quo(
        self,
        project_id: str,
        target: str | None = None,
        limit: int | None = 500,
    ) -> dict[str, Any]:
        self.projects.require_project(project_id)
        if target is None:
            self.conn.execute(
                "DELETE FROM staleness_reports WHERE project_id = ? AND target_type = 'status_quo_drift'",
                (project_id,),
            )
        result = self.find_status_quo_drifts(project_id, target=target, limit=None)
        reports = []
        for finding in result["findings"]:
            reports.append(
                self.add_report(
                    project_id,
                    finding["document"]["uid"],
                    "status_quo_drift",
                    finding["status"],
                    finding["reason"],
                    finding,
                )
            )
        result["generated"] = len(reports)
        result["reports"] = reports
        if limit is not None:
            result["findings"] = result["findings"][: max(limit, 0)]
            result["returned_findings_limit"] = max(limit, 0)
        return result

    def _report_counts(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT target_type, status, COUNT(*) AS count
            FROM staleness_reports
            WHERE project_id = ?
            GROUP BY target_type, status
            ORDER BY target_type, status
            """,
            (project_id,),
        ).fetchall()
        return [dict(row) for row in rows]


@dataclass
class _Document:
    uid: str
    item_type: str
    local_id: str
    title: str
    source_uri: str | None
    body: str
    uml_elements: list[dict[str, Any]] = field(default_factory=list)

    def as_evidence(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "item_type": self.item_type,
            "local_id": self.local_id,
            "title": self.title,
            "source_uri": self.source_uri,
        }


@dataclass
class _RepositorySnapshot:
    repositories: list[dict[str, Any]]
    files_by_lower: dict[str, str]
    absolute_to_relative: dict[str, str]
    alias_files_by_lower: dict[str, str]
    repository_aliases: set[str]
    sibling_alias_roots: dict[str, str]
    basenames: dict[str, list[str]]
    symbol_locations: dict[str, list[str]]

    @classmethod
    def build(cls, repositories: list[dict[str, Any]]) -> "_RepositorySnapshot":
        files_by_lower: dict[str, str] = {}
        absolute_to_relative: dict[str, str] = {}
        alias_files_by_lower: dict[str, str] = {}
        repository_aliases: set[str] = set()
        resolved_roots: list[Path] = []
        basenames: dict[str, list[str]] = defaultdict(list)
        symbol_locations: dict[str, list[str]] = defaultdict(list)
        for repository in repositories:
            root = Path(repository["local_path"])
            if not root.exists():
                continue
            repo_alias = root.name
            repository_aliases.add(repo_alias.lower())
            resolved_roots.append(root.resolve())
            for path in _iter_repository_files(root):
                relative = normalize_path(str(path.relative_to(root)))
                if not _should_index_path(relative, repository):
                    continue
                lower = relative.lower()
                files_by_lower[lower] = relative
                if repo_alias:
                    alias_files_by_lower[f"{repo_alias}/{relative}".lower()] = relative
                absolute_to_relative[normalize_path(str(path.resolve())).lower()] = relative
                basenames[path.name.lower()].append(relative)
                if _is_code_file(relative):
                    for symbol in _symbols_from_file(path):
                        symbol_locations[symbol.lower()].append(relative)
                    stem = path.stem
                    if _looks_like_symbol(stem):
                        symbol_locations[stem.lower()].append(relative)
        for paths in basenames.values():
            paths.sort()
        for paths in symbol_locations.values():
            paths.sort()
        sibling_alias_roots = _discover_sibling_alias_roots(resolved_roots, repository_aliases)
        return cls(
            repositories=repositories,
            files_by_lower=files_by_lower,
            absolute_to_relative=absolute_to_relative,
            alias_files_by_lower=alias_files_by_lower,
            repository_aliases=repository_aliases,
            sibling_alias_roots=sibling_alias_roots,
            basenames=dict(basenames),
            symbol_locations=dict(symbol_locations),
        )

    def relative_for(self, raw_path: str | None) -> str | None:
        if not raw_path:
            return None
        normalized = normalize_path(raw_path)
        direct = self.files_by_lower.get(normalized.lower())
        if direct:
            return direct
        aliased = self.alias_files_by_lower.get(normalized.lower())
        if aliased:
            return aliased
        absolute = self.absolute_to_relative.get(normalize_path(str(Path(raw_path).resolve())).lower())
        if absolute:
            return absolute
        for repository in self.repositories:
            root = normalize_path(str(Path(repository["local_path"]).resolve()))
            if normalized.lower().startswith(root.lower().rstrip("/") + "/"):
                return normalized[len(root.rstrip("/")) + 1 :]
        return None

    def resolve_path_reference(self, reference: str, document: _Document) -> dict[str, Any]:
        normalized = _clean_path_reference(reference)
        if not normalized:
            return {"kind": "ignored"}
        exact = self.relative_for(normalized)
        if exact:
            return {"kind": "exact", "path": exact}
        if Path(normalized).is_absolute():
            external = self._external_absolute_reference(normalized)
            if external:
                return external
            return {"kind": "ignored"}

        direct = self.files_by_lower.get(normalized.lower())
        if direct:
            return {"kind": "exact", "path": direct}
        aliased = self.alias_files_by_lower.get(normalized.lower())
        if aliased:
            return {"kind": "exact", "path": aliased}

        document_path = self.relative_for(document.source_uri)
        if document_path and not normalized.startswith("/"):
            relative_to_doc = normalize_path(posixpath.normpath(posixpath.join(posixpath.dirname(document_path), normalized)))
            match = self.files_by_lower.get(relative_to_doc.lower())
            if match:
                return {"kind": "exact", "path": match}

        suffix_matches = self._suffix_matches(normalized, document_path)
        if len(suffix_matches) == 1:
            return {"kind": "exact", "path": suffix_matches[0]}

        candidates = self.basenames.get(Path(normalized).name.lower(), [])
        same_area_candidates = self._same_area_candidates(document_path, candidates)
        if len(same_area_candidates) == 1:
            candidate = same_area_candidates[0]
            if "/" not in normalized and "\\" not in normalized:
                return {"kind": "exact", "path": candidate}
            return {"kind": "moved", "reference": normalized, "candidates": [candidate]}
        if len(candidates) == 1:
            candidate = candidates[0]
            if "/" not in normalized and "\\" not in normalized:
                return {"kind": "exact", "path": candidate}
            return {"kind": "moved", "reference": normalized, "candidates": [candidate]}
        if candidates:
            return {"kind": "ignored"}
        external = self._external_repository_reference(normalized)
        if external:
            return external
        return {"kind": "missing", "reference": normalized, "candidates": []}

    def _suffix_matches(self, reference: str, document_path: str | None) -> list[str]:
        if "/" not in reference and "\\" not in reference:
            return []
        lower_suffix = "/" + normalize_path(reference).lower().lstrip("/")
        matches = [path for key, path in self.files_by_lower.items() if key.endswith(lower_suffix)]
        same_area = self._same_area_candidates(document_path, matches)
        return same_area or matches

    def _same_area_candidates(self, document_path: str | None, candidates: list[str]) -> list[str]:
        document_area = _component_key(document_path)
        if not document_area:
            return []
        return [candidate for candidate in candidates if _component_key(candidate) == document_area]

    def _external_repository_reference(self, reference: str) -> dict[str, Any] | None:
        parts = normalize_path(reference).split("/")
        if len(parts) < 2:
            return None
        alias = parts[0].lower()
        if alias in self.repository_aliases:
            return None
        local_path = self.sibling_alias_roots.get(alias)
        if not local_path:
            return None
        return {
            "kind": "external_unregistered",
            "reference": reference,
            "repository_alias": parts[0],
            "local_path": local_path,
        }

    def _external_absolute_reference(self, reference: str) -> dict[str, Any] | None:
        try:
            absolute = normalize_path(str(Path(reference).resolve())).lower()
        except OSError:
            return None
        for alias, root in self.sibling_alias_roots.items():
            root_lower = root.lower().rstrip("/")
            if absolute == root_lower or absolute.startswith(root_lower + "/"):
                return {
                    "kind": "external_unregistered",
                    "reference": reference,
                    "repository_alias": alias,
                    "local_path": root,
                }
        return None

    def has_symbol(self, symbol: str) -> bool:
        normalized = _normalize_symbol(symbol)
        if not normalized:
            return False
        if normalized.lower() in self.symbol_locations:
            return True
        if "::" in normalized:
            return normalized.rsplit("::", 1)[-1].lower() in self.symbol_locations
        return False

    def symbol_paths(self, symbol: str) -> list[str]:
        normalized = _normalize_symbol(symbol)
        if not normalized:
            return []
        paths = self.symbol_locations.get(normalized.lower(), [])
        if not paths and "::" in normalized:
            paths = self.symbol_locations.get(normalized.rsplit("::", 1)[-1].lower(), [])
        return paths[:10]


CODE_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hh",
    ".hpp",
    ".cs",
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
}
REFERENCE_EXTENSIONS = CODE_EXTENSIONS | {
    ".ini",
    ".json",
    ".md",
    ".mmd",
    ".mermaid",
    ".plantuml",
    ".puml",
    ".uplugin",
    ".uproject",
    ".yaml",
    ".yml",
}
SKIP_DIRS = {
    ".git",
    ".vs",
    ".pytest_cache",
    "__pycache__",
    "Binaries",
    "DerivedDataCache",
    "Intermediate",
    "Saved",
}
IGNORED_REFERENCE_PREFIXES = (
    "binaries/",
    "deriveddatacache/",
    "intermediate/",
    "saved/",
)
COMMON_SYMBOL_WORDS = {
    "ADR",
    "API",
    "CLI",
    "CPU",
    "DB",
    "FAQ",
    "HTTP",
    "HTTPS",
    "ID",
    "JSON",
    "LLM",
    "MCP",
    "README",
    "REST",
    "SQL",
    "TODO",
    "UML",
    "URI",
    "URL",
    "UUID",
    "XML",
    "YAML",
}
PATH_RE = re.compile(
    r"(?P<path>(?:[A-Za-z]:[\\/])?(?:[A-Za-z0-9_.@+-]+[\\/])+[A-Za-z0-9_.@+-]+\.[A-Za-z0-9]+"
    r"|[A-Za-z0-9_.@+-]+\.(?:plantuml|mermaid|uplugin|uproject|yaml|json|cpp|cxx|hpp|tsx|jsx|mmd|puml|ini|yml|md|hh|cc|cs|py|js|ts|h|c))(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\((?P<target>[^)]+)\)")
CODE_SPAN_RE = re.compile(r"`(?P<code>[^`\n]{1,240})`")
SYMBOL_TOKEN_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)?\b")
DECLARATION_RES = [
    re.compile(r"\b(?:class|struct|interface)\s+(?:[A-Z][A-Z0-9_]*_API\s+)?([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"\benum\s+(?:class\s+)?([A-Za-z_][A-Za-z0-9_]*)"),
    re.compile(r"\b(?:def|async\s+def|function)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("),
    re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)::[~A-Za-z_][A-Za-z0-9_]*\s*\("),
    re.compile(r"\bIMPLEMENT_MODULE\s*\([^,]+,\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)"),
]
IMPLEMENTATION_STATUS_RE = re.compile(
    r"\b(not yet implemented|not implemented|planned|future work|todo|stub|placeholder|coming soon)\b",
    re.IGNORECASE,
)
DOMAIN_PLANNED_STATUS_RE = re.compile(
    r"\bplanned\s+(rename|renames|action|actions|operation|operations|entry|entries|change|changes)\b",
    re.IGNORECASE,
)
SUPERSEDED_DOCUMENT_RE = re.compile(
    r"\b(superseded status|do not execute this plan|historical plan references|superseded plan)\b",
    re.IGNORECASE,
)
FUTURE_TARGET_DOCUMENT_RE = re.compile(
    r"\b(target-state|future target|proposed for implementation|planned implementation|not yet implemented|future work)\b|<<future target",
    re.IGNORECASE,
)
STRONG_SYMBOL_SUFFIX_RE = re.compile(
    r"(Analyzer|Backend|Builder|Commandlet|Config|Controller|Converter|Director|Editor|Gateway|Manager|Module|Panel|Provider|Registry|Runner|Service|Settings|Store|Subsystem|Widget)$"
)


def _load_documents(conn: sqlite3.Connection, project_id: str, target: str | None) -> list[_Document]:
    documents: list[_Document] = []
    target_clause = ""
    params: list[Any] = [project_id]
    if target:
        target_clause = "AND (ki.item_uid = ? OR ki.local_id = ? OR ki.source_uri = ?)"
        params.extend([target, target, target])
    rows = conn.execute(
        f"""
        SELECT ki.item_uid, ki.item_type, ki.local_id, ki.title, ki.source_uri, ki.summary,
               a.raw_source, a.context_md, a.decision_md, a.consequences_md
        FROM knowledge_items ki
        LEFT JOIN adrs a ON a.item_uid = ki.item_uid
        WHERE ki.project_id = ?
          AND ki.item_type = 'adr'
          {target_clause}
        ORDER BY ki.local_id
        """,
        params,
    ).fetchall()
    for row in rows:
        body = "\n".join(
            part
            for part in [
                row["raw_source"],
                row["summary"],
                row["context_md"],
                row["decision_md"],
                row["consequences_md"],
            ]
            if part
        )
        documents.append(
            _Document(
                uid=row["item_uid"],
                item_type=row["item_type"],
                local_id=row["local_id"],
                title=row["title"] or row["local_id"],
                source_uri=row["source_uri"],
                body=body,
            )
        )

    target_clause = ""
    params = [project_id]
    if target:
        target_clause = "AND (d.diagram_uid = ? OR d.diagram_id = ? OR d.source_uri = ?)"
        params.extend([target, target, target])
    diagram_rows = conn.execute(
        f"""
        SELECT d.diagram_uid, d.diagram_id, d.title, d.source_uri, d.raw_source, d.diagram_kind,
               ki.item_uid
        FROM uml_diagrams d
        LEFT JOIN knowledge_items ki
          ON ki.project_id = d.project_id
         AND ki.item_type = 'uml_diagram'
         AND ki.local_id = d.diagram_id
        WHERE d.project_id = ?
          {target_clause}
        ORDER BY d.diagram_id
        """,
        params,
    ).fetchall()
    for row in diagram_rows:
        elements = [
            dict(element)
            for element in conn.execute(
                """
                SELECT element_id, element_type, name, description
                FROM uml_elements
                WHERE project_id = ?
                  AND diagram_uid = ?
                ORDER BY element_id
                """,
                (project_id, row["diagram_uid"]),
            ).fetchall()
        ]
        documents.append(
            _Document(
                uid=row["item_uid"] or row["diagram_uid"],
                item_type="uml_diagram",
                local_id=row["diagram_id"],
                title=row["title"],
                source_uri=row["source_uri"],
                body=row["raw_source"] or "",
                uml_elements=elements,
            )
        )
    return documents


def _iter_repository_files(root: Path):
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            children = list(current.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_dir():
                if child.name not in SKIP_DIRS:
                    stack.append(child)
            elif child.is_file():
                yield child


def _discover_sibling_alias_roots(roots: list[Path], registered_aliases: set[str]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for root in roots:
        parent = root.parent
        try:
            children = list(parent.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir():
                continue
            alias = child.name.lower()
            if alias in registered_aliases or alias in aliases:
                continue
            aliases[alias] = normalize_path(str(child.resolve()))
    return aliases


def _should_index_path(path: str, repository: dict[str, Any]) -> bool:
    from architectural_knowledge_db.services.git_scanner import should_store_path

    return should_store_path(path, repository.get("include_patterns", []), repository.get("exclude_patterns", []))


def _is_code_file(path: str) -> bool:
    return Path(path).suffix.lower() in CODE_EXTENSIONS


def _is_reference_file(path: str) -> bool:
    return Path(path).suffix.lower() in REFERENCE_EXTENSIONS


def _symbols_from_file(path: Path) -> set[str]:
    try:
        if path.stat().st_size > 512_000:
            return set()
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return set()
    symbols: set[str] = set()
    for declaration_re in DECLARATION_RES:
        symbols.update(match.group(1) for match in declaration_re.finditer(text))
    return {symbol for symbol in symbols if _looks_like_symbol(symbol)}


def _file_reference_findings(document: _Document, snapshot: _RepositorySnapshot) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    document_intent = _document_intent(document)
    for reference in _extract_path_references(document.body):
        resolved = snapshot.resolve_path_reference(reference, document)
        if resolved["kind"] in {"ignored", "exact"}:
            continue
        if resolved["kind"] == "moved":
            findings.append(
                _finding(
                    document,
                    status="review_recommended",
                    check_type="path_reference_moved_or_ambiguous",
                    reference=resolved["reference"],
                    reason=f"{document.local_id} references {resolved['reference']}, but only basename matches exist in the current repository snapshot.",
                    evidence={"candidate_paths": resolved["candidates"]},
                )
            )
        elif resolved["kind"] == "external_unregistered":
            findings.append(
                _finding(
                    document,
                    status="review_recommended",
                    check_type="external_repository_not_registered",
                    reference=resolved["reference"],
                    reason=(
                        f"{document.local_id} references {resolved['reference']} in sibling workspace "
                        f"{resolved['repository_alias']}, but that repository is not registered in the current drift snapshot."
                    ),
                    evidence={
                        "repository_alias": resolved["repository_alias"],
                        "local_path": resolved["local_path"],
                        "document_intent": document_intent,
                    },
                )
            )
        elif resolved["kind"] == "missing":
            status, check_type, reason, evidence = _missing_path_details(document, resolved["reference"], document_intent)
            findings.append(
                _finding(
                    document,
                    status=status,
                    check_type=check_type,
                    reference=resolved["reference"],
                    reason=reason,
                    evidence=evidence,
                )
            )
    return findings


def _symbol_reference_findings(document: _Document, snapshot: _RepositorySnapshot) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    document_intent = _document_intent(document)
    for symbol in _extract_symbol_references(document):
        if snapshot.has_symbol(symbol):
            continue
        severity, check_type, reason, evidence = _missing_symbol_details(document, symbol, document_intent)
        findings.append(
            _finding(
                document,
                status=severity,
                check_type=check_type,
                reference=symbol,
                reason=reason,
                evidence=evidence,
            )
        )
    return findings


def _implementation_status_findings(document: _Document, snapshot: _RepositorySnapshot) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for sentence in _sentences(document.body):
        if not IMPLEMENTATION_STATUS_RE.search(sentence):
            continue
        if DOMAIN_PLANNED_STATUS_RE.search(sentence):
            continue
        present_symbols = [
            symbol
            for symbol in _extract_symbols_from_text(sentence, require_strong_shape=True)
            if snapshot.has_symbol(symbol)
        ]
        for symbol in present_symbols[:5]:
            findings.append(
                _finding(
                    document,
                    status="review_recommended",
                    check_type="implemented_symbol_described_as_future_or_stub",
                    reference=symbol,
                    reason=f"{document.local_id} describes {symbol} as future, stub, or not implemented, but the symbol exists in the current code snapshot.",
                    evidence={"current_symbol_paths": snapshot.symbol_paths(symbol), "sentence": sentence.strip()[:400]},
                )
            )
    return findings


def _finding(
    document: _Document,
    status: str,
    check_type: str,
    reference: str,
    reason: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "status": status,
        "check_type": check_type,
        "reference": reference,
        "reason": reason,
        "document": document.as_evidence(),
        "evidence": {"mode": "status_quo", **(evidence or {})},
    }
    return payload


def _extract_path_references(text: str) -> list[str]:
    references: list[str] = []
    for match in MARKDOWN_LINK_RE.finditer(text):
        references.append(match.group("target"))
    for match in CODE_SPAN_RE.finditer(text):
        code = match.group("code")
        references.extend(
            path_match.group("path")
            for path_match in PATH_RE.finditer(code)
            if not _match_is_embedded_in_url(code, path_match.start(), path_match.end())
        )
    for match in PATH_RE.finditer(text):
        if _match_is_embedded_in_url(text, match.start(), match.end()):
            continue
        reference = match.group("path")
        if "/" in reference or "\\" in reference:
            references.append(reference)
    deduped: list[str] = []
    seen: set[str] = set()
    for reference in references:
        cleaned = _clean_path_reference(reference)
        if not cleaned or _should_ignore_reference(cleaned) or not _is_reference_file(cleaned):
            continue
        key = cleaned.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(cleaned)
    return deduped[:80]


def _match_is_embedded_in_url(text: str, start: int, end: int) -> bool:
    token_start = max(
        text.rfind(" ", 0, start),
        text.rfind("\n", 0, start),
        text.rfind("\t", 0, start),
        text.rfind("(", 0, start),
        text.rfind("[", 0, start),
    ) + 1
    token_end_candidates = [
        position
        for position in [
            text.find(" ", end),
            text.find("\n", end),
            text.find("\t", end),
            text.find(")", end),
            text.find("]", end),
        ]
        if position != -1
    ]
    token_end = min(token_end_candidates) if token_end_candidates else len(text)
    token = text[token_start:token_end]
    return "://" in token


def _clean_path_reference(reference: str | None) -> str | None:
    if not reference:
        return None
    value = reference.strip().strip("<>\"'")
    if not value or "://" in value or value.startswith(("mailto:", "#")):
        return None
    value = value.split("#", 1)[0].split("?", 1)[0]
    value = value.rstrip(".,;:)")
    value = normalize_path(value)
    if value.startswith(".") and not value.startswith(("./", "../")):
        return None
    if not re.match(r"^[A-Za-z]:/", value):
        value = normalize_path(posixpath.normpath(value))
        if value == ".":
            return None
    return value or None


def _should_ignore_reference(reference: str) -> bool:
    lower = reference.lower().lstrip("/")
    return lower.startswith(IGNORED_REFERENCE_PREFIXES)


def _document_intent(document: _Document) -> str:
    haystack = "\n".join(
        part
        for part in [document.local_id, document.title, document.source_uri or "", document.body[:4000]]
        if part
    )
    if SUPERSEDED_DOCUMENT_RE.search(haystack):
        return "superseded_historical_plan"
    if FUTURE_TARGET_DOCUMENT_RE.search(haystack):
        return "future_target"
    return "current"


def _missing_path_details(document: _Document, reference: str, document_intent: str) -> tuple[str, str, str, dict[str, Any]]:
    if document_intent == "superseded_historical_plan":
        return (
            "review_recommended",
            "superseded_plan_path_reference",
            f"{document.local_id} references historical path {reference} inside a superseded plan; do not treat it as current implementation evidence.",
            {"document_intent": document_intent},
        )
    if document_intent == "future_target":
        return (
            "review_recommended",
            "future_target_path_reference",
            f"{document.local_id} references future or target-state path {reference}, which is not present in the current repository snapshot.",
            {"document_intent": document_intent},
        )
    return (
        "likely_stale",
        "missing_path_reference",
        f"{document.local_id} references {reference}, which does not exist in the current repository snapshot.",
        {"document_intent": document_intent},
    )


def _missing_symbol_details(document: _Document, symbol: str, document_intent: str) -> tuple[str, str, str, dict[str, Any]]:
    if document_intent == "superseded_historical_plan":
        return (
            "review_recommended",
            "superseded_plan_symbol_reference",
            f"{document.local_id} references historical symbol {symbol} inside a superseded plan; do not treat it as current implementation evidence.",
            {"document_intent": document_intent},
        )
    if document_intent == "future_target":
        return (
            "review_recommended",
            "future_target_symbol_reference",
            f"{document.local_id} references future or target-state symbol {symbol}, which was not found in the current code snapshot.",
            {"document_intent": document_intent},
        )
    severity = "likely_stale" if document.item_type == "uml_diagram" else "review_recommended"
    return (
        severity,
        "missing_symbol_reference",
        f"{document.local_id} references symbol {symbol}, which was not found in the current code snapshot.",
        {"document_intent": document_intent},
    )


def _component_key(path: str | None) -> str:
    if not path:
        return ""
    parts = normalize_path(path).split("/")
    if len(parts) >= 2 and parts[0] in {
        "AIPlugins",
        "BridgePlugins",
        "EnginePlugins",
        "GovernanceDevelopmentPlugins",
        "ScenePlugins",
    }:
        return parts[1].lower()
    if len(parts) >= 2 and parts[0] == "Plugins":
        return parts[1].lower()
    if len(parts) >= 4 and parts[0] == "docs" and parts[1] == "ADR" and parts[2] == "Plugins":
        return parts[3].lower()
    if len(parts) >= 3 and parts[0] == "UML" and parts[1] == "Plugins":
        return parts[2].lower()
    return ""


def _extract_symbol_references(document: _Document) -> list[str]:
    symbols: set[str] = set()
    for match in CODE_SPAN_RE.finditer(document.body):
        code = match.group("code")
        if "/" in code or "\\" in code:
            continue
        symbols.update(_extract_symbols_from_text(code, require_strong_shape=True))
    for element in document.uml_elements:
        name = element.get("name") or ""
        element_type = (element.get("element_type") or "").lower()
        if element_type in {"class", "abstract_class", "interface", "enum", "component"} and _looks_like_symbol(name):
            symbols.add(name)
    return sorted(symbols)[:120]


def _extract_symbols_from_text(text: str, require_strong_shape: bool) -> set[str]:
    symbols: set[str] = set()
    for match in SYMBOL_TOKEN_RE.finditer(text):
        symbol = _normalize_symbol(match.group(0))
        if not symbol or not _looks_like_symbol(symbol):
            continue
        if require_strong_shape and not _has_strong_symbol_shape(symbol):
            continue
        symbols.add(symbol)
    return symbols


def _normalize_symbol(symbol: str) -> str | None:
    value = symbol.strip().strip("`\"'.,;:()[]{}<>")
    if not value or value.upper() in COMMON_SYMBOL_WORDS:
        return None
    return value


def _looks_like_symbol(symbol: str) -> bool:
    if not symbol or len(symbol) < 4 or re.search(r"\s", symbol):
        return False
    if symbol.upper() in COMMON_SYMBOL_WORDS:
        return False
    return bool(re.search(r"[A-Z_]", symbol))


def _has_strong_symbol_shape(symbol: str) -> bool:
    leaf = symbol.rsplit("::", 1)[-1]
    return bool(STRONG_SYMBOL_SUFFIX_RE.search(leaf) or re.match(r"^[AFIUS][A-Z][A-Za-z0-9_]{2,}$", leaf))


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


def _dedupe_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for finding in findings:
        key = (
            finding["document"]["uid"],
            finding["check_type"],
            finding["reference"].lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(finding)
    return deduped


def _finding_sort_key(finding: dict[str, Any]) -> tuple[int, str, str, str]:
    status_rank = {"likely_stale": 0, "review_recommended": 1, "watch": 2, "unknown": 3, "current": 4}
    return (
        status_rank.get(finding["status"], 9),
        finding["document"]["item_type"],
        finding["document"]["local_id"],
        finding["reference"],
    )


def _summarize_findings(findings: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "by_status": Counter(finding["status"] for finding in findings).most_common(),
        "by_check_type": Counter(finding["check_type"] for finding in findings).most_common(),
        "by_item_type": Counter(finding["document"]["item_type"] for finding in findings).most_common(),
    }


def _top_areas(findings: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    counts = Counter(_document_area(finding["document"]) for finding in findings)
    return [{"area": area, "count": count} for area, count in counts.most_common(limit)]


def _top_documents(findings: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for finding in findings:
        document = finding["document"]
        entry = grouped.setdefault(
            document["uid"],
            {
                "document": document,
                "count": 0,
                "by_check_type": Counter(),
                "by_status": Counter(),
            },
        )
        entry["count"] += 1
        entry["by_check_type"][finding["check_type"]] += 1
        entry["by_status"][finding["status"]] += 1
    top = sorted(grouped.values(), key=lambda item: item["count"], reverse=True)[:limit]
    return [
        {
            "document": item["document"],
            "count": item["count"],
            "by_check_type": item["by_check_type"].most_common(),
            "by_status": item["by_status"].most_common(),
        }
        for item in top
    ]


def _document_area(document: dict[str, Any]) -> str:
    source_uri = normalize_path(document.get("source_uri") or "")
    marker = "D:/TinyToolDevelopment/Git/"
    if source_uri.startswith(marker):
        source_uri = source_uri[len(marker) :]
    parts = source_uri.split("/")
    if len(parts) >= 2 and parts[0] in {
        "AIPlugins",
        "BridgePlugins",
        "EnginePlugins",
        "GovernanceDevelopmentPlugins",
        "ScenePlugins",
    }:
        return "/".join(parts[:2])
    if len(parts) >= 4 and parts[0] == "docs" and parts[1] == "ADR" and parts[2] == "Plugins":
        return "docs/ADR/Plugins/" + parts[3]
    if len(parts) >= 3 and parts[0] == "UML" and parts[1] == "Plugins":
        return "UML/Plugins/" + parts[2]
    return "/".join(parts[:2]) if len(parts) >= 2 else (parts[0] or "unknown")


def _git_timeline_summary(report_counts: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: Counter[str] = Counter()
    type_counts: Counter[str] = Counter()
    for row in report_counts:
        if row["target_type"] == "status_quo_drift":
            continue
        status_counts[row["status"]] += row["count"]
        type_counts[row["target_type"]] += row["count"]
    return {
        "by_status": status_counts.most_common(),
        "by_target_type": type_counts.most_common(),
    }
