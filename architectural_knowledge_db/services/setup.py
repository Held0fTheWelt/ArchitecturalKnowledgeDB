from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path
from typing import Any

from architectural_knowledge_db.models import ProjectUpsert
from architectural_knowledge_db.services.import_export import ImportExportService
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.services.uml import UMLService


class StarterSetupService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.projects = ProjectService(conn)
        self.import_export = ImportExportService(conn)
        self.uml = UMLService(conn)

    def setup_project(
        self,
        project_id: str,
        project_name: str | None = None,
        target_dir: str | Path = "docs/architecture",
        template_name: str = "starter",
        overwrite: bool = False,
        import_content: bool = True,
    ) -> dict[str, Any]:
        display_name = project_name or project_id
        project = self.projects.upsert_project(
            ProjectUpsert(
                project_id=project_id,
                display_name=display_name,
                description="Project initialized from the ArchitecturalKnowledgeDB starter templates.",
            )
        )
        target = Path(target_dir)
        written = self.write_templates(
            target,
            template_name=template_name,
            variables={"project_id": project_id, "project_name": display_name},
            overwrite=overwrite,
        )
        result: dict[str, Any] = {
            "project": project,
            "target_dir": str(target),
            "template": template_name,
            "created_files": written["created_files"],
            "skipped_files": written["skipped_files"],
            "imports": {},
        }
        if import_content:
            adr_dir = target / "adr"
            uml_dir = target / "uml"
            result["imports"]["adrs"] = self.import_export.import_adrs(project_id, adr_dir)
            result["imports"]["uml"] = self.uml.import_diagrams(project_id, uml_dir)
        return result

    def write_templates(
        self,
        target_dir: str | Path,
        template_name: str = "starter",
        variables: dict[str, str] | None = None,
        overwrite: bool = False,
    ) -> dict[str, list[str]]:
        target = Path(target_dir)
        variables = variables or {}
        template_root = resources.files("architectural_knowledge_db").joinpath("templates", template_name)
        if not template_root.is_dir():
            raise ValueError(f"Unknown setup template: {template_name}")

        created: list[str] = []
        skipped: list[str] = []
        for relative_path, resource in sorted(_iter_files(template_root), key=lambda item: str(item[0])):
            destination = target / relative_path
            if destination.exists() and not overwrite:
                skipped.append(str(destination))
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            text = resource.read_text(encoding="utf-8")
            destination.write_text(_render_template(text, variables), encoding="utf-8", newline="\n")
            created.append(str(destination))
        return {"created_files": created, "skipped_files": skipped}


def _iter_files(
    root: resources.abc.Traversable,
    prefix: Path | None = None,
) -> list[tuple[Path, resources.abc.Traversable]]:
    prefix = prefix or Path()
    files: list[tuple[Path, resources.abc.Traversable]] = []
    for child in root.iterdir():
        child_path = prefix / child.name
        if child.is_dir():
            files.extend(_iter_files(child, child_path))
        elif child.is_file():
            files.append((child_path, child))
    return files


def _render_template(text: str, variables: dict[str, str]) -> str:
    rendered = text
    for key, value in variables.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered
