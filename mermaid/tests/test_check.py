"""Tests for scripts/check.sh: CLI pin, line reporting, Markdown mode, determinism."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = SKILL_DIR.parent
CHECK = SKILL_DIR / "scripts" / "check.sh"
WORKFLOW = REPO_DIR / ".github" / "workflows" / "tests.yml"
BASH = shutil.which("bash") or "/bin/bash"

# Every external tool check.sh calls. A PATH made only of these has no mmdc and no npx.
TOOLS = ("mktemp", "rm", "cp", "cat", "sed", "tr", "grep", "awk", "head", "mkdir", "wc")

HAVE_CLI = bool(shutil.which("mmdc") or shutil.which("npx"))
needs_cli = pytest.mark.skipif(not HAVE_CLI, reason="needs Mermaid CLI 12.0.0 or npx")


def tools_dir(tmp_path: Path) -> Path:
    bindir = tmp_path / "tools"
    bindir.mkdir()
    for tool in TOOLS:
        found = shutil.which(tool)
        assert found, f"{tool} not on PATH"
        (bindir / tool).symlink_to(found)
    return bindir


def write_exe(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


def run_check(*args: str, env: dict | None = None, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BASH, str(CHECK), *args],
        capture_output=True, text=True, timeout=300, env=env, input=stdin,
    )


# --- 2.1 CLI selection ------------------------------------------------------------------


def test_other_mmdc_version_falls_back_to_pinned_npx(tmp_path: Path) -> None:
    fake = tmp_path / "fake"
    fake.mkdir()
    log = tmp_path / "npx.log"
    write_exe(fake / "mmdc", 'if [ "$1" = "--version" ]; then echo 11.16.0; exit 0; fi\nexit 99\n')
    write_exe(
        fake / "npx",
        f'echo "$@" >> "{log}"\n'
        'while [ $# -gt 0 ]; do if [ "$1" = "-o" ]; then out="$2"; fi; shift; done\n'
        'echo "<svg></svg>" > "$out"\n',
    )
    env = {**os.environ, "PATH": f"{fake}:{tools_dir(tmp_path)}"}
    env.pop("MERMAID_CLI_PACKAGE", None)
    result = run_check("-c", "flowchart TD\n  A-->B", env=env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "-y @mermaid-js/mermaid-cli@12.0.0" in log.read_text()
    # The download note goes to stderr so stdout stays clean for callers.
    assert "npx" in result.stderr
    assert "npx" not in result.stdout


def test_no_cli_exits_3_and_names_the_version(tmp_path: Path) -> None:
    env = {**os.environ, "PATH": str(tools_dir(tmp_path))}
    result = run_check("-c", "flowchart TD\n  A-->B", env=env)
    assert result.returncode == 3
    assert "need Mermaid CLI 12.0.0" in result.stdout


def test_pin_matches_workflow() -> None:
    script = CHECK.read_text()
    workflow = WORKFLOW.read_text()
    assert re.search(r'^REQUIRED_CLI_VERSION="12\.0\.0"$', script, re.M)
    assert "@mermaid-js/mermaid-cli@12.0.0" in workflow
    assert "mermaid@12.0.0" in workflow
    assert "v!=='12.0.0'" in workflow


@needs_cli
def test_identical_runs_give_identical_output() -> None:
    source = "flowchart TD\n  A --> B\n  B --> --> C\n"
    first = run_check("-c", source)
    second = run_check("-c", source)
    assert first.returncode == second.returncode == 1
    assert first.stdout == second.stdout
