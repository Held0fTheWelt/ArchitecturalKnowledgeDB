from __future__ import annotations

import hashlib
import re


def stable_uid(*parts: str) -> str:
    normalized = ":".join(_clean_part(part) for part in parts if part is not None)
    if len(normalized) <= 180:
        return normalized
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
    return f"{normalized[:140]}:{digest}"


def digest_uid(prefix: str, *parts: str) -> str:
    payload = "\x1f".join(parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def _clean_part(value: str) -> str:
    cleaned = re.sub(r"\s+", "-", str(value).strip())
    return cleaned.replace("/", "_").replace("\\", "_")
