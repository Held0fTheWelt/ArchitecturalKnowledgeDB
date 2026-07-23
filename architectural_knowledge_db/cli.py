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
    ContextPackRequest,
    DefinitionInput,
    KnowledgeSpace,
    OriginExplainRequest,
    ProjectUpsert,
    RepositoryRegistration,
    RuleInput,
    SourceAreaInput,
    UMLElementInput,
    UMLElementUpdate,
    UMLRelationshipInput,
)
from architectural_knowledge_db.services.consistency import ConsistencyService
from architectural_knowledge_db.services.context import ContextPackBuilder
from architectural_knowledge_db.services.git_scanner import GitScanner
from architectural_knowledge_db.services.import_export import ImportExportService
from architectural_knowledge_db.services.knowledge import KnowledgeService
from architectural_knowledge_db.services.origin import OriginService
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.services.repositories import RepositoryService
from architectural_knowledge_db.services.search import SearchService
from architectural_knowledge_db.services.setup import StarterSetupService
from architectural_knowledge_db.services.staleness import StalenessService
from architectural_knowledge_db.services.uml import UMLService


app = typer.Typer(help="ArchitecturalKnowledgeDB local service CLI.")
project_app = typer.Typer(help="Manage projects and shared spaces.")
repo_app = typer.Typer(help="Manage source repositories.")
adr_app = typer.Typer(help="Import, export, and inspect ADRs.")
sad_app = typer.Typer(help="Export arc42 Software Architecture Documents.")
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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
