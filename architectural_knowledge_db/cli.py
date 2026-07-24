from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import typer
import uvicorn

from architectural_knowledge_db.config import Settings, load_project_registry, self_export_target
from architectural_knowledge_db.db.connection import initialize_database
from architectural_knowledge_db.mcp import MCP_MANIFEST
from architectural_knowledge_db.models import (
    AdrInput,
    CanonicalDocumentCreate,
    CanonicalDocumentUpdate,
    ContextPackRequest,
    DefinitionInput,
    KnowledgeSpace,
    OriginExplainRequest,
    ProjectUpsert,
    RepositoryRegistration,
    RuleInput,
    SadDecisionInput,
    SadDocumentInput,
    SadSectionInput,
    SourceAreaInput,
    SpecInput,
    UMLDiagramInput,
    UMLDiagramUpdate,
    UMLElementInput,
    UMLElementUpdate,
    UMLRelationshipInput,
    UMLRelationshipUpdate,
)
from architectural_knowledge_db.services.authoring import AuthoringService
from architectural_knowledge_db.services.change_sets import ChangeSetService
from architectural_knowledge_db.services.consistency import ConsistencyService
from architectural_knowledge_db.services.context import ContextPackBuilder
from architectural_knowledge_db.services.git_scanner import GitScanner
from architectural_knowledge_db.services.import_export import ImportExportService, repo_relative_key
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.origin import OriginService
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.services.repositories import RepositoryService
from architectural_knowledge_db.services.sad import SadService
from architectural_knowledge_db.services.search import SearchService
from architectural_knowledge_db.services.setup import StarterSetupService
from architectural_knowledge_db.services.staleness import StalenessService
from architectural_knowledge_db.services.uml import UMLService
from architectural_knowledge_db.services.workspace import WorkspaceService


app = typer.Typer(help="ArchitecturalKnowledgeDB local service CLI.")
project_app = typer.Typer(help="Manage projects and shared spaces.")
repo_app = typer.Typer(help="Manage source repositories.")
adr_app = typer.Typer(help="Import, export, and inspect ADRs.")
sad_app = typer.Typer(help="Author and export arc42 Software Architecture Documents.")
rule_app = typer.Typer(help="Manage architecture rules.")
definition_app = typer.Typer(help="Manage definitions.")
source_area_app = typer.Typer(help="Manage source areas.")
document_app = typer.Typer(help="Import project documents and notes.")
git_app = typer.Typer(help="Scan read-only Git metadata.")
origin_app = typer.Typer(help="Explain source or knowledge origins.")
stale_app = typer.Typer(help="Manage staleness reports.")
mcp_app = typer.Typer(help="MCP manifest and dispatch helpers.")
uml_app = typer.Typer(help="Import, export, and edit UML diagrams.")
consistency_app = typer.Typer(help="Run consistency checks and inspect links.")
workspace_app = typer.Typer(help="Multi-repo workspace inventory + cross-reference resolution.")
spec_app = typer.Typer(help="Author, ingest, and promote specs and their Architektur-Impact deltas.")
work_app = typer.Typer(help="Inspect the cross-spec change-set backlog.")
change_app = typer.Typer(help="Manage individual change_items.")

app.add_typer(project_app, name="project")
app.add_typer(repo_app, name="repo")
app.add_typer(adr_app, name="adr")
app.add_typer(sad_app, name="sad")
app.add_typer(rule_app, name="rule")
app.add_typer(definition_app, name="definition")
app.add_typer(source_area_app, name="source-area")
app.add_typer(document_app, name="document")
app.add_typer(git_app, name="git")
app.add_typer(origin_app, name="origin")
app.add_typer(stale_app, name="stale")
app.add_typer(mcp_app, name="mcp")
app.add_typer(uml_app, name="uml")
app.add_typer(consistency_app, name="consistency")
app.add_typer(workspace_app, name="workspace")
app.add_typer(spec_app, name="spec")
app.add_typer(work_app, name="work")
app.add_typer(change_app, name="change")
obsidian_app = typer.Typer(help="Obsidian-vault layout sync and verify (derived render).")
app.add_typer(obsidian_app, name="obsidian")


@app.callback()
def callback(
    db: Path | None = typer.Option(None, "--db", help="SQLite database path."),
) -> None:
    if db is not None:
        os.environ["AKDB_DATABASE_PATH"] = str(db)


@app.command("init")
def init_db() -> None:
    with _conn() as conn:
        migrations = conn.execute("SELECT version, applied_at FROM schema_migrations ORDER BY version").fetchall()
        _print({"database": str(Settings.from_env().database_path), "migrations": [dict(row) for row in migrations]})


@app.command("setup")
def setup_starter(
    project_id: str = typer.Option(..., "--project", help="Project id to create or update."),
    name: str | None = typer.Option(None, "--name", help="Display name. Defaults to --project."),
    target: Path = typer.Option(Path("docs/architecture"), "--target", help="Folder for starter ADR/UML/spec files."),
    template: str = typer.Option("starter", "--template", help="Template set name."),
    overwrite: bool = typer.Option(False, "--overwrite/--no-overwrite", help="Overwrite existing template files."),
    import_content: bool = typer.Option(
        True,
        "--import/--no-import",
        help="Import generated ADR and UML files into the knowledge database.",
    ),
) -> None:
    with _conn() as conn:
        _print(
            StarterSetupService(conn).setup_project(
                project_id=project_id,
                project_name=name,
                target_dir=target,
                template_name=template,
                overwrite=overwrite,
                import_content=import_content,
            )
        )


@app.command()
def serve(
    host: str | None = typer.Option(None, "--host", help="Host to bind."),
    port: int | None = typer.Option(None, "--port", help="Port to bind."),
) -> None:
    settings = Settings.from_env()
    uvicorn.run(
        "architectural_knowledge_db.api.app:create_app",
        factory=True,
        host=host or settings.host,
        port=port or settings.port,
    )


@project_app.command("add")
def add_project(
    project_id: str = typer.Option(..., "--id", help="Stable project id."),
    name: str = typer.Option(..., "--name", help="Display name."),
    description: str | None = typer.Option(None, "--description"),
    imports: list[str] = typer.Option([], "--import", help="Shared space id to import."),
) -> None:
    with _conn() as conn:
        result = ProjectService(conn).upsert_project(
            ProjectUpsert(project_id=project_id, display_name=name, description=description, imports=imports)
        )
        _print(result)


@project_app.command("list")
def list_projects() -> None:
    with _conn() as conn:
        _print(ProjectService(conn).list_projects())


@project_app.command("space-add")
def add_space(
    space_id: str = typer.Option(..., "--id"),
    display_name: str = typer.Option(..., "--name"),
    space_type: str = typer.Option("shared", "--type"),
    project_id: str | None = typer.Option(None, "--project"),
    description: str | None = typer.Option(None, "--description"),
) -> None:
    with _conn() as conn:
        result = ProjectService(conn).upsert_space(
            KnowledgeSpace(
                space_id=space_id,
                project_id=project_id,
                space_type=space_type,  # type: ignore[arg-type]
                display_name=display_name,
                description=description,
            )
        )
        _print(result)


@project_app.command("import-registry")
def import_registry(path: Path = typer.Argument(..., help="JSON/YAML project registry.")) -> None:
    registry = load_project_registry(path)
    with _conn() as conn:
        projects = ProjectService(conn)
        repos = RepositoryService(conn)
        for shared in registry.get("shared_spaces", []):
            projects.ensure_shared_space(shared["id"], shared.get("display_name") or shared["id"])
        imported_projects = []
        imported_repositories = []
        for project in registry.get("projects", []):
            result = projects.upsert_project(
                ProjectUpsert(
                    project_id=project["id"],
                    display_name=project.get("display_name") or project["id"],
                    description=project.get("description"),
                    imports=project.get("imports", []),
                )
            )
            imported_projects.append(result)
            for repo in project.get("repositories", []):
                imported_repositories.append(
                    repos.register_repository(
                        project["id"],
                        RepositoryRegistration(
                            repository_id=repo["id"],
                            local_path=repo["local_path"],
                            default_branch=repo.get("default_branch"),
                            scan_policy=repo.get("scan_policy", "manual"),
                            include_patterns=repo.get("include_patterns", []),
                            exclude_patterns=repo.get("exclude_patterns", []),
                        ),
                    )
                )
        _print(
            {
                "projects": imported_projects,
                "repositories": imported_repositories,
                "shared_spaces": registry.get("shared_spaces", []),
            }
        )


@repo_app.command("add")
def add_repository(
    project_id: str = typer.Option(..., "--project"),
    repository_id: str = typer.Option(..., "--id"),
    path: Path = typer.Option(..., "--path"),
    remote: str | None = typer.Option(None, "--remote"),
    default_branch: str | None = typer.Option(None, "--default-branch"),
    include: list[str] = typer.Option([], "--include"),
    exclude: list[str] = typer.Option([], "--exclude"),
) -> None:
    with _conn() as conn:
        result = RepositoryService(conn).register_repository(
            project_id,
            RepositoryRegistration(
                repository_id=repository_id,
                local_path=str(path),
                remote_url_sanitized=remote,
                default_branch=default_branch,
                include_patterns=include,
                exclude_patterns=exclude,
            ),
        )
        _print(result)


@repo_app.command("list")
def list_repositories(project_id: str = typer.Option(..., "--project")) -> None:
    with _conn() as conn:
        _print(RepositoryService(conn).list_repositories(project_id))


@adr_app.command("add")
def add_adr(
    project_id: str = typer.Option(..., "--project"),
    adr_id: str = typer.Option(..., "--id"),
    title: str = typer.Option(..., "--title"),
    status: str = typer.Option("accepted", "--status"),
    context: str | None = typer.Option(None, "--context"),
    decision: str | None = typer.Option(None, "--decision"),
    consequences: str | None = typer.Option(None, "--consequences"),
) -> None:
    with _conn() as conn:
        result = KnowledgeService(conn).upsert_adr(
            project_id,
            AdrInput(
                adr_id=adr_id,
                title=title,
                status=status,
                context_md=context,
                decision_md=decision,
                consequences_md=consequences,
            ),
        )
        _print(result)


@adr_app.command("import")
def import_adrs(
    project_id: str = typer.Option(..., "--project"),
    folder: Path = typer.Option(..., "--folder"),
) -> None:
    with _conn() as conn:
        _print(ImportExportService(conn).import_adrs(project_id, folder))


@adr_app.command("export")
def export_adrs(
    project_id: str = typer.Option(..., "--project"),
    folder: Path = typer.Option(..., "--folder"),
) -> None:
    with _conn() as conn:
        _print(ImportExportService(conn).export_adrs(project_id, folder))


@sad_app.command("export")
def export_sad(
    project_id: str = typer.Option(..., "--project"),
    folder: Path | None = typer.Option(
        None,
        "--folder",
        help="Export folder. Defaults to the workspace self-export target when known.",
    ),
    document_local_id: str | None = typer.Option(None, "--document"),
) -> None:
    target = folder
    if target is None:
        target = self_export_target(project_id)
        if target is None:
            raise typer.BadParameter(
                "No --folder given and no self-export default for this project/workspace.",
                param_hint="--folder",
            )
    with _conn() as conn:
        _print(ImportExportService(conn).export_sad(project_id, target, document_local_id))


@sad_app.command("list")
def list_sads(project_id: str = typer.Option(..., "--project")) -> None:
    with _conn() as conn:
        _print(SadService(conn).list_documents(project_id))


@sad_app.command("get")
def get_sad(
    project_id: str = typer.Option(..., "--project"),
    document_id: str = typer.Option(..., "--document"),
) -> None:
    with _conn() as conn:
        _print(SadService(conn).get_document(project_id, document_id))


@sad_app.command("upsert")
def upsert_sad(
    project_id: str = typer.Option(..., "--project"),
    document_id: str = typer.Option(..., "--document"),
    title: str = typer.Option(..., "--title"),
    source_key: str = typer.Option("architecture.md", "--source-key"),
    preamble_md: str | None = typer.Option(None, "--preamble"),
    frontmatter_json: str | None = typer.Option(
        None, "--frontmatter-json", help="JSON object stored as SAD frontmatter."
    ),
    status: str = typer.Option("current", "--status"),
    summary: str | None = typer.Option(None, "--summary"),
) -> None:
    try:
        frontmatter = json.loads(frontmatter_json) if frontmatter_json else {}
    except json.JSONDecodeError as exc:
        raise typer.BadParameter(f"--frontmatter-json is invalid JSON: {exc.msg}") from exc
    if not isinstance(frontmatter, dict):
        raise typer.BadParameter("--frontmatter-json must contain a JSON object.")
    with _conn() as conn:
        _print(
            SadService(conn).upsert_document(
                project_id,
                SadDocumentInput(
                    document_id=document_id,
                    title=title,
                    source_key=source_key,
                    preamble_md=preamble_md,
                    frontmatter=frontmatter,
                    status=status,
                    summary=summary,
                ),
            )
        )


@sad_app.command("section-set")
def set_sad_section(
    project_id: str = typer.Option(..., "--project"),
    document_id: str = typer.Option(..., "--document"),
    section_id: str = typer.Option(..., "--id"),
    title: str = typer.Option(..., "--title"),
    order: int = typer.Option(..., "--order"),
    body_md: str = typer.Option("", "--body"),
    role: str | None = typer.Option(None, "--role"),
) -> None:
    with _conn() as conn:
        _print(
            SadService(conn).upsert_section(
                project_id,
                SadSectionInput(
                    document_id=document_id,
                    section_id=section_id,
                    title=title,
                    order=order,
                    body_md=body_md,
                    role=role,
                ),
            )
        )


@sad_app.command("section-delete")
def delete_sad_section(
    project_id: str = typer.Option(..., "--project"),
    document_id: str = typer.Option(..., "--document"),
    section_id: str = typer.Option(..., "--id"),
) -> None:
    with _conn() as conn:
        _print(SadService(conn).delete_section(project_id, document_id, section_id))


@sad_app.command("decision-set")
def set_sad_decision(
    project_id: str = typer.Option(..., "--project"),
    document_id: str = typer.Option(..., "--document"),
    decision_id: str = typer.Option(..., "--id"),
    title: str = typer.Option(..., "--title"),
    order: int = typer.Option(..., "--order"),
    status: str = typer.Option("proposed", "--status"),
    body_md: str = typer.Option("", "--body"),
) -> None:
    with _conn() as conn:
        _print(
            SadService(conn).upsert_decision(
                project_id,
                SadDecisionInput(
                    document_id=document_id,
                    decision_id=decision_id,
                    title=title,
                    order=order,
                    status=status,
                    body_md=body_md,
                ),
            )
        )


@sad_app.command("decision-delete")
def delete_sad_decision(
    project_id: str = typer.Option(..., "--project"),
    document_id: str = typer.Option(..., "--document"),
    decision_id: str = typer.Option(..., "--id"),
) -> None:
    with _conn() as conn:
        _print(SadService(conn).delete_decision(project_id, document_id, decision_id))


@sad_app.command("delete")
def delete_sad(
    project_id: str = typer.Option(..., "--project"),
    document_id: str = typer.Option(..., "--document"),
) -> None:
    with _conn() as conn:
        _print(SadService(conn).delete_document(project_id, document_id))


@adr_app.command("list")
def list_adrs(
    project_id: str = typer.Option(..., "--project"),
    status: str | None = typer.Option(None, "--status"),
) -> None:
    with _conn() as conn:
        _print(KnowledgeService(conn).list_adrs(project_id, status=status))


@adr_app.command("get")
def get_adr(
    project_id: str = typer.Option(..., "--project"),
    adr_id: str = typer.Option(..., "--adr"),
) -> None:
    with _conn() as conn:
        _print(KnowledgeService(conn).get_adr(project_id, adr_id))


@rule_app.command("add")
def add_rule(
    project_id: str = typer.Option(..., "--project"),
    rule_id: str = typer.Option(..., "--id"),
    text: str = typer.Option(..., "--text"),
    severity: str = typer.Option("normal", "--severity"),
    applies_to: list[str] = typer.Option([], "--applies-to"),
    forbidden_change: list[str] = typer.Option([], "--forbidden-change"),
) -> None:
    with _conn() as conn:
        _print(
            KnowledgeService(conn).upsert_rule(
                project_id,
                RuleInput(
                    rule_id=rule_id,
                    rule_text=text,
                    severity=severity,
                    applies_to=applies_to,
                    forbidden_changes=forbidden_change,
                ),
            )
        )


@rule_app.command("import")
def import_rules(
    project_id: str = typer.Option(..., "--project"),
    path: Path = typer.Option(..., "--file"),
) -> None:
    with _conn() as conn:
        _print(ImportExportService(conn).import_rules(project_id, path))


@definition_app.command("add")
def add_definition(
    project_id: str = typer.Option(..., "--project"),
    term: str = typer.Option(..., "--term"),
    meaning: str = typer.Option(..., "--meaning"),
) -> None:
    with _conn() as conn:
        _print(KnowledgeService(conn).upsert_definition(project_id, DefinitionInput(term=term, canonical_meaning=meaning)))


@definition_app.command("import")
def import_definitions(
    project_id: str = typer.Option(..., "--project"),
    path: Path = typer.Option(..., "--file"),
) -> None:
    with _conn() as conn:
        _print(ImportExportService(conn).import_definitions(project_id, path))


@source_area_app.command("add")
def add_source_area(
    project_id: str = typer.Option(..., "--project"),
    source_area_id: str = typer.Option(..., "--id"),
    title: str = typer.Option(..., "--title"),
    pattern: list[str] = typer.Option([], "--pattern"),
    description: str | None = typer.Option(None, "--description"),
    repository_id: str | None = typer.Option(None, "--repository"),
) -> None:
    with _conn() as conn:
        _print(
            KnowledgeService(conn).upsert_source_area(
                project_id,
                SourceAreaInput(
                    source_area_id=source_area_id,
                    title=title,
                    path_patterns=pattern,
                    description=description,
                    repository_id=repository_id,
                ),
            )
        )


@source_area_app.command("import")
def import_source_areas(
    project_id: str = typer.Option(..., "--project"),
    path: Path = typer.Option(..., "--file"),
) -> None:
    with _conn() as conn:
        _print(ImportExportService(conn).import_source_areas(project_id, path))


@document_app.command("import")
def import_documents(
    project_id: str = typer.Option(..., "--project"),
    folder: Path = typer.Option(..., "--folder"),
    include: list[str] = typer.Option([], "--include", help="Glob to include. Defaults to *.md."),
    exclude: list[str] = typer.Option([], "--exclude", help="Glob to exclude, for example adr/**."),
) -> None:
    with _conn() as conn:
        _print(ImportExportService(conn).import_documents(project_id, folder, include or None, exclude or None))


@document_app.command("update-canonical")
def update_canonical_document(
    project_id: str = typer.Option(..., "--project"),
    repository_id: str = typer.Option(..., "--repository"),
    source_key: str = typer.Option(..., "--source-key"),
    body_file: Path | None = typer.Option(None, "--body-file"),
    body: str | None = typer.Option(None, "--body"),
    body_origin: str = typer.Option(
        ...,
        "--body-origin",
        help="Must be 'canonical'; generated mirror projections are not authoring input.",
    ),
    encoding: str = typer.Option("utf-8", "--encoding"),
) -> None:
    if (body_file is None) == (body is None):
        raise typer.BadParameter("Provide exactly one of --body-file or --body.")
    if body_file is not None:
        with body_file.open("r", encoding=encoding, newline="") as handle:
            body_text = handle.read()
    else:
        body_text = body or ""
    with _conn() as conn:
        _print(
            ImportExportService(conn).update_canonical_document(
                project_id,
                CanonicalDocumentUpdate(
                    repository_id=repository_id,
                    repo_source_key=source_key,
                    body_text=body_text,
                    body_origin=body_origin,
                    body_encoding=encoding,
                ),
            )
        )


@document_app.command("create-canonical")
def create_canonical_document(
    project_id: str = typer.Option(..., "--project"),
    repository_id: str = typer.Option(..., "--repository"),
    source_key: str = typer.Option(..., "--source-key"),
    body_file: Path | None = typer.Option(None, "--body-file"),
    body: str | None = typer.Option(None, "--body"),
    body_origin: str = typer.Option(
        ...,
        "--body-origin",
        help="Must be 'canonical'; generated mirror projections are not authoring input.",
    ),
    encoding: str = typer.Option("utf-8", "--encoding"),
    sad_document_id: str | None = typer.Option(None, "--sad-document-id"),
) -> None:
    if (body_file is None) == (body is None):
        raise typer.BadParameter("Provide exactly one of --body-file or --body.")
    if body_file is not None:
        with body_file.open("r", encoding=encoding, newline="") as handle:
            body_text = handle.read()
    else:
        body_text = body or ""
    with _conn() as conn:
        _print(
            ImportExportService(conn).create_canonical_document(
                project_id,
                CanonicalDocumentCreate(
                    repository_id=repository_id,
                    repo_source_key=source_key,
                    body_text=body_text,
                    body_origin=body_origin,
                    body_encoding=encoding,
                    sad_document_id=sad_document_id,
                ),
            )
        )


@app.command("search")
def search(
    project_id: str = typer.Option(..., "--project"),
    query: str = typer.Argument(...),
    include_type: list[str] = typer.Option([], "--type"),
    limit: int = typer.Option(20, "--limit"),
) -> None:
    with _conn() as conn:
        _print(SearchService(conn).search(project_id, query, include_types=include_type or None, limit=limit))


@app.command("context-pack")
def context_pack(
    project_id: str = typer.Option(..., "--project"),
    task: str = typer.Argument(...),
    source_path: list[str] = typer.Option([], "--source-path"),
    max_items: int = typer.Option(20, "--max-items"),
    include_git: bool = typer.Option(True, "--include-git/--no-include-git"),
    include_staleness: bool = typer.Option(True, "--include-staleness/--no-include-staleness"),
) -> None:
    with _conn() as conn:
        _print(
            ContextPackBuilder(conn).build(
                project_id,
                ContextPackRequest(
                    task=task,
                    source_paths=source_path,
                    max_items=max_items,
                    include_git_provenance=include_git,
                    include_staleness=include_staleness,
                ),
            )
        )


@git_app.command("scan")
def scan_git(
    project_id: str = typer.Option(..., "--project"),
    max_commits: int = typer.Option(500, "--max-commits"),
) -> None:
    with _conn() as conn:
        _print(GitScanner(conn).scan_project(project_id, max_commits=max_commits))


@uml_app.command("import")
def import_uml(
    project_id: str = typer.Option(..., "--project"),
    folder: Path = typer.Option(..., "--folder"),
) -> None:
    with _conn() as conn:
        _print(UMLService(conn).import_diagrams(project_id, folder))


@uml_app.command("export")
def export_uml(
    project_id: str = typer.Option(..., "--project"),
    folder: Path = typer.Option(..., "--folder"),
) -> None:
    with _conn() as conn:
        _print(UMLService(conn).export_diagrams(project_id, folder))


@uml_app.command("list")
def list_uml(
    project_id: str = typer.Option(..., "--project"),
    kind: str | None = typer.Option(None, "--kind"),
) -> None:
    with _conn() as conn:
        _print(UMLService(conn).list_diagrams(project_id, kind=kind))


@uml_app.command("get")
def get_uml(
    project_id: str = typer.Option(..., "--project"),
    diagram_id: str = typer.Option(..., "--diagram"),
) -> None:
    with _conn() as conn:
        _print(UMLService(conn).get_diagram(project_id, diagram_id))


@uml_app.command("create")
def create_uml(
    project_id: str = typer.Option(..., "--project"),
    diagram_id: str = typer.Option(..., "--diagram"),
    title: str = typer.Option(..., "--title"),
    kind: str = typer.Option("unknown", "--kind"),
    notation: str = typer.Option("plantuml", "--notation"),
    source_key: str | None = typer.Option(None, "--source-key"),
    sad_document_id: str | None = typer.Option(None, "--sad-document"),
    raw_source: str | None = typer.Option(None, "--raw-source"),
) -> None:
    with _conn() as conn:
        _print(
            UMLService(conn).create_diagram(
                project_id,
                UMLDiagramInput(
                    diagram_id=diagram_id,
                    title=title,
                    diagram_kind=kind,
                    notation=notation,
                    model={
                        "source_key": source_key,
                        "sad_document_id": sad_document_id,
                    },
                    raw_source=raw_source,
                ),
            )
        )


@uml_app.command("update")
def update_uml(
    project_id: str = typer.Option(..., "--project"),
    diagram_id: str = typer.Option(..., "--diagram"),
    title: str | None = typer.Option(None, "--title"),
    kind: str | None = typer.Option(None, "--kind"),
    notation: str | None = typer.Option(None, "--notation"),
    source_key: str | None = typer.Option(None, "--source-key"),
    sad_document_id: str | None = typer.Option(None, "--sad-document"),
    raw_source: str | None = typer.Option(None, "--raw-source"),
) -> None:
    with _conn() as conn:
        _print(
            UMLService(conn).update_diagram(
                project_id,
                diagram_id,
                UMLDiagramUpdate(
                    title=title,
                    diagram_kind=kind,
                    notation=notation,
                    source_key=source_key,
                    sad_document_id=sad_document_id,
                    raw_source=raw_source,
                ),
            )
        )


@uml_app.command("delete")
def delete_uml(
    project_id: str = typer.Option(..., "--project"),
    diagram_id: str = typer.Option(..., "--diagram"),
) -> None:
    with _conn() as conn:
        _print(UMLService(conn).delete_diagram(project_id, diagram_id))


@uml_app.command("element-add")
def add_uml_element(
    project_id: str = typer.Option(..., "--project"),
    diagram_id: str = typer.Option(..., "--diagram"),
    element_type: str = typer.Option(..., "--type"),
    name: str = typer.Option(..., "--name"),
    element_id: str | None = typer.Option(None, "--id"),
    description: str | None = typer.Option(None, "--description"),
) -> None:
    with _conn() as conn:
        _print(
            UMLService(conn).add_element(
                project_id,
                UMLElementInput(
                    diagram_id=diagram_id,
                    element_id=element_id,
                    element_type=element_type,
                    name=name,
                    description=description,
                ),
            )
        )


@uml_app.command("element-update")
def update_uml_element(
    project_id: str = typer.Option(..., "--project"),
    element_id: str = typer.Option(..., "--id"),
    element_type: str | None = typer.Option(None, "--type"),
    name: str | None = typer.Option(None, "--name"),
    description: str | None = typer.Option(None, "--description"),
) -> None:
    with _conn() as conn:
        _print(
            UMLService(conn).update_element(
                project_id,
                element_id,
                UMLElementUpdate(element_type=element_type, name=name, description=description),
            )
        )


@uml_app.command("relationship-add")
def add_uml_relationship(
    project_id: str = typer.Option(..., "--project"),
    diagram_id: str = typer.Option(..., "--diagram"),
    source: str = typer.Option(..., "--source"),
    target: str = typer.Option(..., "--target"),
    relationship_type: str = typer.Option("association", "--type"),
    label: str | None = typer.Option(None, "--label"),
) -> None:
    with _conn() as conn:
        _print(
            UMLService(conn).add_relationship(
                project_id,
                UMLRelationshipInput(
                    diagram_id=diagram_id,
                    source_element_id=source,
                    target_element_id=target,
                    relationship_type=relationship_type,
                    label=label,
                ),
            )
        )


@uml_app.command("element-delete")
def delete_uml_element(
    project_id: str = typer.Option(..., "--project"),
    element_id: str = typer.Option(..., "--id"),
) -> None:
    with _conn() as conn:
        _print(UMLService(conn).delete_element(project_id, element_id))


@uml_app.command("relationship-update")
def update_uml_relationship(
    project_id: str = typer.Option(..., "--project"),
    relationship_uid: str = typer.Option(..., "--id"),
    relationship_type: str | None = typer.Option(None, "--type"),
    label: str | None = typer.Option(None, "--label"),
) -> None:
    with _conn() as conn:
        _print(
            UMLService(conn).update_relationship(
                project_id,
                relationship_uid,
                UMLRelationshipUpdate(relationship_type=relationship_type, label=label),
            )
        )


@uml_app.command("relationship-delete")
def delete_uml_relationship(
    project_id: str = typer.Option(..., "--project"),
    relationship_uid: str = typer.Option(..., "--id"),
) -> None:
    with _conn() as conn:
        _print(UMLService(conn).delete_relationship(project_id, relationship_uid))


@origin_app.command("explain")
def explain_origin(
    project_id: str = typer.Option(..., "--project"),
    target: str = typer.Option(..., "--target"),
    target_type: str = typer.Option("source_path", "--type"),
) -> None:
    with _conn() as conn:
        _print(OriginService(conn).explain(project_id, OriginExplainRequest(target=target, target_type=target_type)))  # type: ignore[arg-type]


@origin_app.command("git-provenance")
def git_provenance(
    project_id: str = typer.Option(..., "--project"),
    target: str = typer.Option(..., "--target"),
    limit_commits: int = typer.Option(10, "--limit-commits"),
) -> None:
    with _conn() as conn:
        _print(OriginService(conn).git_provenance(project_id, target, limit_commits))


@stale_app.command("list")
def list_staleness(
    project_id: str = typer.Option(..., "--project"),
    target: str | None = typer.Option(None, "--target"),
    status: list[str] = typer.Option([], "--status"),
) -> None:
    with _conn() as conn:
        _print(StalenessService(conn).list_reports(project_id, target=target, status_filter=status or None))


@stale_app.command("add")
def add_staleness(
    project_id: str = typer.Option(..., "--project"),
    target: str = typer.Option(..., "--target"),
    target_type: str = typer.Option(..., "--type"),
    status: str = typer.Option(..., "--status"),
    reason: str | None = typer.Option(None, "--reason"),
) -> None:
    with _conn() as conn:
        _print(StalenessService(conn).add_report(project_id, target, target_type, status, reason))


@stale_app.command("compute")
def compute_staleness(
    project_id: str = typer.Option(..., "--project"),
    mode: str = typer.Option("status_quo", "--mode", help="status_quo, git_timeline, or combined."),
    target: str | None = typer.Option(None, "--target"),
    limit: int = typer.Option(500, "--limit"),
) -> None:
    with _conn() as conn:
        _print(StalenessService(conn).compute(project_id, mode=mode, target=target, limit=limit))


@stale_app.command("run")
def run_complete_drift_check(
    project_id: str = typer.Option(..., "--project"),
    target: str | None = typer.Option(None, "--target"),
    limit: int = typer.Option(100, "--limit", help="Number of top status-quo findings to return."),
) -> None:
    with _conn() as conn:
        _print(StalenessService(conn).run_drift_check(project_id, target=target, limit=limit))


@stale_app.command("status-quo")
def find_status_quo_drifts(
    project_id: str = typer.Option(..., "--project"),
    target: str | None = typer.Option(None, "--target"),
    limit: int = typer.Option(100, "--limit"),
    persist: bool = typer.Option(False, "--persist/--no-persist"),
) -> None:
    with _conn() as conn:
        service = StalenessService(conn)
        if persist:
            _print(service.compute_status_quo(project_id, target=target, limit=limit))
        else:
            _print(service.find_status_quo_drifts(project_id, target=target, limit=limit))


@consistency_app.command("check")
def check_consistency(
    project_id: str = typer.Option(..., "--project"),
    scope: str | None = typer.Option(None, "--scope"),
    check_type: list[str] = typer.Option([], "--type"),
) -> None:
    with _conn() as conn:
        _print(ConsistencyService(conn).check(project_id, scope=scope, types=check_type or None))


@consistency_app.command("findings")
def list_consistency_findings(
    project_id: str = typer.Option(..., "--project"),
    finding_type: str | None = typer.Option(None, "--type"),
    severity: str | None = typer.Option(None, "--severity"),
) -> None:
    with _conn() as conn:
        _print(ConsistencyService(conn).list_findings(project_id, finding_type=finding_type, severity=severity))


@consistency_app.command("impact")
def impact_of(
    project_id: str = typer.Option(..., "--project"),
    target: str = typer.Option(..., "--target"),
    depth: int = typer.Option(3, "--depth"),
) -> None:
    with _conn() as conn:
        _print(ConsistencyService(conn).impact_of(project_id, target, depth=depth))


@consistency_app.command("link")
def add_link(
    project_id: str = typer.Option(..., "--project"),
    source: str = typer.Option(..., "--source"),
    target: str = typer.Option(..., "--target"),
    link_type: str = typer.Option(..., "--type"),
    evidence: str | None = typer.Option(None, "--evidence"),
) -> None:
    with _conn() as conn:
        _print(ConsistencyService(conn).link(project_id, source, target, link_type, evidence=evidence))


@consistency_app.command("links")
def get_links(
    project_id: str = typer.Option(..., "--project"),
    target: str | None = typer.Option(None, "--target"),
    direction: str = typer.Option("both", "--direction"),
) -> None:
    with _conn() as conn:
        _print(ConsistencyService(conn).get_links(project_id, target=target, direction=direction))


@mcp_app.command("manifest")
def mcp_manifest() -> None:
    _print(MCP_MANIFEST)


@contextmanager
def _conn():
    conn = initialize_database(Settings.from_env().database_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _print(payload: Any) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


canon_app = typer.Typer(help="Whole-tree repo-native canon mirror export + verification.")
app.add_typer(canon_app, name="canon")


@canon_app.command("export")
def canon_export(
    project: str = typer.Option(..., "--project"),
    folder: Path = typer.Option(..., "--folder"),
) -> None:
    with _conn() as conn:
        _print(ImportExportService(conn).export_canon(project, folder))


@canon_app.command("verify")
def canon_verify(
    project: str = typer.Option(..., "--project"),
    folder: Path = typer.Option(..., "--folder", help="Live repo tree root to verify against."),
) -> None:
    with _conn() as conn:
        _print(ImportExportService(conn).verify_canon(project, folder))


@workspace_app.command("scan")
def workspace_scan(
    project_id: str = typer.Option(..., "--project"),
    repository_id: str = typer.Option(..., "--repository-id"),
) -> None:
    with _conn() as conn:
        _print(WorkspaceService(conn).scan_inventory(project_id, repository_id))


@workspace_app.command("resolve")
def workspace_resolve(
    project_id: str = typer.Option(..., "--project"),
    ref: str = typer.Argument(...),
) -> None:
    with _conn() as conn:
        _print(WorkspaceService(conn).resolve_reference(project_id, ref))


@workspace_app.command("export-manifest")
def workspace_export_manifest(
    project_id: str = typer.Option(..., "--project"),
    folder: Path = typer.Option(..., "--folder"),
) -> None:
    with _conn() as conn:
        path = WorkspaceService(conn).export_manifest(project_id, folder)
    _print({"project_id": project_id, "manifest": path})


def _resolve_spec_uid(conn: Any, project_id: str, spec: str) -> str:
    """Accept a spec's item_uid or its local spec_id (mirrors CompletenessService._resolve_item)."""
    knowledge = KnowledgeService(conn)
    try:
        item = knowledge.get_item_by_uid(spec)
    except ValueError:
        item = None
    if item is not None and item["item_type"] == "spec":
        return spec
    row = conn.execute(
        "SELECT item_uid FROM knowledge_items WHERE project_id = ? AND item_type = 'spec' AND local_id = ?",
        (project_id, spec),
    ).fetchone()
    if row is None:
        raise ValueError(f"Unknown spec: {spec}")
    return row["item_uid"]


@spec_app.command("ingest")
def spec_ingest(
    project: str = typer.Argument(...),
    spec: str = typer.Argument(..., help="Spec item_uid or spec_id."),
    file: Path = typer.Argument(..., help="Markdown file containing the spec body + Architektur-Impact section."),
) -> None:
    text = file.read_text(encoding="utf-8")
    # Specs live under docs/superpowers/specs/** in TTD, which is outside the
    # ttd-canon mirror root rules (docs/architecture|UML|docs/ADR). Remap the
    # durable body into docs/architecture/specs/<filename> so promote/export
    # keeps a byte-exact twin under _generated/specs/ after the source is git-rm'd.
    mirror_key = f"docs/architecture/specs/{file.name}"
    with _conn() as conn:
        spec_uid = _resolve_spec_uid(conn, project, spec)
        knowledge = KnowledgeService(conn)
        current = knowledge.get_item_by_uid(spec_uid)
        details = current["details"]
        metadata = {
            **current.get("metadata", {}),
            "body_text": text,
            "body_encoding": "utf-8",
            "repo_source_key": mirror_key,
            "source_key": file.name,
            "source_path": repo_relative_key(file),
        }
        knowledge.upsert_spec(
            project,
            SpecInput(
                spec_id=details["spec_id"],
                title=current["title"],
                archetype=details["archetype"],
                lifecycle=details.get("lifecycle", "draft"),
                mvp_uid=details.get("mvp_uid"),
                sections=details.get("sections", []),
                summary=current.get("summary"),
                metadata=metadata,
            ),
        )
        impact = ChangeSetService(conn).ingest_impact(project, spec_uid, text)
        status = AuthoringService(conn).set_spec_status(project, spec_uid, "ready")
    _print({"impact": impact, "status": status, "repo_source_key": mirror_key})


@work_app.command("open")
def work_open(project: str = typer.Argument(...)) -> None:
    with _conn() as conn:
        _print(ChangeSetService(conn).open_work_orders(project))


@spec_app.command("plan-basis")
def spec_plan_basis(
    project: str = typer.Argument(...),
    spec: str = typer.Argument(..., help="Spec item_uid or spec_id."),
) -> None:
    with _conn() as conn:
        spec_uid = _resolve_spec_uid(conn, project, spec)
        _print(ChangeSetService(conn).plan_basis(project, spec_uid))


@change_app.command("set-state")
def change_set_state(
    project: str = typer.Argument(...),
    item_id: int = typer.Argument(...),
    state: str = typer.Argument(..., help="proposed | in_progress | done"),
) -> None:
    with _conn() as conn:
        _print(ChangeSetService(conn).set_item_state(project, item_id, state))


@spec_app.command("promote")
def spec_promote(
    project: str = typer.Argument(...),
    spec: str = typer.Argument(..., help="Spec item_uid or spec_id."),
    force: bool = typer.Option(False, "--force", help="Promote even if change items are still open."),
) -> None:
    with _conn() as conn:
        spec_uid = _resolve_spec_uid(conn, project, spec)
        result = ChangeSetService(conn).promote(project, spec_uid, force=force)
    _print(result)
    if result.get("refused"):
        raise typer.Exit(code=1)


export_app = typer.Typer(help="Deterministic corpus export and round-trip verification.")
app.add_typer(export_app, name="export")


@export_app.command("run")
def export_run(
    project: str = typer.Option(..., "--project", help="Project id."),
    folder: Path = typer.Option(..., "--folder", help="Destination export folder."),
) -> None:
    with _conn() as conn:
        _print(ImportExportService(conn).export_corpus(project, folder))


@export_app.command("verify")
def export_verify(
    project: str = typer.Option(..., "--project", help="Project id."),
    folder: Path = typer.Option(..., "--folder", help="Existing export folder to verify."),
) -> None:
    with _conn() as conn:
        _print(ImportExportService(conn).verify_corpus(project, folder))


@export_app.command("target-add")
def export_target_add(
    project: str = typer.Argument(...),
    target_id: str = typer.Argument(...),
    repo: str = typer.Option(..., "--repo", help="repository_id owning dest_root."),
    dest: Path = typer.Option(..., "--dest", help="Destination mirror root."),
    layout: str = typer.Option(..., "--layout"),
    kinds: str = typer.Option(..., "--kinds", help="Comma-separated content kinds, e.g. sad,uml,adr."),
    no_auto: bool = typer.Option(False, "--no-auto", help="Disable auto-flush for this target."),
    disabled: bool = typer.Option(False, "--disabled", help="Register the target as disabled."),
) -> None:
    from architectural_knowledge_db.services.export_targets import ExportTargetsService

    content_kinds = [k.strip() for k in kinds.split(",") if k.strip()]
    with _conn() as conn:
        ExportTargetsService(conn).register_target(
            project,
            target_id,
            repository_id=repo,
            dest_root=str(dest),
            layout=layout,
            content_kinds=content_kinds,
            auto_export=not no_auto,
            enabled=not disabled,
        )
        _print(ExportTargetsService(conn).get_target(project, target_id))


@export_app.command("target-list")
def export_target_list(project: str = typer.Argument(...)) -> None:
    from architectural_knowledge_db.services.export_targets import ExportTargetsService

    with _conn() as conn:
        _print(ExportTargetsService(conn).list_targets(project))


@export_app.command("target-delete")
def export_target_delete(
    project: str = typer.Argument(...),
    target_id: str = typer.Argument(...),
) -> None:
    from architectural_knowledge_db.services.export_targets import ExportTargetsService

    with _conn() as conn:
        _print(ExportTargetsService(conn).delete_target(project, target_id))


def _resolve_targets(conn: Any, project: str, target: str | None) -> list[str]:
    from architectural_knowledge_db.services.export_targets import ExportTargetsService

    if target:
        return [target]
    return [t["target_id"] for t in ExportTargetsService(conn).list_targets(project, enabled_only=True)]


@export_app.command("flush")
def export_flush(
    project: str = typer.Argument(...),
    target: str | None = typer.Option(None, "--target"),
) -> None:
    with _conn() as conn:
        results = {t: ImportExportService(conn).export_incremental(project, t) for t in _resolve_targets(conn, project, target)}
    _print(results)


@export_app.command("sync")
def export_sync(
    project: str = typer.Argument(...),
    target: str | None = typer.Option(None, "--target"),
) -> None:
    with _conn() as conn:
        results = {t: ImportExportService(conn).export_sync(project, t) for t in _resolve_targets(conn, project, target)}
    _print(results)


@export_app.command("target-verify")
def export_target_verify(
    project: str = typer.Argument(...),
    target: str | None = typer.Option(None, "--target"),
) -> None:
    with _conn() as conn:
        targets = _resolve_targets(conn, project, target)
        results = {t: ImportExportService(conn).verify_export(project, t) for t in targets}
    _print(results)
    drifted = any(r["mismatched"] or r["missing"] or r["extra"] for r in results.values())
    if drifted:
        raise typer.Exit(code=1)


@obsidian_app.command("sync")
def obsidian_sync(
    project: str = typer.Argument(...),
    target: str | None = typer.Option(None, "--target"),
) -> None:
    """Full rebuild of an obsidian-vault target (layout dispatch inside export_sync)."""
    with _conn() as conn:
        results = {
            t: ImportExportService(conn).export_sync(project, t)
            for t in _resolve_targets(conn, project, target)
        }
    _print(results)


@obsidian_app.command("verify")
def obsidian_verify(
    project: str = typer.Argument(...),
    target: str | None = typer.Option(None, "--target"),
) -> None:
    """Byte-compare an obsidian-vault target; exit 1 on mismatched/missing/extra."""
    with _conn() as conn:
        targets = _resolve_targets(conn, project, target)
        results = {t: ImportExportService(conn).verify_export(project, t) for t in targets}
    _print(results)
    drifted = any(r["mismatched"] or r["missing"] or r["extra"] for r in results.values())
    if drifted:
        raise typer.Exit(code=1)


def _parse_projects_csv(projects: str) -> list[str]:
    return [p.strip() for p in projects.split(",") if p.strip()]


def _resolve_vault_root(conn: Any, project_ids: list[str], vault_root: Path | None) -> Path:
    if vault_root is not None:
        return Path(vault_root)
    from architectural_knowledge_db.services.export_targets import ExportTargetsService

    ets = ExportTargetsService(conn)
    for pid in project_ids:
        for target in ets.list_targets(pid):
            if target.get("enabled") and target.get("layout") == "obsidian-vault":
                dest = ets.resolve_dest_root(pid, target["target_id"])
                return Path(dest).parent
    raise typer.BadParameter(
        "Could not infer vault root from obsidian-vault targets; pass --vault-root."
    )


@obsidian_app.command("build-index")
def obsidian_build_index(
    projects: str = typer.Option(..., "--projects", help="Comma-separated project ids."),
    vault_root: Path | None = typer.Option(None, "--vault-root", help="Vault repo root (owns _index/)."),
) -> None:
    """Write/refresh workspace ``_index/`` MOCs at the vault root."""
    from architectural_knowledge_db.services.obsidian_export import write_workspace_index

    project_ids = _parse_projects_csv(projects)
    with _conn() as conn:
        root = _resolve_vault_root(conn, project_ids, vault_root)
        result = write_workspace_index(conn, project_ids, root)
    _print(result)


@obsidian_app.command("verify-index")
def obsidian_verify_index(
    projects: str = typer.Option(..., "--projects", help="Comma-separated project ids."),
    vault_root: Path | None = typer.Option(None, "--vault-root", help="Vault repo root (owns _index/)."),
) -> None:
    """Re-render ``_index/`` and byte-compare; exit 1 on drift."""
    from architectural_knowledge_db.services.obsidian_export import verify_workspace_index

    project_ids = _parse_projects_csv(projects)
    with _conn() as conn:
        root = _resolve_vault_root(conn, project_ids, vault_root)
        result = verify_workspace_index(conn, project_ids, root)
    _print(result)
    if result["mismatched"] or result["missing"] or result["extra"]:
        raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
