"""Compile versioned Mermaid JSON IR without network or renderer side effects.

The package keeps canonicalization and source generation pure so callers can validate,
cache, and audit structured diagrams before invoking an external Mermaid renderer.
"""

from .model import CompileResult, Diagnostic, IRError

__all__ = ["CompileResult", "Diagnostic", "IRError"]
