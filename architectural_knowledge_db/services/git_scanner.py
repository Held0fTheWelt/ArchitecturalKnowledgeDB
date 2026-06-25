from __future__ import annotations

import hashlib
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from architectural_knowledge_db.config import Settings
from architectural_knowledge_db.ids import digest_uid, stable_uid
from architectural_knowledge_db.services.jsonutil import dumps
from architectural_knowledge_db.services.knowledge import normalize_path, path_matches
from architectural_knowledge_db.services.repositories import RepositoryService


@dataclass
class ChangedFile:
    path: str
    change_type: str
    previous_path: str | None = None


@dataclass
class CommitRecord:
    commit_hash: str
    short_hash: str
    committed_at: str
    author_name: str | None
    author_email: str | None
    parents: list[str]
    message_subject: str
    changed_files: list[ChangedFile] = field(default_factory=list)


class GitScanner:
    def __init__(self, conn: sqlite3.Connection, settings: Settings | None = None):
        self.conn = conn
        self.settings = settings or Settings.from_env()
        self.repositories = RepositoryService(conn)

    def scan_project(self, project_id: str, max_commits: int = 500) -> dict[str, Any]:
        repositories = self.repositories.list_repositories(project_id)
        results = []
        for repository in repositories:
            results.append(self.scan_repository(project_id, repository["repository_id"], max_commits=max_commits))
        return {"project_id": project_id, "repositories": results}

    def scan_repository(self, project_id: str, repository_id: str, max_commits: int = 500) -> dict[str, Any]:
        repository = self.repositories.get_repository(project_id, repository_id)
        repo_path = Path(repository["local_path"])
        if not is_git_worktree(repo_path):
            self.repositories.mark_scan_status(repository_id, "not_a_git_repository")
            return {
                "repository_id": repository_id,
                "status": "not_a_git_repository",
                "commits_scanned": 0,
                "files_scanned": 0,
            }

        commits = read_git_log(repo_path, max_commits=max_commits)
        stored_commits = 0
        stored_files = 0
        for commit in commits:
            changed_files = [
                changed
                for changed in commit.changed_files
                if should_store_path(
                    changed.path,
                    include_patterns=repository["include_patterns"],
                    exclude_patterns=repository["exclude_patterns"],
                )
            ]
            if not changed_files:
                continue
            commit_uid = stable_uid(repository_id, "commit", commit.commit_hash)
            self.conn.execute(
                """
                INSERT INTO git_commits(
                  commit_uid, repository_id, project_id, commit_hash, short_hash, committed_at,
                  author_name, author_email_hash, message_subject, message_body, is_merge, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(repository_id, commit_hash) DO UPDATE SET
                  short_hash = excluded.short_hash,
                  committed_at = excluded.committed_at,
                  author_name = excluded.author_name,
                  author_email_hash = excluded.author_email_hash,
                  message_subject = excluded.message_subject,
                  message_body = excluded.message_body,
                  is_merge = excluded.is_merge,
                  metadata_json = excluded.metadata_json
                """,
                (
                    commit_uid,
                    repository_id,
                    project_id,
                    commit.commit_hash,
                    commit.short_hash,
                    commit.committed_at,
                    commit.author_name,
                    hash_email(commit.author_email) if self.settings.store_author_email_hash else None,
                    commit.message_subject,
                    None,
                    1 if len(commit.parents) > 1 else 0,
                    dumps({"parent_count": len(commit.parents)}),
                ),
            )
            self.conn.execute("DELETE FROM git_commit_files WHERE commit_uid = ?", (commit_uid,))
            stored_commits += 1
            for changed in changed_files:
                commit_file_uid = digest_uid("commit_file", repository_id, commit.commit_hash, changed.path)
                self.conn.execute(
                    """
                    INSERT INTO git_commit_files(
                      commit_file_uid, commit_uid, repository_id, project_id, file_path,
                      previous_path, change_type, metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        commit_file_uid,
                        commit_uid,
                        repository_id,
                        project_id,
                        changed.path,
                        changed.previous_path,
                        changed.change_type,
                        dumps({}),
                    ),
                )
                stored_files += 1

        file_history_count = self.rebuild_file_history(project_id, repository_id)
        inferred_links = self.infer_cochange_links(project_id, repository_id)
        self.repositories.mark_scan_status(repository_id, "ok")
        return {
            "repository_id": repository_id,
            "status": "ok",
            "commits_scanned": stored_commits,
            "changed_files_scanned": stored_files,
            "file_history_entries": file_history_count,
            "inferred_links": inferred_links,
        }

    def rebuild_file_history(self, project_id: str, repository_id: str) -> int:
        rows = self.conn.execute(
            """
            SELECT f.file_path, c.commit_hash, c.committed_at
            FROM git_commit_files f
            JOIN git_commits c ON c.commit_uid = f.commit_uid
            WHERE f.project_id = ? AND f.repository_id = ?
            ORDER BY c.committed_at ASC
            """,
            (project_id, repository_id),
        ).fetchall()
        history: dict[str, dict[str, Any]] = {}
        for row in rows:
            file_path = row["file_path"]
            entry = history.setdefault(
                file_path,
                {
                    "file_path": file_path,
                    "first_seen_commit_hash": row["commit_hash"],
                    "first_seen_at": row["committed_at"],
                    "last_changed_commit_hash": row["commit_hash"],
                    "last_changed_at": row["committed_at"],
                    "change_count": 0,
                },
            )
            entry["last_changed_commit_hash"] = row["commit_hash"]
            entry["last_changed_at"] = row["committed_at"]
            entry["change_count"] += 1

        self.conn.execute(
            "DELETE FROM git_file_history WHERE project_id = ? AND repository_id = ?",
            (project_id, repository_id),
        )
        for entry in history.values():
            self.conn.execute(
                """
                INSERT INTO git_file_history(
                  file_history_uid, repository_id, project_id, file_path,
                  first_seen_commit_hash, first_seen_at,
                  last_changed_commit_hash, last_changed_at,
                  change_count, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stable_uid(repository_id, "file_history", entry["file_path"]),
                    repository_id,
                    project_id,
                    entry["file_path"],
                    entry["first_seen_commit_hash"],
                    entry["first_seen_at"],
                    entry["last_changed_commit_hash"],
                    entry["last_changed_at"],
                    entry["change_count"],
                    dumps({}),
                ),
            )
        return len(history)

    def infer_cochange_links(self, project_id: str, repository_id: str) -> int:
        knowledge_rows = self.conn.execute(
            """
            SELECT item_uid, source_uri
            FROM knowledge_items
            WHERE project_id = ?
              AND source_uri IS NOT NULL
            """,
            (project_id,),
        ).fetchall()
        source_by_path = {
            normalize_path(row["source_uri"]): row["item_uid"]
            for row in knowledge_rows
            if row["source_uri"]
        }
        if not source_by_path:
            return 0
        commit_rows = self.conn.execute(
            """
            SELECT commit_uid, commit_hash
            FROM git_commits
            WHERE project_id = ? AND repository_id = ?
            """,
            (project_id, repository_id),
        ).fetchall()
        created = 0
        for commit in commit_rows:
            files = [
                row["file_path"]
                for row in self.conn.execute(
                    """
                    SELECT file_path
                    FROM git_commit_files
                    WHERE project_id = ? AND repository_id = ? AND commit_uid = ?
                    """,
                    (project_id, repository_id, commit["commit_uid"]),
                ).fetchall()
            ]
            knowledge_items = []
            source_files = []
            for file_path in files:
                matched_uid = first_matching_source_uri(source_by_path, file_path)
                if matched_uid:
                    knowledge_items.append((matched_uid, file_path))
                elif not is_knowledge_file(file_path):
                    source_files.append(file_path)
            for item_uid, knowledge_file in knowledge_items:
                for source_file in source_files:
                    link_uid = digest_uid("link", project_id, item_uid, source_file, "git_cochange_inferred", commit["commit_hash"])
                    before = self.conn.total_changes
                    self.conn.execute(
                        """
                        INSERT INTO knowledge_links(
                          link_uid, project_id, source_item_uid, target_ref, link_type,
                          authority_level, confidence, evidence, metadata_json
                        )
                        VALUES (?, ?, ?, ?, 'git_cochange_inferred', 'git_provenance_evidence', 'medium', ?, ?)
                        ON CONFLICT(link_uid) DO NOTHING
                        """,
                        (
                            link_uid,
                            project_id,
                            item_uid,
                            source_file,
                            f"Commit {commit['commit_hash']} changed {knowledge_file} and {source_file}.",
                            dumps({"commit_hash": commit["commit_hash"], "knowledge_file": knowledge_file}),
                        ),
                    )
                    if self.conn.total_changes > before:
                        created += 1
        return created


def is_git_worktree(path: Path) -> bool:
    if not path.exists():
        return False
    completed = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    return completed.returncode == 0 and completed.stdout.strip() == "true"


def read_git_log(path: Path, max_commits: int) -> list[CommitRecord]:
    pretty = "%x1e%H%x1f%h%x1f%cI%x1f%an%x1f%ae%x1f%P%x1f%s"
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(path),
            "log",
            f"--max-count={max_commits}",
            "--date=iso-strict",
            f"--pretty=format:{pretty}",
            "--name-status",
            "--find-renames",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git log failed")
    return parse_git_log(completed.stdout)


def parse_git_log(output: str) -> list[CommitRecord]:
    commits: list[CommitRecord] = []
    for raw_record in output.split("\x1e"):
        raw_record = raw_record.strip("\n")
        if not raw_record.strip():
            continue
        lines = raw_record.splitlines()
        if not lines:
            continue
        fields = lines[0].split("\x1f", 6)
        if len(fields) != 7:
            continue
        commit_hash, short_hash, committed_at, author_name, author_email, parents, subject = fields
        changed_files = [parse_name_status(line) for line in lines[1:] if line.strip()]
        commits.append(
            CommitRecord(
                commit_hash=commit_hash,
                short_hash=short_hash,
                committed_at=committed_at,
                author_name=author_name or None,
                author_email=author_email or None,
                parents=[parent for parent in parents.split() if parent],
                message_subject=subject,
                changed_files=[changed for changed in changed_files if changed is not None],
            )
        )
    return commits


def parse_name_status(line: str) -> ChangedFile | None:
    parts = line.split("\t")
    if len(parts) < 2:
        return None
    status = parts[0]
    change_type = status_to_change_type(status)
    if status.startswith("R") or status.startswith("C"):
        if len(parts) < 3:
            return None
        previous_path = normalize_path(parts[1])
        path = normalize_path(parts[2])
        return ChangedFile(path=path, previous_path=previous_path, change_type=change_type)
    return ChangedFile(path=normalize_path(parts[1]), change_type=change_type)


def status_to_change_type(status: str) -> str:
    code = status[:1]
    return {
        "A": "added",
        "M": "modified",
        "D": "deleted",
        "R": "renamed",
        "C": "copied",
        "T": "modified",
    }.get(code, "unknown")


def should_store_path(path: str, include_patterns: list[str], exclude_patterns: list[str]) -> bool:
    normalized = normalize_path(path)
    if normalized == ".git" or normalized.startswith(".git/") or "/.git/" in normalized:
        return False
    if include_patterns and not any(path_matches(pattern, normalized) for pattern in include_patterns):
        return False
    if exclude_patterns and any(path_matches(pattern, normalized) for pattern in exclude_patterns):
        return False
    return True


def first_matching_source_uri(source_by_path: dict[str, str], file_path: str) -> str | None:
    normalized_file = normalize_path(file_path)
    for source_uri, item_uid in source_by_path.items():
        if source_uri.endswith(normalized_file):
            return item_uid
    return None


def is_knowledge_file(file_path: str) -> bool:
    return normalize_path(file_path).lower().endswith((".md", ".puml", ".yaml", ".yml", ".json"))


def hash_email(email: str | None) -> str | None:
    if not email:
        return None
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()
