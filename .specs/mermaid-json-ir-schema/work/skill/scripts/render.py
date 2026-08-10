#!/usr/bin/env python3
"""Compatibility facade for strict canonical and documented flat legacy Mermaid JSON IR."""

import argparse
import json
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from scripts.mermaid_ir.compiler import compile_ir
from scripts.mermaid_ir.legacy_serializers import render_graph_c4
from scripts.mermaid_ir.model import IRError
from scripts.mermaid_ir.targets import register_all


def render(ir: dict, target: str | None = None, backend: str = "mermaid") -> str:
    """Return deterministic Mermaid source while preserving documented legacy inputs."""

    if ("schemaVersion" not in ir and target in {"C4Context", "C4Container"}
            and ir.get("target") in {"C4Context", "C4Container"} and target != ir.get("target")):
        if backend != "mermaid":
            raise IRError(f"unsupported backend {backend!r}")
        return render_graph_c4(ir)
    register_all()
    return compile_ir(ir, target, backend).source


def main(argv: list[str] | None = None) -> int:
    from scripts.mermaid_ir.cli import main as cli_main
    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
