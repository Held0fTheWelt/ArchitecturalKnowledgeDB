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
        )


def _truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


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
