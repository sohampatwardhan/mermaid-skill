"""RFC 6901 pointer and deterministic diagnostic-order helpers."""

from __future__ import annotations

from collections.abc import Iterable

from .model import Diagnostic


def escape_pointer_token(token: object) -> str:
    """Escape one reference token so arbitrary JSON keys remain unambiguous in diagnostics."""

    return str(token).replace("~", "~0").replace("/", "~1")


def join_pointer(pointer: str, token: object) -> str:
    """Append a token to an absolute JSON Pointer, including the root pointer ``""``."""

    return f"{pointer}/{escape_pointer_token(token)}"


def sort_diagnostics(values: Iterable[Diagnostic]) -> tuple[Diagnostic, ...]:
    """Return diagnostics in the public stable order required for reproducible automation."""

    return tuple(sorted(values, key=lambda item: (item.pointer, item.code, item.message)))
