"""Atomic command-line adapters for validation, normalization, source, and host configuration."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from .compiler import compile_ir
from .model import IRError
from .targets import register_all


def _atomic_write(path: Path, value: str) -> None:
    """Replace one output only after its complete content is durable in the same directory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try: os.unlink(temporary)
        except FileNotFoundError: pass
        raise


def main(argv: list[str] | None = None) -> int:
    """Return 0 on success, 1 for IR rejection, or 2 for invocation/I/O failures."""

    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, nargs="?")
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--target")
    parser.add_argument("--backend", default="mermaid")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--normalize-out", type=Path)
    parser.add_argument("--initialize-config-out", type=Path)
    parser.add_argument("--allow-nondeterministic", action="store_true")
    parser.add_argument("--list-targets", action="store_true")
    parser.add_argument("--example", metavar="TARGET")
    parser.add_argument("--example-kind", choices=("minimal", "maximal"), default="maximal")
    parser.add_argument("--diagnostics-format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    register_all()
    if args.list_targets:
        from .registry import TARGETS
        print("\n".join(sorted(TARGETS)))
        return 0
    if args.example:
        if args.input is not None:
            parser.error("INPUT and --example are mutually exclusive")
        example = Path(__file__).resolve().parents[2] / "examples" / args.example / f"{args.example_kind}.json"
        if not example.is_file():
            from .registry import TARGETS
            print(f"ERROR: no example for {args.example!r}; known targets: {', '.join(sorted(TARGETS))}", file=sys.stderr)
            return 2
        value = example.read_text(encoding="utf-8")
        if args.output: _atomic_write(args.output, value)
        else: sys.stdout.write(value)
        return 0
    if args.input is None:
        parser.error("INPUT is required unless --list-targets or --example is used")
    try:
        document = json.loads(args.input.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr); return 2
    try:
        result = compile_ir(document, args.target, args.backend,
                            deterministic=not args.allow_nondeterministic)
        if args.normalize_out:
            _atomic_write(args.normalize_out, json.dumps(result.normalized, indent=2, sort_keys=True) + "\n")
        if args.initialize_config_out:
            _atomic_write(args.initialize_config_out, json.dumps(result.initialize_config, indent=2, sort_keys=True) + "\n")
        if not args.validate_only:
            if args.output: _atomic_write(args.output, result.source)
            else: sys.stdout.write(result.source)
        return 0
    except IRError as exc:
        if args.diagnostics_format == "json":
            print(json.dumps({"ok": False, "diagnostics": [
                {"code": item.code, "pointer": item.pointer or "/", "message": item.message,
                 "relatedPointers": list(item.related_pointers)} for item in exc.diagnostics
            ]}, sort_keys=True), file=sys.stderr)
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr); return 2
