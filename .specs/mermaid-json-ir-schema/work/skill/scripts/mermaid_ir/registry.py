"""Single dispatch registry for independently evolvable Mermaid target modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .compiler import _set_target_lookup
from .model import Diagnostic


@dataclass(frozen=True)
class TargetSpec:
    """Bind one target's schema, migration, validation, and serialization contracts.

    The canonical envelope is deliberately absent from registration so adding a target cannot
    mutate the version-one document boundary.
    """

    target: str
    family: str
    schema: dict[str, Any] | str
    legacy_fields: frozenset[str]
    migrate_legacy_content: Callable[[dict[str, Any]], dict[str, Any]]
    validate_semantics: Callable[[dict[str, Any]], tuple[Diagnostic, ...] | list[Diagnostic]]
    serialize: Callable[[dict[str, Any]], str]
    coverage: tuple[dict[str, Any], ...] = ()
    config_namespace: str | None = None
    schema_registry: Any | None = field(default=None, compare=False)


TARGETS: dict[str, TargetSpec] = {}


def register_target(spec: TargetSpec) -> None:
    """Register a target exactly once so accidental replacement cannot change dispatch."""

    if spec.target in TARGETS:
        raise ValueError(f"target {spec.target!r} is already registered")
    TARGETS[spec.target] = spec


def get_target(target: str) -> TargetSpec | None:
    """Return a target contract without falling back to a similar diagram family."""

    return TARGETS.get(target)


def clear_targets() -> None:
    """Clear the registry for isolated tests; production initialization never calls this."""

    TARGETS.clear()


_set_target_lookup(get_target)
