from __future__ import annotations

import re

from architectural_knowledge_db.models import ChangeItemInput


class ImpactParseError(ValueError):
    """Raised when an Architektur-Impact bullet is ambiguous or invalid."""


_OPS = {"add", "modify", "supersede", "remove"}


def _target(value: str) -> tuple[str, str]:
    match = re.fullmatch(r"SAD:(\S+)\s+(decision|section)\s+(\S+)", value)
    if match:
        kind = "sad_decision" if match.group(2) == "decision" else "sad_section"
        return kind, f"{match.group(1)}:{match.group(3)}"
    if re.fullmatch(r"ADR-[A-Za-z0-9_.-]+(?:\s+\S.*)?", value):
        return "adr", value.split()[0]
    match = re.fullmatch(r"UML:element\s+(.+?)(?:\s+in\s+(\S+))?", value)
    if match:
        name, diagram = match.group(1), match.group(2)
        return "uml_element", f"{diagram}:{name}" if diagram else name
    match = re.fullmatch(r"UML:rel\s+(.+?)->(.+?)(?:\s+in\s+(\S+))?", value)
    if match:
        source, target, diagram = match.groups()
        rel = f"{source.strip()}->{target.strip()}"
        return "uml_relationship", f"{diagram}:{rel}" if diagram else rel
    match = re.fullmatch(r"rule\s+(.+)", value)
    if match:
        return "rule", match.group(1).strip()
    match = re.fullmatch(r"def\s+(.+)", value)
    if match:
        return "definition", match.group(1).strip()
    raise ImpactParseError(f"unknown or malformed impact target: {value}")


def parse_impact_section(markdown: str) -> list[ChangeItemInput]:
    lines = markdown.splitlines()
    start = next(
        (i + 1 for i, line in enumerate(lines) if re.fullmatch(r"##\s+Architektur-Impact\s*", line)),
        None,
    )
    if start is None:
        return []
    result: list[ChangeItemInput] = []
    for line in lines[start:]:
        if re.match(r"^#{1,6}\s+", line):
            break
        if not line.strip():
            continue
        if not re.match(r"^\s*-\s+", line):
            raise ImpactParseError(f"malformed impact line: {line}")
        body = re.sub(r"^\s*-\s+", "", line, count=1).strip()
        target_text, separator, note = body.partition("—")
        if not separator:
            target_text, separator, note = body.partition("â€”")
        parts = target_text.strip().split(maxsplit=1)
        if len(parts) != 2 or parts[0] not in _OPS:
            op = parts[0] if parts else ""
            raise ImpactParseError(f"unknown or malformed impact operation: {op}")
        kind, ref = _target(parts[1].strip())
        result.append(
            ChangeItemInput(
                op=parts[0],
                target_kind=kind,
                target_ref=ref,
                note=note.strip() or None,
            )
        )
    return result
