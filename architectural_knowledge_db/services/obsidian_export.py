"""Deterministic Obsidian vault renderer (derived notes; not a body_text round-trip).

Layout ``obsidian-vault`` export targets source their expected file map from this module.
AKDB never depends on Obsidian itself — this is a pure DB→markdown projection.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Callable

import yaml

# Characters illegal / ambiguous in Obsidian note basenames.
_UNSAFE_NOTE_CHARS = re.compile(r"[]\[#|^\\/:]")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_FRONTMATTER_KEYS = ("kind", "status", "repo", "system", "source_key", "aliases", "tags", "links")


def _safe_base(title: str) -> str:
    cleaned = _UNSAFE_NOTE_CHARS.sub("", title or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or "untitled"


class ObsidianNameRegistry:
    """Allocate globally unique Obsidian note names (D4).

    First holder of a base slug keeps the bare name. Later collisions are
    qualified by a stable key (repo, then section_key) — never by insertion order
    alone: the qualifier is derived from the colliding item's repo/section.
    """

    def __init__(self) -> None:
        self._uid_to_name: dict[str, str] = {}
        self._taken: set[str] = set()
        self._base_holders: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def register(
        self,
        *,
        item_uid: str,
        item_type: str,
        title: str,
        repo: str,
        section_key: str | None,
    ) -> str:
        if item_uid in self._uid_to_name:
            return self._uid_to_name[item_uid]
        base = _safe_base(title)
        holder = {
            "item_uid": item_uid,
            "item_type": item_type,
            "title": title,
            "repo": repo or "",
            "section_key": section_key,
            "base": base,
        }
        holders = self._base_holders[base]
        holders.append(holder)
        if len(holders) == 1 and base not in self._taken:
            name = base
        else:
            name = self._qualified_name(holder)
            # If still taken (same repo/section as another), append uid.
            if name in self._taken:
                name = f"{name} · {item_uid}"
        self._uid_to_name[item_uid] = name
        self._taken.add(name)
        return name

    def resolve(self, item_uid: str) -> str | None:
        return self._uid_to_name.get(item_uid)

    def _qualified_name(self, holder: dict[str, Any]) -> str:
        repo = holder["repo"] or "unknown"
        sk = holder["section_key"]
        if sk:
            return f"{holder['base']} ({repo} · {sk})"
        return f"{holder['base']} ({repo})"


def build_frontmatter(
    *,
    kind: str,
    status: str | None,
    repo: str,
    system: str | None,
    source_key: str | None,
    aliases: list[str],
    tags: list[str],
    links: list[str],
) -> str:
    """Emit a deterministic YAML frontmatter block (D5).

    ``status`` is omitted entirely when ``None`` (presence-based kinds).
    ``links`` render as a YAML list of double-quoted ``"[[Name]]"`` strings.
    """
    payload: dict[str, Any] = {
        "kind": kind,
        "repo": repo,
        "system": system,
        "source_key": source_key,
        "aliases": list(aliases),
        "tags": list(tags),
        "links": list(links),
    }
    if status is not None:
        payload["status"] = status
    ordered: dict[str, Any] = {}
    for key in _FRONTMATTER_KEYS:
        if key == "status" and status is None:
            continue
        ordered[key] = payload[key]

    class _QuotedListDumper(yaml.SafeDumper):
        pass

    def _repr_str(dumper: yaml.Dumper, data: str) -> Any:
        # Force double quotes for wikilink strings; leave other scalars plain when safe.
        if data.startswith("[[") and data.endswith("]]"):
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')
        return dumper.represent_scalar("tag:yaml.org,2002:str", data)

    _QuotedListDumper.add_representer(str, _repr_str)
    body = yaml.dump(
        ordered,
        Dumper=_QuotedListDumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=10_000,
    )
    return f"---\n{body.rstrip()}\n---\n"


def rewrite_links(
    body_text: str,
    *,
    registry: ObsidianNameRegistry,
    resolve_target: Callable[[str], str | None],
) -> tuple[str, list[str]]:
    """Rewrite markdown links to Obsidian wikilinks; unresolved → plain text (§3.3).

    ``resolve_target(href)`` returns a note name (optionally ``#Heading``) or ``None``.
    Fragments are left for the resolver; callers may normalize via ``markdown_anchors``.
    """
    del registry  # reserved for future registry-assisted resolution
    unresolved: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        text, href = match.group(1), match.group(2)
        target = resolve_target(href)
        if target is None:
            unresolved.append(href)
            return text
        return f"[[{target}]]"

    rewritten = _MD_LINK_RE.sub(_replace, body_text)
    return rewritten, unresolved


def render_uml_note(item: dict[str, Any], *, registry: ObsidianNameRegistry) -> str:
    """Embed PlantUML source in a fenced ``plantuml`` block (D6)."""
    del registry
    metadata = item.get("metadata") or {}
    source = metadata.get("body_text") or ""
    # Guard against a source that already contains a closing fence.
    safe = source.replace("```", "'''")
    if not safe.endswith("\n"):
        safe = safe + "\n"
    return f"```plantuml\n{safe}```\n"
