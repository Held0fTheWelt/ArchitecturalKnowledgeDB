from __future__ import annotations

from pathlib import Path

from architectural_knowledge_db.config import self_export_target


def test_self_export_target_akdb_repo_defaults_to_docs_architecture(tmp_path: Path) -> None:
    repo = tmp_path / "TinyToolDevelopment" / "ArchitecturalKnowledgeDB"
    data = repo / ".akdb"
    data.mkdir(parents=True)
    database = data / "architectural_knowledge_db.sqlite"
    database.write_text("", encoding="utf-8")

    target = self_export_target(
        "architectural-knowledge-db",
        data_root=data,
        database_path=database,
    )

    assert target is not None
    assert target.as_posix().endswith("docs/architecture")
    assert target == (repo / "docs" / "architecture").resolve()


def test_self_export_target_old_tools_layout_is_not_active(tmp_path: Path) -> None:
    workspace = tmp_path / "TinyToolDevelopment"
    repo = workspace / "Tools" / "ArchitecturalKnowledgeDB"
    data = repo / ".akdb"
    data.mkdir(parents=True)
    database = data / "architectural_knowledge_db.sqlite"
    database.write_text("", encoding="utf-8")

    assert (
        self_export_target(
            "architectural-knowledge-db",
            data_root=data,
            database_path=database,
        )
        is None
    )


def test_self_export_target_other_project_skips_akdb_repo_docs(tmp_path: Path) -> None:
    repo = tmp_path / "TinyToolDevelopment" / "ArchitecturalKnowledgeDB"
    data = repo / ".akdb"
    data.mkdir(parents=True)
    database = data / "architectural_knowledge_db.sqlite"
    database.write_text("", encoding="utf-8")

    assert (
        self_export_target(
            "other-project",
            data_root=data,
            database_path=database,
        )
        is None
    )
