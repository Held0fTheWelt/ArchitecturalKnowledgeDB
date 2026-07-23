"""GitHub-style Markdown heading-anchor slugging.

Verbatim port of `github_heading_slugs` (+ `HEADING_RE` / `HTML_ANCHOR_RE` /
`strip_code_fences`) from the PluginProject repo's link-check gate
(`Tools/Pipeline/adr_link_check/adr_link_check.py`). Keeping this identical is what
guarantees in-repo and cross-repo anchor resolution follow the same rules — proven by a
shared heading->slug parity fixture tested in both repos (AKDB `tests/services/test_workspace_scan.py`
and the gate's `tests/test_runner.py`, Workspace Resolution Phase A Task A2 / Phase B Task B2).
"""

from __future__ import annotations

import re

HEADING_RE = re.compile(r"^#{1,6}\s+(?P<title>.+?)\s*#*\s*$", re.MULTILINE)
HTML_ANCHOR_RE = re.compile(
    r"<(?:a\s+[^>]*(?:name|id)|[^>]+\s+id)=[\"'](?P<anchor>[^\"']+)[\"']", re.IGNORECASE
)


def strip_code_fences(text: str) -> str:
    return re.sub(r"```.*?```", "", text, flags=re.DOTALL)


def heading_slugs(text: str) -> set[str]:
    """Return GitHub-style heading ids, including deterministic duplicate suffixes."""
    searchable = strip_code_fences(text)
    counts: dict[str, int] = {}
    slugs: set[str] = set()
    for match in HEADING_RE.finditer(searchable):
        title = match.group("title")
        title = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", title)
        title = re.sub(r"<[^>]+>", "", title)
        title = re.sub(r"[`*_~]", "", title).strip().lower()
        slug = re.sub(r"[^\w\- ]", "", title, flags=re.UNICODE)
        slug = re.sub(r"\s+", "-", slug)
        duplicate_index = counts.get(slug, 0)
        counts[slug] = duplicate_index + 1
        slugs.add(slug if duplicate_index == 0 else f"{slug}-{duplicate_index}")
    slugs.update(match.group("anchor").lower() for match in HTML_ANCHOR_RE.finditer(searchable))
    return slugs
