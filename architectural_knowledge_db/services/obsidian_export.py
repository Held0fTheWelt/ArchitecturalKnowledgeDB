"""Deterministic Obsidian vault renderer (derived notes; not a body_text round-trip).

Layout ``obsidian-vault`` export targets source their expected file map from this module.
AKDB never depends on Obsidian itself — this is a pure DB→markdown projection.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

# Characters illegal / ambiguous in Obsidian note basenames.
_UNSAFE_NOTE_CHARS = re.compile(r"[]\[#|^\\/:]")


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
