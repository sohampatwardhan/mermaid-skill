"""Provision the pinned Mermaid 12.0.0 parse install once for the whole test session.

check.sh validates by parsing with the pinned mermaid@12.0.0 plus jsdom (and the optional
zenuml plugin), all under Node — no browser. The first check.sh call would otherwise install
that pin; doing it once here, before any test runs, keeps the parse-dependent tests fast and
race-free and points every check.sh subprocess at the one shared node_modules via
MERMAID_PARSE_NODE_MODULES. If MERMAID_PARSE_NODE_MODULES is already set (CI points it at its
pinned install), this does nothing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
CHECK = SKILL_DIR / "scripts" / "check.sh"
BASH = shutil.which("bash") or "/bin/bash"


def pytest_configure(config) -> None:
    if os.environ.get("MERMAID_PARSE_NODE_MODULES"):
        return
    if not (shutil.which("node") and shutil.which("npm")):
        return  # Parse-dependent tests skip themselves via HAVE_CLI.
    cache = Path(os.environ.get("MERMAID_PARSE_CACHE", Path.home() / ".cache" / "mermaid-parse-12.0.0"))
    modules = cache / "node_modules"
    os.environ["MERMAID_PARSE_CACHE"] = str(cache)
    if (modules / "mermaid").is_dir() and (modules / "jsdom").is_dir():
        os.environ["MERMAID_PARSE_NODE_MODULES"] = str(modules)
        return
    # Warm the cache with one check.sh run; it installs the pin, then every test reuses it.
    try:
        subprocess.run(
            [BASH, str(CHECK), "-c", "flowchart TD\n  A-->B"],
            capture_output=True, text=True, timeout=600,
        )
    except Exception:
        return
    if (modules / "mermaid").is_dir() and (modules / "jsdom").is_dir():
        os.environ["MERMAID_PARSE_NODE_MODULES"] = str(modules)
