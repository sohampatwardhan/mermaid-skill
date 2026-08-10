"""Stable public result and error models for the Mermaid IR compiler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Diagnostic:
    """Describe one actionable failure at a canonical JSON Pointer.

    Related pointers identify conflicting declarations without forcing callers to parse
    prose. Codes are stable machine-facing categories; messages remain human-facing.
    """

    code: str
    pointer: str
    message: str
    related_pointers: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompileResult:
    """Return every deterministic artifact produced by successful compilation.

    Initialization configuration stays separate because it belongs to the embedding host,
    while ``source`` contains only the current diagram's Mermaid document.
    """

    normalized: dict[str, Any]
    source: str
    initialize_config: dict[str, Any]
    mermaid_version: str
    diagnostics: tuple[Diagnostic, ...] = ()


class IRError(ValueError):
    """Fail compilation while preserving structured diagnostics for programmatic callers."""

    def __init__(self, diagnostics: tuple[Diagnostic, ...] | list[Diagnostic] | Diagnostic | str):
        if isinstance(diagnostics, str):
            normalized = (Diagnostic("ir.error", "", diagnostics),)
        elif isinstance(diagnostics, Diagnostic):
            normalized = (diagnostics,)
        else:
            normalized = tuple(diagnostics)
        self.diagnostics = normalized
        super().__init__(self._format())

    def _format(self) -> str:
        return "\n".join(
            f"{item.code} {item.pointer or '/'}: {item.message}" for item in self.diagnostics
        )
