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


# --- 2.2 line reporting -----------------------------------------------------------------


@needs_cli
def test_parse_error_reports_line_3() -> None:
    result = run_check("-c", "flowchart TD\n  A --> B\n  B --> --> C\n")
    assert result.returncode == 1
    assert "FAIL line 3:   B --> --> C" in result.stdout
    assert "Parse error on line 3" in result.stdout  # full CLI output follows


@needs_cli
def test_line_counts_frontmatter() -> None:
    source = "---\nconfig:\n  layout: elk\n---\nflowchart TD\n  A --> B\n  B --> --> C\n"
    result = run_check("-c", source)
    assert result.returncode == 1
    assert "FAIL line 7:   B --> --> C" in result.stdout


@needs_cli
def test_unknown_diagram_reports_line_unknown() -> None:
    result = run_check("-c", "notadiagram\n  A\n")
    assert result.returncode == 1
    first = result.stdout.splitlines()[0]
    assert first.startswith("FAIL line unknown: ")
    assert "UnknownDiagramError" in first


def test_error_placeholder_svg_exits_1(tmp_path: Path) -> None:
    fake = tmp_path / "fake"
    fake.mkdir()
    write_exe(
        fake / "mmdc",
        'if [ "$1" = "--version" ]; then echo 12.0.0; exit 0; fi\n'
        'while [ $# -gt 0 ]; do if [ "$1" = "-o" ]; then out="$2"; fi; shift; done\n'
        'echo \'<svg aria-roledescription="error"><text>Syntax error in text</text></svg>\' > "$out"\n',
    )
    env = {**os.environ, "PATH": f"{fake}:{tools_dir(tmp_path)}"}
    result = run_check("-c", "flowchart TD\n  A-->B", env=env)
    assert result.returncode == 1
    assert result.stdout.startswith("FAIL line unknown")


# --- 2.2b per-render timeout ------------------------------------------------------------


def _sleeping_mmdc(tmp_path: Path) -> Path:
    """A fake mmdc 12.0.0 that writes a valid SVG but only after a long sleep."""
    fake = tmp_path / "fake"
    fake.mkdir()
    write_exe(
        fake / "mmdc",
        'if [ "$1" = "--version" ]; then echo 12.0.0; exit 0; fi\n'
        'while [ $# -gt 0 ]; do if [ "$1" = "-o" ]; then out="$2"; fi; shift; done\n'
        'sleep 30\n'
        'echo "<svg></svg>" > "$out"\n',
    )
    return fake


def test_single_diagram_timeout_fails_and_says_timeout(tmp_path: Path) -> None:
    fake = _sleeping_mmdc(tmp_path)
    # Keep the real PATH so check.sh's portable timeout (timeout/gtimeout/perl/python3) and the
    # fake's own `sleep` resolve; the fake mmdc 12.0.0 is first, so it is the one that is used.
    env = {
        **os.environ,
        "PATH": f"{fake}:{os.environ['PATH']}",
        "MERMAID_CHECK_TIMEOUT": "1",
    }
    result = run_check("-c", "flowchart TD\n  A-->B", env=env)
    # A render that outlives the bound must never pass.
    assert result.returncode == 1, result.stdout + result.stderr
    assert "timeout" in (result.stdout + result.stderr).lower()


def test_markdown_timeout_reports_path_line_and_timeout(tmp_path: Path) -> None:
    fake = _sleeping_mmdc(tmp_path)
    md = tmp_path / "slow.md"
    md.write_text("# Slow\n\n```mermaid\nflowchart TD\n  A --> B\n```\n")
    env = {
        **os.environ,
        "PATH": f"{fake}:{os.environ['PATH']}",
        "MERMAID_CHECK_TIMEOUT": "1",
    }
    result = run_check("--markdown", str(md), env=env)
    assert result.returncode == 1, result.stdout + result.stderr
    failures = [line for line in result.stdout.splitlines() if line.startswith(f"{md}:")]
    assert failures, result.stdout + result.stderr
    # Reported with path:line and the word "timeout".
    assert re.match(rf"{re.escape(str(md))}:\d+:", failures[0]), failures[0]
    assert "timeout" in "\n".join(failures).lower()


# --- 2.3 Markdown mode ------------------------------------------------------------------

MIXED_MD = """# Mixed

```mermaid
flowchart TD
  A --> B
```

Some prose.

```text
flowchart TD
  not --> --> checked
```

```mermaid
pie
  "a" : 1
```

```mermaid
flowchart TD
  A --> B
  B --> --> C
```
"""
# The bad fence's content starts on Markdown line 21; its CLI line 3 is Markdown line 23.
BAD_MD_LINE = 23


@needs_cli
def test_markdown_reports_path_and_markdown_line(tmp_path: Path) -> None:
    md = tmp_path / "mixed.md"
    md.write_text(MIXED_MD)
    assert md.read_text().splitlines()[BAD_MD_LINE - 1] == "  B --> --> C"
    result = run_check("--markdown", str(md))
    assert result.returncode == 1
    failures = [line for line in result.stdout.splitlines() if line.startswith(f"{md}:")]
    assert len(failures) == 1, result.stdout
    assert failures[0].startswith(f"{md}:{BAD_MD_LINE}: ")
    # Same verdict and lines on a second run.
    again = run_check("--markdown", str(md))
    assert again.returncode == 1 and again.stdout == result.stdout


@needs_cli
def test_markdown_all_good_passes(tmp_path: Path) -> None:
    md = tmp_path / "good.md"
    md.write_text(MIXED_MD.split("```mermaid\nflowchart TD\n  A --> B\n  B -->")[0])
    result = run_check("--markdown", str(md))
    assert result.returncode == 0, result.stdout
    assert f"PASS {md} (2 fences)" in result.stdout


@needs_cli
def test_markdown_without_fences_is_not_a_failure(tmp_path: Path) -> None:
    md = tmp_path / "plain.md"
    md.write_text("# Nothing\n\nNo diagrams here.\n")
    result = run_check("--markdown", str(md))
    assert result.returncode == 0
    assert f"{md}: no mermaid fences" in result.stdout


def test_markdown_missing_file_exits_2(tmp_path: Path) -> None:
    result = run_check("--markdown", str(tmp_path / "absent.md"))
    assert result.returncode == 2


# --- 3 pinned syntax cache --------------------------------------------------------------

REFRESH = SKILL_DIR / "scripts" / "refresh.sh"


def test_refresh_defaults_to_the_pinned_tag() -> None:
    script = REFRESH.read_text()
    assert 'MERMAID_REF="${MERMAID_REF:-mermaid@12.0.0}"' in script
    assert "?${REF_QS}" in script  # every API listing passes ref=
    assert "${RAW}/${DOCS_PATH}/" in script  # raw downloads are tag-qualified


def test_cache_is_stamped_with_the_pinned_version() -> None:
    stamp = "cached against Mermaid 12.0.0"
    assert stamp in (SKILL_DIR / "reference" / "diagram-types.md").read_text()
    assert stamp in (SKILL_DIR / "reference" / "syntax" / "README.md").read_text()


def test_refresh_failure_leaves_the_cache_untouched(tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    (skill / "scripts").mkdir(parents=True)
    (skill / "reference" / "syntax").mkdir(parents=True)
    shutil.copy(REFRESH, skill / "scripts" / "refresh.sh")
    (skill / "reference" / "diagram-types.md").write_text("old list\n")
    (skill / "reference" / "syntax" / "pie.md").write_text("old pie\n")
    fake = tmp_path / "fake"
    fake.mkdir()
    write_exe(fake / "curl", "exit 22\n")
    env = {**os.environ, "PATH": f"{fake}:{os.environ['PATH']}"}
    result = subprocess.run(
        [BASH, str(skill / "scripts" / "refresh.sh")], capture_output=True, text=True, env=env, timeout=60
    )
    assert result.returncode == 1
    assert "Nothing updated" in result.stdout
    assert (skill / "reference" / "diagram-types.md").read_text() == "old list\n"
    assert (skill / "reference" / "syntax" / "pie.md").read_text() == "old pie\n"
