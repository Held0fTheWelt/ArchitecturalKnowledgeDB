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

    @classmethod
    def from_env(cls) -> "Settings":
        data_root = Path(os.getenv("AKDB_DATA_ROOT", ".akdb")).expanduser().resolve()
        database_path = Path(
            os.getenv("AKDB_DATABASE_PATH", str(data_root / "architectural_knowledge_db.sqlite"))
        ).expanduser().resolve()
        host = os.getenv("AKDB_HOST", "127.0.0.1")
        port = int(os.getenv("AKDB_PORT", str(DEFAULT_PORT)))
        return cls(
            data_root=data_root,
            database_path=database_path,
            host=host,
            port=port,
            store_author_email_hash=_truthy(os.getenv("AKDB_STORE_AUTHOR_EMAIL_HASH")),
            include_commit_body=_truthy(os.getenv("AKDB_INCLUDE_COMMIT_BODY")),
            auto_export_root=_auto_export_root(data_root, database_path),
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
    return _workspace_auto_export_root(data_root, database_path)


def auto_export_root_for_database(database_path: Path | str) -> Path | None:
    database = Path(database_path).expanduser().resolve()
    data_root = Path(os.getenv("AKDB_DATA_ROOT", str(database.parent))).expanduser().resolve()
    return _auto_export_root(data_root, database)


def _workspace_auto_export_root(data_root: Path, database_path: Path) -> Path | None:
    try:
        data = data_root.resolve()
        database = database_path.resolve()
    except OSError:
        return None
    if data.name.lower() != ".akdb" or database.parent != data:
        return None
    repo = data.parent
    if repo.name != "ArchitecturalKnowledgeDB" or repo.parent.name != "Tools":
        return None
    workspace = repo.parent.parent
    if workspace.name != "TinyToolDevelopment":
        return None
    return workspace / "AKDB" / "export"


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
