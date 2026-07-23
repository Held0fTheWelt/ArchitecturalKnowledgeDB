from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_PORT = 8787


@dataclass(frozen=True)
class Settings:
    data_root: Path
    database_path: Path
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    store_author_email_hash: bool = False
    include_commit_body: bool = False
    auto_export_root: Path | None = None
    database_url: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        data_root = Path(os.getenv("AKDB_DATA_ROOT", ".akdb")).expanduser().resolve()
        database_path = Path(
            os.getenv("AKDB_DATABASE_PATH", str(data_root / "architectural_knowledge_db.sqlite"))
        ).expanduser().resolve()
        host = os.getenv("AKDB_HOST", "127.0.0.1")
        port = int(os.getenv("AKDB_PORT", str(DEFAULT_PORT)))
        database_url = os.getenv("AKDB_DB_URL") or None
        return cls(
            data_root=data_root,
            database_path=database_path,
            host=host,
            port=port,
            store_author_email_hash=_truthy(os.getenv("AKDB_STORE_AUTHOR_EMAIL_HASH")),
            include_commit_body=_truthy(os.getenv("AKDB_INCLUDE_COMMIT_BODY")),
            auto_export_root=_auto_export_root(data_root, database_path),
            database_url=database_url,
        )


def _truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


def _falsy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"0", "false", "no", "off"}


def _auto_export_root(data_root: Path, database_path: Path) -> Path | None:
    if _falsy(os.getenv("AKDB_AUTO_EXPORT")):
        return None
    explicit = os.getenv("AKDB_AUTO_EXPORT_ROOT") or os.getenv("AKDB_EXPORT_ROOT")
    if explicit and explicit.strip():
        return Path(explicit).expanduser().resolve()
    if _truthy(os.getenv("AKDB_AUTO_EXPORT")):
        return (data_root / "exports").resolve()
    return None


def auto_export_root_for_database(database_path: Path | str) -> Path | None:
    database = Path(database_path).expanduser().resolve()
    data_root = Path(os.getenv("AKDB_DATA_ROOT", str(database.parent))).expanduser().resolve()
    return _auto_export_root(data_root, database)


AKDB_SELF_PROJECT_ID = "architectural-knowledge-db"


def self_export_target(
    project_id: str,
    *,
    data_root: Path | str | None = None,
    database_path: Path | str | None = None,
) -> Path | None:
    """Default arc42/SAD export folder for known AKDB workspace layouts.

    Standalone AKDB repo + project ``architectural-knowledge-db`` maps to
    ``<repo>/docs/architecture``.
    Explicit ``--folder`` / env roots remain authoritative when callers supply them.
    """
    layout = _workspace_layout(data_root, database_path)
    if layout is None:
        return None
    kind, repo, _workspace = layout
    if kind == "standalone" and project_id == AKDB_SELF_PROJECT_ID:
        return (repo / "docs" / "architecture").resolve()
    return None


def _workspace_layout(
    data_root: Path | str | None,
    database_path: Path | str | None,
) -> tuple[str, Path, Path] | None:
    try:
        if database_path is None:
            database = Path(
                os.getenv("AKDB_DATABASE_PATH", str(Path(os.getenv("AKDB_DATA_ROOT", ".akdb")) / "architectural_knowledge_db.sqlite"))
            ).expanduser().resolve()
        else:
            database = Path(database_path).expanduser().resolve()
        if data_root is None:
            data = Path(os.getenv("AKDB_DATA_ROOT", str(database.parent))).expanduser().resolve()
        else:
            data = Path(data_root).expanduser().resolve()
    except OSError:
        return None
    if data.name.lower() != ".akdb" or database.parent != data:
        return None
    repo = data.parent
    if repo.name != "ArchitecturalKnowledgeDB":
        return None
    if repo.parent.name == "Tools":
        return None
    # Standalone public AKDB checkout (e.g. TinyToolDevelopment/ArchitecturalKnowledgeDB).
    return ("standalone", repo, repo.parent)


def load_project_registry(path: Path) -> dict[str, Any]:
    """Load a JSON or YAML project registry."""
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        import json

        return json.loads(text)

    import yaml

    loaded = yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise ValueError(f"Project registry must be a mapping: {path}")
    return loaded
