"""Pure orchestration from legacy or canonical JSON to deterministic Mermaid source."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .diagnostics import sort_diagnostics
from .config import effective_configuration
from .migrate import get_target_spec, set_target_lookup
from .model import CompileResult, Diagnostic, IRError
from .normalize import normalize
from .schema_runtime import SchemaRegistry, validate_schema


def _set_target_lookup(provider: Callable[[str], Any | None]) -> None:
    """Bind the target provider used by scaffolding tests and, later, the production registry."""

    set_target_lookup(provider)


def compile_ir(
    ir: dict[str, Any],
    target: str | None = None,
    backend: str = "mermaid",
    *,
    deterministic: bool = True,
) -> CompileResult:
    """Compile one document without mutation, network access, or renderer invocation.

    Structural and semantic failures raise ``IRError`` before serialization, guaranteeing that
    callers never receive partial Mermaid source. ``deterministic=False`` only relaxes an explicit
    renderer conflict; it never changes statement ordering.
    """

    if backend != "mermaid":
        raise IRError(Diagnostic("compiler.backend", "/", f"unsupported backend {backend!r}"))
    normalized = normalize(ir, target)
    spec = get_target_spec(normalized["target"])
    if spec is None:
        raise IRError(Diagnostic("schema.target", "/target", f"unsupported target {normalized['target']!r}"))
    registry = getattr(spec, "schema_registry", None) or SchemaRegistry(Path(__file__).resolve().parents[2] / "schema")
    structural = validate_schema(normalized, spec.schema, registry)
    if structural:
        raise IRError(structural)
    semantic = sort_diagnostics(spec.validate_semantics(normalized))
    if semantic:
        raise IRError(semantic)
    renderer = normalized.get("renderer", {})
    if deterministic and renderer.get("deterministic") is False:
        raise IRError(Diagnostic("determinism.conflict", "/renderer/deterministic", "deterministic compilation rejects false"))
    effective = effective_configuration(normalized)
    normalized["renderer"] = {**renderer, "mermaidVersion": effective["mermaidVersion"],
                              "frontmatter": effective["frontmatter"],
                              "initialize": effective["initialize"]}
    source = spec.serialize(normalized)
    return CompileResult(
        normalized=normalized,
        source=source,
        initialize_config=effective["initialize"],
        mermaid_version=effective["mermaidVersion"],
        diagnostics=(),
    )
