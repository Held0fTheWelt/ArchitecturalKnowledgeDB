from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from architectural_knowledge_db.services.git_scanner import GitScanner
from architectural_knowledge_db.services.import_export import ImportExportService
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.services.uml import UMLService


class ReingestService:
    """Rebuild a project's knowledge from its on-disk sources.

    Re-imports ADRs, architecture documents, and UML, then rescans Git
    provenance, reusing the existing import/scan services. Folders default to the
    standard repository layout under ``source_root`` (``AKDB_SOURCE_ROOT`` when
    not given); missing folders are skipped rather than failing the run.

    Note: writes to the configured database. When the native :8787 service holds
    the live DB open on a shared (v9fs) mount, run this against a database the
    agent owns (or with the service stopped) — a single writer at a time.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.projects = ProjectService(conn)

    def reingest_project(
        self,
        project_id: str,
        source_root: str | Path | None = None,
        adr_folder: str | Path | None = None,
        document_folder: str | Path | None = None,
        uml_folder: str | Path | None = None,
        scan_git: bool = True,
        max_commits: int = 400,
    ) -> dict[str, Any]:
        self.projects.require_project(project_id)
        root = Path(source_root or os.environ.get("AKDB_SOURCE_ROOT") or ".").expanduser()
        git_root = root / "Git" if (root / "Git").is_dir() else root
        adr = Path(adr_folder) if adr_folder else git_root / "docs" / "ADR"
        docs = Path(document_folder) if document_folder else git_root / "docs" / "architecture"
        uml = Path(uml_folder) if uml_folder else git_root / "UML"

        importer = ImportExportService(self.conn)
        stages: dict[str, Any] = {}

        if adr.is_dir():
            res = importer.import_adrs(project_id, adr)
            stages["adrs"] = {
                "folder": str(adr),
                "imported": res["imported"],
                "skipped": len(res.get("skipped", [])),
            }
        else:
            stages["adrs"] = {"folder": str(adr), "skipped_missing": True}

        if docs.is_dir():
            res = importer.import_documents(project_id, docs)
            stages["documents"] = {
                "folder": str(docs),
                "imported": res["imported"],
                "derived": res.get("derived", 0),
            }
        else:
            stages["documents"] = {"folder": str(docs), "skipped_missing": True}

        if uml.is_dir():
            res = UMLService(self.conn).import_diagrams(project_id, uml)
            stages["uml"] = {"folder": str(uml), "imported": res.get("imported", 0)}
        else:
            stages["uml"] = {"folder": str(uml), "skipped_missing": True}

        if scan_git:
            try:
                stages["git"] = GitScanner(self.conn).scan_project(project_id, max_commits=max_commits)
            except Exception as exc:  # best-effort: document re-import still succeeds
                stages["git"] = {"status": "skipped", "error": str(exc)}
        else:
            stages["git"] = {"status": "disabled"}

        self.conn.commit()
        return {
            "project_id": project_id,
            "source_root": str(root),
            "git_root": str(git_root),
            "stages": stages,
        }
