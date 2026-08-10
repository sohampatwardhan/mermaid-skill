"""Validate and separate per-diagram Mermaid settings from host initialization settings."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from .model import Diagnostic, IRError

PINNED_MERMAID_VERSION = "11.16.1"
SECURE_FRONTMATTER_KEYS = frozenset({"secure", "securityLevel", "startOnLoad"})
TARGET_NAMESPACES = {
    "flowchart": "flowchart", "mindmap": "mindmap", "block": "block", "C4Context": "c4",
    "C4Container": "c4", "architecture-beta": "architecture", "erDiagram": "er",
    "classDiagram": "class", "gantt": "gantt", "stateDiagram-v2": "state",
    "sequenceDiagram": "sequence", "requirementDiagram": "requirement",
}
KNOWN_NAMESPACES = frozenset(TARGET_NAMESPACES.values())


def _validate_namespaces(config: dict[str, Any], target: str, pointer: str) -> None:
    selected = TARGET_NAMESPACES.get(target)
    for key in config:
        if key in KNOWN_NAMESPACES and key != selected:
            raise IRError(Diagnostic("config.namespace", f"{pointer}/{key}", f"namespace {key!r} does not apply to {target!r}"))


def effective_configuration(document: dict[str, Any]) -> dict[str, Any]:
    """Return deterministic frontmatter and initialization dictionaries without mutation.

    A content-derived seed makes SVG identifier generation reproducible across processes. Secure
    host settings are excluded from diagram frontmatter because embedding policy must retain them.
    """

    renderer = copy.deepcopy(document.get("renderer", {}))
    version = renderer.get("mermaidVersion", PINNED_MERMAID_VERSION)
    if version != PINNED_MERMAID_VERSION:
        raise IRError(Diagnostic("config.version", "/renderer/mermaidVersion", f"expected Mermaid {PINNED_MERMAID_VERSION}, got {version}"))
    if renderer.get("deterministic", True) is False:
        raise IRError(Diagnostic("determinism.conflict", "/renderer/deterministic", "deterministic mode rejects false"))
    frontmatter = copy.deepcopy(renderer.get("frontmatter", {}))
    frontmatter_config = frontmatter.get("config", {})
    for key in SECURE_FRONTMATTER_KEYS & set(frontmatter_config):
        raise IRError(Diagnostic("config.secure", f"/renderer/frontmatter/config/{key}", "secure host setting is forbidden in diagram frontmatter"))
    target = document.get("target", "")
    _validate_namespaces(frontmatter_config, target, "/renderer/frontmatter/config")
    initialize = copy.deepcopy(renderer.get("initialize", {}))
    _validate_namespaces(initialize, target, "/renderer/initialize")
    if initialize.get("deterministicIds") is False:
        raise IRError(Diagnostic("determinism.conflict", "/renderer/initialize/deterministicIds", "deterministic IDs cannot be disabled"))
    initialize["deterministicIds"] = True
    if "deterministicIDSeed" not in initialize:
        canonical_content = json.dumps(document.get("content", {}), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        initialize["deterministicIDSeed"] = hashlib.sha256(canonical_content.encode("utf-8")).hexdigest()
    return {"frontmatter": frontmatter, "initialize": initialize, "mermaidVersion": version}
