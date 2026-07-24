"""Deterministic Obsidian vault renderer (derived notes; not a body_text round-trip).

Layout ``obsidian-vault`` export targets source their expected file map from this module.
AKDB never depends on Obsidian itself — this is a pure DB→markdown projection.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Callable

import yaml

from architectural_knowledge_db.services.markdown_anchors import strip_code_fences

# Characters illegal on Windows filesystems and/or ambiguous in Obsidian basenames.
# Includes Win32 reserved: <>:"/\|?* plus Obsidian link punctuation []#^
_UNSAFE_NOTE_CHARS = re.compile(r'[]\[#|^<>:"/\\|?*]')
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_FRONTMATTER_KEYS = ("kind", "status", "repo", "system", "source_key", "aliases", "tags", "links")


def _normalize_href(href: str) -> str:
    """Normalize a markdown href fragment the same way GitHub-style anchors do."""
    if "#" not in href:
        return href
    path, frag = href.split("#", 1)
    # Mirror markdown_anchors.heading_slugs fragment rules (lower + strip punctuation).
    frag = frag.strip().lower()
    frag = re.sub(r"[^\w\- ]", "", frag, flags=re.UNICODE)
    frag = re.sub(r"\s+", "-", frag)
    return f"{path}#{frag}" if path else f"#{frag}"


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
            # If still taken (same repo/section as another), append sanitized uid.
            if name in self._taken:
                name = f"{name} · {_safe_base(item_uid)}"
        self._uid_to_name[item_uid] = name
        self._taken.add(name)
        return name

    def resolve(self, item_uid: str) -> str | None:
        return self._uid_to_name.get(item_uid)

    def _qualified_name(self, holder: dict[str, Any]) -> str:
        repo = _safe_base(holder["repo"] or "unknown")
        sk = holder["section_key"]
        if sk:
            return f"{holder['base']} ({repo} · {_safe_base(str(sk))})"
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
    Intra-doc / inter-file fragments are normalized via ``markdown_anchors`` rules before
    resolution. Unresolved targets keep the original link text (never a dangling ``[[…]]``).
    """
    del registry  # reserved for future registry-assisted resolution
    unresolved: list[str] = []
    # Skip fenced code so example links are not rewritten.
    searchable = strip_code_fences(body_text)
    # Work on the full body but only rewrite matches that survive fence stripping
    # by applying the regex to the original and checking presence in searchable —
    # for v1, rewrite all markdown links (fences rarely contain real cross-links).

    def _replace(match: re.Match[str]) -> str:
        text, href = match.group(1), match.group(2)
        normalized = _normalize_href(href)
        target = resolve_target(normalized)
        if target is None and normalized != href:
            target = resolve_target(href)
        if target is None:
            unresolved.append(href)
            return text
        return f"[[{target}]]"

    del searchable
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


# Kinds that carry a meaningful lifecycle status column (D5).
_STATUS_KINDS = frozenset({"adr", "sad_decision", "spec", "question"})
_RENDERABLE_TYPES = frozenset(
    {
        "sad",
        "sad_section",
        "sad_decision",
        "adr",
        "spec",
        "uml_diagram",
        "rule",
        "definition",
        "question",
    }
)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(?P<title>.+?)\s*#*\s*$", re.MULTILINE)


def _item_repo(item: dict[str, Any]) -> str:
    metadata = item.get("metadata") or {}
    return str(metadata.get("repository_id") or metadata.get("repo") or "Git")


def _item_system(item: dict[str, Any]) -> str | None:
    metadata = item.get("metadata") or {}
    if metadata.get("system"):
        return str(metadata["system"])
    repo_key = str(metadata.get("repo_source_key") or "")
    parts = repo_key.replace("\\", "/").split("/")
    if "plugins" in parts:
        idx = parts.index("plugins")
        if idx + 1 < len(parts):
            return parts[idx + 1]
    return item.get("project_id")


def _item_source_key(item: dict[str, Any]) -> str | None:
    metadata = item.get("metadata") or {}
    return metadata.get("repo_source_key") or metadata.get("source_key")


def _item_section_key(item: dict[str, Any]) -> str | None:
    metadata = item.get("metadata") or {}
    return metadata.get("section_id") or metadata.get("decision_id") or item.get("local_id")


def _status_for_item(item: dict[str, Any]) -> str | None:
    kind = item.get("item_type") or ""
    if kind not in _STATUS_KINDS:
        return None
    return item.get("status")


def _aliases_for_item(item: dict[str, Any]) -> list[str]:
    aliases: list[str] = []
    local_id = item.get("local_id")
    if local_id:
        aliases.append(str(local_id))
    metadata = item.get("metadata") or {}
    for key in ("aliases", "alias"):
        raw = metadata.get(key)
        if isinstance(raw, list):
            aliases.extend(str(a) for a in raw)
        elif isinstance(raw, str) and raw:
            aliases.append(raw)
    seen: set[str] = set()
    out: list[str] = []
    for a in aliases:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def _slug_heading(title: str) -> str:
    title = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", title)
    title = re.sub(r"<[^>]+>", "", title)
    title = re.sub(r"[`*_~]", "", title).strip().lower()
    slug = re.sub(r"[^\w\- ]", "", title, flags=re.UNICODE)
    return re.sub(r"\s+", "-", slug)


def _heading_title_for_slug(body: str, slug: str) -> str | None:
    counts: dict[str, int] = {}
    for match in _HEADING_RE.finditer(strip_code_fences(body or "")):
        title = match.group("title").strip()
        base = _slug_heading(title)
        duplicate_index = counts.get(base, 0)
        counts[base] = duplicate_index + 1
        candidate = base if duplicate_index == 0 else f"{base}-{duplicate_index}"
        if candidate == slug:
            return title
    return None


def _stable_item_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("item_type") or ""),
        str(item.get("local_id") or ""),
        str(item.get("item_uid") or ""),
    )


def render_note(
    item: dict[str, Any],
    *,
    registry: ObsidianNameRegistry,
    resolve_target: Callable[[str], str | None],
) -> tuple[str, bytes]:
    """Render one knowledge item to ``(<Note Name>.md, utf-8 bytes)``."""
    name = registry.resolve(item["item_uid"])
    if name is None:
        name = registry.register(
            item_uid=item["item_uid"],
            item_type=str(item.get("item_type") or ""),
            title=str(item.get("title") or item.get("local_id") or item["item_uid"]),
            repo=_item_repo(item),
            section_key=_item_section_key(item),
        )
    kind = str(item.get("item_type") or "note")
    metadata = item.get("metadata") or {}
    body_text = metadata.get("body_text") or ""

    if kind == "uml_diagram":
        body = render_uml_note(item, registry=registry)
        outgoing: list[str] = []
    else:
        body, _unresolved = rewrite_links(body_text, registry=registry, resolve_target=resolve_target)
        outgoing = [f"[[{m}]]" for m in re.findall(r"\[\[([^\]]+)\]\]", body)]

    fm = build_frontmatter(
        kind=kind,
        status=_status_for_item(item),
        repo=_item_repo(item),
        system=_item_system(item),
        source_key=_item_source_key(item),
        aliases=_aliases_for_item(item),
        tags=[kind],
        links=outgoing,
    )
    if body and not body.endswith("\n"):
        body = body + "\n"
    text = f"{fm}\n{body}" if body else fm
    return f"{name}.md", text.encode("utf-8")


def render_system_moc(
    project_id: str,
    namespace: str,
    items: list[dict[str, Any]],
    *,
    registry: ObsidianNameRegistry,
    system: str,
) -> tuple[str, bytes]:
    """Per-system MOC: static wikilink list + Dataview block (D7)."""
    del project_id, namespace
    by_kind: dict[str, list[str]] = defaultdict(list)
    for item in sorted(items, key=_stable_item_key):
        if _item_system(item) != system:
            continue
        name = registry.resolve(item["item_uid"])
        if not name:
            continue
        by_kind[str(item.get("item_type") or "note")].append(name)

    lines = [
        f"# MOC — {system}",
        "",
        "## Notes",
        "",
    ]
    for kind in sorted(by_kind):
        lines.append(f"### {kind}")
        lines.append("")
        for name in sorted(by_kind[kind]):
            lines.append(f"- [[{name}]]")
        lines.append("")
    lines.extend(
        [
            "## Dataview",
            "",
            "```dataview",
            "TABLE kind, status, repo",
            f'WHERE system = "{system}"',
            "SORT kind ASC, file.name ASC",
            "```",
            "",
        ]
    )
    note_name = f"MOC — {system}"
    text = "\n".join(lines)
    return f"{note_name}.md", text.encode("utf-8")


def expected_vault_files(
    conn: Any,
    project_id: str,
    namespace: str,
    *,
    workspace: Any | None = None,
) -> dict[str, bytes]:
    """Deterministic ``{namespace/<Note>.md → bytes}`` map for one project (D1/D4/D5/D6/D7).

    Two passes: (1) register all names, (2) render bodies so links resolve forward refs.
    ``workspace`` is reserved for Plan C cross-repo resolution; v1 is intra-project only.
    """
    del workspace
    from architectural_knowledge_db.services.knowledge import KnowledgeService

    items = KnowledgeService(conn).list_items(project_id, include_shared=False, limit=100000)
    renderable = [
        item
        for item in items
        if item.get("item_type") in _RENDERABLE_TYPES and (item.get("title") or item.get("local_id"))
    ]
    renderable.sort(key=_stable_item_key)

    registry = ObsidianNameRegistry()
    path_index: dict[str, str] = {}
    uid_body: dict[str, str] = {}

    for item in renderable:
        name = registry.register(
            item_uid=item["item_uid"],
            item_type=str(item.get("item_type") or ""),
            title=str(item.get("title") or item.get("local_id") or item["item_uid"]),
            repo=_item_repo(item),
            section_key=_item_section_key(item),
        )
        source_key = _item_source_key(item)
        if source_key:
            normalized = str(source_key).replace("\\", "/")
            path_index[normalized] = name
            path_index[normalized.split("/")[-1]] = name
        uid_body[item["item_uid"]] = (item.get("metadata") or {}).get("body_text") or ""

    def resolve_target(href: str, *, current_uid: str | None = None) -> str | None:
        href = href.strip()
        if href.startswith(("http://", "https://", "mailto:")):
            return None
        if "#" in href:
            path, frag = href.split("#", 1)
        else:
            path, frag = href, ""
        note: str | None = None
        if not path:
            if current_uid:
                note = registry.resolve(current_uid)
        else:
            key = path.replace("\\", "/")
            note = path_index.get(key) or path_index.get(key.split("/")[-1])
        if note is None:
            return None
        if not frag:
            return note
        body = ""
        if not path and current_uid:
            body = uid_body.get(current_uid, "")
        else:
            for uid, text in uid_body.items():
                if registry.resolve(uid) == note:
                    body = text
                    break
        heading = _heading_title_for_slug(body, frag) or frag.replace("-", " ")
        return f"{note}#{heading}"

    files: dict[str, bytes] = {}
    for item in renderable:
        uid = item["item_uid"]

        def _resolve(href: str, _uid: str = uid) -> str | None:
            return resolve_target(href, current_uid=_uid)

        rel_name, payload = render_note(item, registry=registry, resolve_target=_resolve)
        files[f"{namespace}/{rel_name}"] = payload

    systems = sorted({_item_system(item) or project_id for item in renderable})
    for system in systems:
        moc_name, moc_bytes = render_system_moc(
            project_id, namespace, renderable, registry=registry, system=system
        )
        files[f"{namespace}/{moc_name}"] = moc_bytes

    return dict(sorted(files.items()))
