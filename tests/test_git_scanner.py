from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from architectural_knowledge_db.models import ProjectUpsert, RepositoryRegistration
from architectural_knowledge_db.services.git_scanner import GitScanner, should_store_path
from architectural_knowledge_db.services.projects import ProjectService
from architectural_knowledge_db.services.repositories import RepositoryService, resolve_local_path_alias, sanitize_remote_url


pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git executable is required")


def test_sanitize_remote_url_removes_credentials() -> None:
    assert (
        sanitize_remote_url("https://user:secret@example.com/org/repo.git")
        == "https://example.com/org/repo.git"
    )


def test_git_scanner_stores_selected_metadata_without_email_or_git_internals(conn, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Example User")
    git(repo, "config", "user.email", "user@example.com")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    git(repo, "add", "src/app.py")
    git(repo, "commit", "-m", "Add app")
    (repo / "src" / "app.py").write_text("print('hello again')\n", encoding="utf-8")
    git(repo, "commit", "-am", "Update app")

    ProjectService(conn).upsert_project(ProjectUpsert(project_id="akdb", display_name="AKDB"))
    RepositoryService(conn).register_repository(
        "akdb",
        RepositoryRegistration(
            repository_id="akdb-main",
            local_path=str(repo),
            remote_url_sanitized="https://user:secret@example.com/org/repo.git",
            include_patterns=["src/**"],
        ),
    )

    result = GitScanner(conn).scan_project("akdb", max_commits=10)

    assert result["repositories"][0]["status"] == "ok"
    assert result["repositories"][0]["commits_scanned"] == 2
    assert conn.execute("SELECT COUNT(*) AS count FROM git_commit_files").fetchone()["count"] == 2
    assert conn.execute("SELECT author_email_hash FROM git_commits LIMIT 1").fetchone()["author_email_hash"] is None
    assert conn.execute("SELECT COUNT(*) AS count FROM git_commit_files WHERE file_path LIKE '.git%'").fetchone()[
        "count"
    ] == 0
    assert conn.execute("SELECT change_count FROM git_file_history WHERE file_path = 'src/app.py'").fetchone()[
        "change_count"
    ] == 2


def test_git_path_filter_never_stores_git_internals() -> None:
    assert should_store_path(".git/config", include_patterns=[], exclude_patterns=[]) is False
    assert should_store_path("src/app.py", include_patterns=["src/**"], exclude_patterns=[]) is True


def test_sources_alias_resolves_against_configured_source_root(monkeypatch, tmp_path: Path) -> None:
    source_root = tmp_path / "sources"
    repo = source_root / "Git" / "docs"
    repo.mkdir(parents=True)
    monkeypatch.setenv("AKDB_SOURCE_ROOT", str(source_root))

    assert Path(resolve_local_path_alias("/sources/Git/docs")) == repo


def git(repo: Path, *args: str) -> None:
    completed = subprocess.run(["git", "-C", str(repo), *args], check=False, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
