"""Deterministic, context-aware primitives shared by Mermaid target serializers."""

from __future__ import annotations

import json
import re
from typing import Any


class IdentifierTable:
    """Map arbitrary JSON IDs to stable collision-free Mermaid bare identifiers."""

    def __init__(self) -> None:
        self._by_raw: dict[str, str] = {}
        self._used: set[str] = set()

    def safe(self, raw: object) -> str:
        """Return the same safe identifier for repeated values and suffix collisions stably."""

        text = str(raw)
        if text in self._by_raw:
            return self._by_raw[text]
        candidate = text if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", text) else "n_" + re.sub(r"[^A-Za-z0-9_]", "_", text)
        if not re.match(r"[A-Za-z_]", candidate):
            candidate = "n_" + candidate
        base = candidate
        suffix = 0
        while candidate in self._used:
            suffix += 1
            candidate = f"{base}_{suffix}"
        self._by_raw[text] = candidate
        self._used.add(candidate)
        return candidate


def clean_text(value: Any) -> str:
    """Flatten line breaks and escape quotes for Mermaid label contexts."""

    return str(value).replace("\r\n", " ").replace("\r", " ").replace("\n", " ").replace('"', "#quot;")


def quote_text(value: Any) -> str:
    """Return a double-quoted Mermaid label with deterministic context escaping."""

    return f'"{clean_text(value)}"'


def canonical_json(value: Any) -> str:
    """Encode JSON flow values with lexical keys and no whitespace for stable frontmatter."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def emit_preamble(document: dict[str, Any], declaration: str) -> list[str]:
    """Emit frontmatter, declaration, accessibility, and title in the mandated source order."""

    lines: list[str] = []
    config = document.get("renderer", {}).get("frontmatter", {}).get("config")
    if config:
        lines.extend(["---", f"config: {canonical_json(config)}", "---"])
    lines.append(declaration)
    accessibility = document.get("accessibility", {})
    if accessibility.get("title"):
        lines.append(f"accTitle: {clean_text(accessibility['title'])}")
    if accessibility.get("description"):
        lines.append(f"accDescr: {clean_text(accessibility['description'])}")
    title = document.get("source", {}).get("title")
    if title:
        lines.append(f"title {clean_text(title)}")
    return lines


def merge_preamble(document: dict[str, Any], legacy_source: str) -> str:
    """Add canonical cross-cutting statements to a proven target serializer result.

    The former serializer owns declaration and target body syntax; this helper replaces only
    its first line with the ordered canonical preamble, preserving byte-stable body behavior.
    """

    lines = legacy_source.rstrip("\n").splitlines()
    if not lines:
        raise ValueError("target serializer returned empty Mermaid source")
    return "\n".join(emit_preamble(document, lines[0]) + lines[1:]) + "\n"
