from __future__ import annotations

from html import escape
import sqlite3
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from architectural_knowledge_db.config import Settings
from architectural_knowledge_db.db.connection import connect, initialize_database
from architectural_knowledge_db.mcp import MCP_MANIFEST, McpDispatcher
from architectural_knowledge_db.models import (
    AdrInput,
    ConsistencyCheckRequest,
    ContextPackRequest,
    DefinitionInput,
    ImpactRequest,
    KnowledgeLinkInput,
    LinkQueryRequest,
    OriginExplainRequest,
    ProjectUpsert,
    RepositoryRegistration,
    RuleInput,
    SearchRequest,
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
from architectural_knowledge_db.services.staleness import StalenessService
from architectural_knowledge_db.services.uml import UMLService


_migrated_database_paths: set[str] = set()


def create_app() -> FastAPI:
    app = FastAPI(
        title="ArchitecturalKnowledgeDB Knowledge DB API",
        version="0.2.0",
        description="Multi-project DB-first architecture knowledge service with linked Git provenance.",
    )
    database_path = Settings.from_env().database_path
    migrated_key = str(database_path.resolve())
    if migrated_key not in _migrated_database_paths:
        _init = initialize_database(database_path)
        _init.close()
        _migrated_database_paths.add(migrated_key)

    @app.get("/health")
    def health(conn: Annotated[sqlite3.Connection, Depends(get_connection)]) -> dict[str, Any]:
        row = conn.execute("SELECT 1 AS ok").fetchone()
        return {"status": "ok", "database": bool(row["ok"])}

    @app.get("/", response_class=HTMLResponse)
    def admin_home(conn: Annotated[sqlite3.Connection, Depends(get_connection)]) -> str:
        return render_admin_home(conn)

    @app.get("/projects")
    def list_projects(conn: Annotated[sqlite3.Connection, Depends(get_connection)]) -> list[dict[str, Any]]:
        return ProjectService(conn).list_projects()

    @app.post("/projects")
    def upsert_project(
        request: ProjectUpsert,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    ) -> dict[str, Any]:
        return _run(lambda: ProjectService(conn).upsert_project(request))

    @app.get("/projects/{project_id}/repositories")
    def list_repositories(
        project_id: str,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    ) -> list[dict[str, Any]]:
        return _run(lambda: RepositoryService(conn).list_repositories(project_id))

    @app.post("/projects/{project_id}/repositories")
    def register_repository(
        project_id: str,
        request: RepositoryRegistration,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    ) -> dict[str, Any]:
        return _run(lambda: RepositoryService(conn).register_repository(project_id, request))

    @app.post("/projects/{project_id}/index/rebuild", status_code=202)
    def rebuild_index(
        project_id: str,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    ) -> dict[str, Any]:
        return _run(lambda: KnowledgeService(conn).rebuild_fts(project_id))

    @app.post("/projects/{project_id}/git/scan", status_code=202)
    def scan_git(
        project_id: str,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
        max_commits: int = Query(default=500, ge=1, le=10000),
    ) -> dict[str, Any]:
        return _run(lambda: GitScanner(conn).scan_project(project_id, max_commits=max_commits))

    @app.get("/projects/{project_id}/git/provenance")
    def git_provenance(
        project_id: str,
        target: str,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
        limit_commits: int = Query(default=10, ge=1, le=100),
    ) -> dict[str, Any]:
        return _run(lambda: OriginService(conn).git_provenance(project_id, target, limit_commits))

    @app.post("/projects/{project_id}/search")
    def search(
        project_id: str,
        request: SearchRequest,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    ) -> list[dict[str, Any]]:
        return _run(
            lambda: SearchService(conn).search(
                project_id,
                request.query,
                include_types=request.include_types,
                include_shared=request.include_shared,
                limit=request.limit,
            )
        )

    @app.get("/projects/{project_id}/knowledge/items")
    def list_items(
        project_id: str,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
        item_type: str | None = None,
        include_shared: bool = True,
        limit: int = Query(default=100, ge=1, le=5000),
    ) -> list[dict[str, Any]]:
        include_types = [item_type] if item_type else None
        return _run(lambda: KnowledgeService(conn).list_items(project_id, include_types, include_shared, limit))

    @app.post("/projects/{project_id}/context-pack")
    def context_pack(
        project_id: str,
        request: ContextPackRequest,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    ) -> dict[str, Any]:
        return _run(lambda: ContextPackBuilder(conn).build(project_id, request))

    @app.post("/projects/{project_id}/origin/explain")
    def explain_origin(
        project_id: str,
        request: OriginExplainRequest,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    ) -> dict[str, Any]:
        return _run(lambda: OriginService(conn).explain(project_id, request))

    @app.get("/projects/{project_id}/staleness")
    def staleness(
        project_id: str,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
        target: str | None = None,
        status_filter: list[str] | None = Query(default=None),
    ) -> list[dict[str, Any]]:
        return _run(lambda: StalenessService(conn).list_reports(project_id, target, status_filter))

    @app.post("/projects/{project_id}/staleness/compute")
    def compute_staleness(
        project_id: str,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
        mode: str = Query(default="status_quo"),
        target: str | None = None,
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> dict[str, Any]:
        return _run(lambda: StalenessService(conn).compute(project_id, mode=mode, target=target, limit=limit))

    @app.post("/projects/{project_id}/drift/run")
    def run_drift_check(
        project_id: str,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
        target: str | None = None,
        limit: int = Query(default=100, ge=1, le=5000),
    ) -> dict[str, Any]:
        return _run(lambda: StalenessService(conn).run_drift_check(project_id, target=target, limit=limit))

    @app.get("/projects/{project_id}/drift/status-quo")
    def status_quo_drift(
        project_id: str,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
        target: str | None = None,
        limit: int = Query(default=100, ge=1, le=5000),
    ) -> dict[str, Any]:
        return _run(lambda: StalenessService(conn).find_status_quo_drifts(project_id, target=target, limit=limit))

    @app.post("/projects/{project_id}/drift/status-quo/compute")
    def compute_status_quo_drift(
        project_id: str,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
        target: str | None = None,
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> dict[str, Any]:
        return _run(lambda: StalenessService(conn).compute_status_quo(project_id, target=target, limit=limit))


    @app.post("/projects/{project_id}/adrs")
    def upsert_adr(
        project_id: str,
        request: AdrInput,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    ) -> dict[str, Any]:
        return _run(lambda: KnowledgeService(conn).upsert_adr(project_id, request))

    @app.get("/projects/{project_id}/adrs")
    def list_adrs(
        project_id: str,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
        status: str | None = None,
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> list[dict[str, Any]]:
        return _run(lambda: KnowledgeService(conn).list_adrs(project_id, status=status, limit=limit))

    @app.get("/projects/{project_id}/adrs/{adr_id}")
    def get_adr(
        project_id: str,
        adr_id: str,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    ) -> dict[str, Any]:
        return _run(lambda: KnowledgeService(conn).get_adr(project_id, adr_id))

    @app.post("/projects/{project_id}/rules")
    def upsert_rule(
        project_id: str,
        request: RuleInput,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    ) -> dict[str, Any]:
        return _run(lambda: KnowledgeService(conn).upsert_rule(project_id, request))

    @app.post("/projects/{project_id}/definitions")
    def upsert_definition(
        project_id: str,
        request: DefinitionInput,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    ) -> dict[str, Any]:
        return _run(lambda: KnowledgeService(conn).upsert_definition(project_id, request))

    @app.post("/projects/{project_id}/source-areas")
    def upsert_source_area(
        project_id: str,
        request: SourceAreaInput,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    ) -> dict[str, Any]:
        return _run(lambda: KnowledgeService(conn).upsert_source_area(project_id, request))

    @app.post("/projects/{project_id}/links")
    def upsert_link(
        project_id: str,
        request: KnowledgeLinkInput,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    ) -> dict[str, Any]:
        return _run(lambda: KnowledgeService(conn).upsert_link(project_id, request))

    @app.get("/projects/{project_id}/rules/for-path")
    def rules_for_path(
        project_id: str,
        path: str,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    ) -> list[dict[str, Any]]:
        return _run(lambda: KnowledgeService(conn).matching_rules_for_path(project_id, path))

    @app.post("/projects/{project_id}/imports/adrs")
    def import_adrs(
        project_id: str,
        folder: str,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    ) -> dict[str, Any]:
        return _run(lambda: ImportExportService(conn).import_adrs(project_id, folder))

    @app.post("/projects/{project_id}/imports/documents")
    def import_documents(
        project_id: str,
        folder: str,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
        include: list[str] | None = Query(default=None),
        exclude: list[str] | None = Query(default=None),
    ) -> dict[str, Any]:
        return _run(lambda: ImportExportService(conn).import_documents(project_id, folder, include, exclude))

    @app.post("/projects/{project_id}/exports/adrs")
    def export_adrs(
        project_id: str,
        folder: str,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    ) -> dict[str, Any]:
        return _run(lambda: ImportExportService(conn).export_adrs(project_id, folder))

    @app.post("/projects/{project_id}/uml/import")
    def import_uml(
        project_id: str,
        folder: str,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    ) -> dict[str, Any]:
        return _run(lambda: UMLService(conn).import_diagrams(project_id, folder))

    @app.post("/projects/{project_id}/uml/export")
    def export_uml(
        project_id: str,
        folder: str,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    ) -> dict[str, Any]:
        return _run(lambda: UMLService(conn).export_diagrams(project_id, folder))

    @app.get("/projects/{project_id}/uml/diagrams")
    def list_diagrams(
        project_id: str,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
        kind: str | None = None,
        limit: int = Query(default=100, ge=1, le=1000),
    ) -> list[dict[str, Any]]:
        return _run(lambda: UMLService(conn).list_diagrams(project_id, kind=kind, limit=limit))

    @app.get("/projects/{project_id}/uml/diagrams/{diagram_id}")
    def get_diagram(
        project_id: str,
        diagram_id: str,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    ) -> dict[str, Any]:
        return _run(lambda: UMLService(conn).get_diagram(project_id, diagram_id))

    @app.post("/projects/{project_id}/uml/elements")
    def add_uml_element(
        project_id: str,
        request: UMLElementInput,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    ) -> dict[str, Any]:
        return _run(lambda: UMLService(conn).add_element(project_id, request))

    @app.put("/projects/{project_id}/uml/elements/{element_id}")
    def update_uml_element(
        project_id: str,
        element_id: str,
        request: UMLElementUpdate,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    ) -> dict[str, Any]:
        return _run(lambda: UMLService(conn).update_element(project_id, element_id, request))

    @app.post("/projects/{project_id}/uml/relationships")
    def add_uml_relationship(
        project_id: str,
        request: UMLRelationshipInput,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    ) -> dict[str, Any]:
        return _run(lambda: UMLService(conn).add_relationship(project_id, request))

    @app.post("/projects/{project_id}/consistency/check")
    def check_consistency(
        project_id: str,
        request: ConsistencyCheckRequest,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    ) -> list[dict[str, Any]]:
        return _run(lambda: ConsistencyService(conn).check(project_id, scope=request.scope, types=request.types))

    @app.get("/projects/{project_id}/consistency/findings")
    def list_consistency_findings(
        project_id: str,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
        finding_type: str | None = None,
        severity: str | None = None,
    ) -> list[dict[str, Any]]:
        return _run(lambda: ConsistencyService(conn).list_findings(project_id, finding_type, severity))

    @app.post("/projects/{project_id}/impact")
    def impact_of(
        project_id: str,
        request: ImpactRequest,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    ) -> dict[str, Any]:
        return _run(lambda: ConsistencyService(conn).impact_of(project_id, request.target, depth=request.depth))

    @app.post("/projects/{project_id}/links/query")
    def query_links(
        project_id: str,
        request: LinkQueryRequest,
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    ) -> dict[str, Any]:
        return _run(lambda: ConsistencyService(conn).get_links(project_id, target=request.target, direction=request.direction))

    @app.get("/mcp/manifest")
    def mcp_manifest() -> dict[str, Any]:
        return MCP_MANIFEST

    @app.post("/mcp/dispatch")
    def mcp_dispatch(
        payload: dict[str, Any],
        conn: Annotated[sqlite3.Connection, Depends(get_connection)],
    ) -> Any:
        tool_name = payload.get("tool_name") or payload.get("name")
        if not tool_name:
            raise HTTPException(status_code=422, detail="tool_name is required")
        arguments = payload.get("arguments") or {}
        return _run(lambda: McpDispatcher(conn).dispatch(tool_name, dict(arguments)))

    return app


def get_connection() -> sqlite3.Connection:
    conn = connect(Settings.from_env().database_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _run(callback: Any) -> Any:
    try:
        return callback()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def render_admin_home(conn: sqlite3.Connection) -> str:
    projects = ProjectService(conn).list_projects()
    project_options = "\n".join(
        f'<option value="{escape(project["project_id"])}">{escape(project["display_name"])}</option>' for project in projects
    )
    project_rows = "\n".join(
        f"""
        <tr>
          <td>{escape(project["project_id"])}</td>
          <td>{escape(project["display_name"])}</td>
          <td>{escape(", ".join(project.get("imports", [])))}</td>
          <td><a href="/docs#/default/list_repositories_projects__project_id__repositories_get">Repositories</a></td>
        </tr>
        """
        for project in projects
    ) or '<tr><td colspan="4">No projects registered yet.</td></tr>'
    overview_rows = "\n".join(
        f"""
        <tr>
          <td>{escape(row["project_id"])}</td>
          <td>{escape(row["item_type"])}</td>
          <td>{row["count"]}</td>
        </tr>
        """
        for row in conn.execute(
            """
            SELECT project_id, item_type, COUNT(*) AS count
            FROM knowledge_items
            GROUP BY project_id, item_type
            ORDER BY project_id, item_type
            """
        ).fetchall()
    ) or '<tr><td colspan="3">No knowledge items imported yet.</td></tr>'
    recent_rows = "\n".join(
        f"""
        <tr>
          <td>{escape(row["project_id"])}</td>
          <td>{escape(row["item_type"])}</td>
          <td>{escape(row["local_id"])}</td>
          <td>{escape(row["title"] or "")}</td>
          <td>{escape(row["source_uri"] or "")}</td>
        </tr>
        """
        for row in conn.execute(
            """
            SELECT project_id, item_type, local_id, title, source_uri
            FROM knowledge_items
            ORDER BY updated_at DESC
            LIMIT 12
            """
        ).fetchall()
    ) or '<tr><td colspan="5">No recent items.</td></tr>'
    diagram_rows = "\n".join(
        f"""
        <tr>
          <td>{escape(row["project_id"])}</td>
          <td>{escape(row["diagram_id"])}</td>
          <td>{escape(row["title"] or "")}</td>
          <td>{escape(row["notation"] or "")}</td>
          <td>{escape(row["diagram_kind"] or "")}</td>
        </tr>
        """
        for row in conn.execute(
            """
            SELECT project_id, diagram_id, title, notation, diagram_kind
            FROM uml_diagrams
            ORDER BY project_id, diagram_id
            LIMIT 20
            """
        ).fetchall()
    ) or '<tr><td colspan="5">No UML diagrams imported yet.</td></tr>'
    default_folder = "." if projects else str(Settings.from_env().database_path.parent)
    return f"""
    <!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>ArchitecturalKnowledgeDB Admin</title>
      <style>
        :root {{ color-scheme: light; font-family: Inter, Segoe UI, Arial, sans-serif; }}
        body {{ margin: 0; background: #f7f8fa; color: #17202a; }}
        header {{ padding: 18px 24px; background: #ffffff; border-bottom: 1px solid #d9dee7; display: flex; justify-content: space-between; align-items: center; }}
        main {{ padding: 20px 24px; display: grid; gap: 18px; grid-template-columns: minmax(0, 1.1fr) minmax(320px, .9fr); }}
        section {{ background: #ffffff; border: 1px solid #d9dee7; border-radius: 8px; padding: 16px; }}
        h1 {{ font-size: 20px; margin: 0; }}
        h2 {{ font-size: 15px; margin: 0 0 12px; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
        th, td {{ text-align: left; padding: 9px 8px; border-bottom: 1px solid #edf0f4; vertical-align: top; }}
        label {{ display: grid; gap: 5px; font-size: 12px; color: #4a5565; margin-bottom: 10px; }}
        input, select, textarea {{ width: 100%; box-sizing: border-box; border: 1px solid #cbd3df; border-radius: 6px; padding: 8px; font: inherit; background: #fff; }}
        textarea {{ min-height: 86px; resize: vertical; }}
        button {{ border: 0; border-radius: 6px; padding: 8px 10px; background: #2457a6; color: #fff; cursor: pointer; }}
        button.secondary {{ background: #4f5b67; }}
        .actions {{ display: flex; gap: 8px; flex-wrap: wrap; }}
        .wide {{ grid-column: 1 / -1; }}
        pre {{ background: #101820; color: #eef4ff; border-radius: 8px; padding: 12px; overflow: auto; max-height: 360px; }}
        @media (max-width: 900px) {{ main {{ grid-template-columns: 1fr; }} }}
      </style>
    </head>
    <body>
      <header>
        <h1>ArchitecturalKnowledgeDB Admin</h1>
        <nav><a href="/docs">OpenAPI</a> · <a href="/mcp/manifest">MCP Manifest</a></nav>
      </header>
      <main>
        <section>
          <h2>Projects</h2>
          <table>
            <thead><tr><th>ID</th><th>Name</th><th>Imports</th><th>Links</th></tr></thead>
            <tbody>{project_rows}</tbody>
          </table>
        </section>
        <section>
          <h2>Add Project</h2>
          <label>ID<input id="project-id" value="architectural-knowledge-db"></label>
          <label>Name<input id="project-name" value="ArchitecturalKnowledgeDB"></label>
          <button onclick="addProject()">Save</button>
        </section>
        <section>
          <h2>Knowledge Overview</h2>
          <table>
            <thead><tr><th>Project</th><th>Type</th><th>Count</th></tr></thead>
            <tbody>{overview_rows}</tbody>
          </table>
        </section>
        <section>
          <h2>Operations</h2>
          <label>Project<select id="selected-project">{project_options}</select></label>
          <label>Folder<input id="folder" value="{escape(default_folder)}"></label>
          <div class="actions">
            <button onclick="postOperation('/imports/adrs')">Import ADRs</button>
            <button onclick="postOperation('/imports/documents')">Import Documents</button>
            <button onclick="postOperation('/uml/import')">Import UML</button>
            <button onclick="postNoBody('/git/scan')">Scan Git</button>
            <button onclick="postNoBody('/index/rebuild')">Rebuild Index</button>
            <button class="secondary" onclick="postNoBody('/drift/run')">Full Drift Run</button>
            <button class="secondary" onclick="postNoBody('/staleness/compute?mode=status_quo')">Status-quo Drift</button>
            <button class="secondary" onclick="postNoBody('/staleness/compute?mode=git_timeline')">Git Timeline Drift</button>
            <button class="secondary" onclick="checkConsistency()">Check Consistency</button>
            <button class="secondary" onclick="listItems()">List Items</button>
            <button class="secondary" onclick="listDiagrams()">List UML</button>
          </div>
        </section>
        <section>
          <h2>Context Pack</h2>
          <label>Task<textarea id="task">Modify the architecture knowledge store safely</textarea></label>
          <button onclick="contextPack()">Run</button>
        </section>
        <section class="wide">
          <h2>Recent Items</h2>
          <table>
            <thead><tr><th>Project</th><th>Type</th><th>ID</th><th>Title</th><th>Source</th></tr></thead>
            <tbody>{recent_rows}</tbody>
          </table>
        </section>
        <section class="wide">
          <h2>UML Diagrams</h2>
          <table>
            <thead><tr><th>Project</th><th>ID</th><th>Title</th><th>Notation</th><th>Kind</th></tr></thead>
            <tbody>{diagram_rows}</tbody>
          </table>
        </section>
        <section class="wide">
          <h2>Result</h2>
          <pre id="result">{{}}</pre>
        </section>
      </main>
      <script>
        const result = document.getElementById('result');
        const project = () => document.getElementById('selected-project').value;
        async function show(response) {{
          const text = await response.text();
          try {{ result.textContent = JSON.stringify(JSON.parse(text), null, 2); }}
          catch {{ result.textContent = text; }}
        }}
        async function addProject() {{
          await show(await fetch('/projects', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{project_id: document.getElementById('project-id').value, display_name: document.getElementById('project-name').value}})
          }}));
        }}
        async function postOperation(path) {{
          const folder = encodeURIComponent(document.getElementById('folder').value);
          await show(await fetch(`/projects/${{project()}}${{path}}?folder=${{folder}}`, {{method: 'POST'}}));
        }}
        async function postNoBody(path) {{
          await show(await fetch(`/projects/${{project()}}${{path}}`, {{method: 'POST'}}));
        }}
        async function checkConsistency() {{
          await show(await fetch(`/projects/${{project()}}/consistency/check`, {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{}})
          }}));
        }}
        async function contextPack() {{
          await show(await fetch(`/projects/${{project()}}/context-pack`, {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{task: document.getElementById('task').value}})
          }}));
        }}
        async function listItems() {{
          await show(await fetch(`/projects/${{project()}}/knowledge/items?limit=200`));
        }}
        async function listDiagrams() {{
          await show(await fetch(`/projects/${{project()}}/uml/diagrams?limit=200`));
        }}
      </script>
    </body>
    </html>
    """


app = create_app()
