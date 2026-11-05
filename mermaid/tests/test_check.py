"""Tests for scripts/check.sh: pinned parser, line reporting, Markdown mode, determinism.

check.sh validates by PARSING the diagram with the pinned Mermaid 12.0.0 (Node + mermaid@12.0.0
+ jsdom), not by rendering it. There is no browser, no mmdc, and no SVG. A diagram is valid when
mermaid.parse() accepts it; a parse error is reported with the parser's own line and message.
"""

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
PARSER = SKILL_DIR / "scripts" / "mermaid-parse.mjs"
WORKFLOW = REPO_DIR / ".github" / "workflows" / "tests.yml"
BASH = shutil.which("bash") or "/bin/bash"

# Every external tool check.sh calls besides node/npm. A PATH made only of these has no node,
# so check.sh cannot reach the pinned parser and must exit 3.
TOOLS = ("mktemp", "rm", "cp", "cat", "sed", "tr", "grep", "awk", "head", "mkdir", "dirname", "cd")

HAVE_PARSE = bool(shutil.which("node") and (os.environ.get("MERMAID_PARSE_NODE_MODULES") or shutil.which("npm")))
needs_parse = pytest.mark.skipif(not HAVE_PARSE, reason="needs Node and the pinned Mermaid 12.0.0 parser")


def tools_dir(tmp_path: Path) -> Path:
    bindir = tmp_path / "tools"
    bindir.mkdir()
    for tool in TOOLS:
        found = shutil.which(tool)
        if found:
            (bindir / tool).symlink_to(found)
    return bindir


def write_exe(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


def run_check(*args: str, env: dict | None = None, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BASH, str(CHECK), *args],
        capture_output=True, text=True, timeout=600, env=env, input=stdin,
    )


# --- parser dependency resolution -------------------------------------------------------


def test_no_node_exits_3_and_names_the_version(tmp_path: Path) -> None:
    # A PATH with the helper tools but no node: check.sh cannot run the pinned parser.
    env = {**os.environ, "PATH": str(tools_dir(tmp_path))}
    env.pop("MERMAID_PARSE_NODE_MODULES", None)
    result = run_check("-c", "flowchart TD\n  A-->B", env=env)
    assert result.returncode == 3
    assert "Mermaid 12.0.0" in (result.stdout + result.stderr)


@needs_parse
def test_node_modules_without_the_deps_exits_3(tmp_path: Path) -> None:
    empty = tmp_path / "node_modules"
    empty.mkdir()
    env = {**os.environ, "MERMAID_PARSE_NODE_MODULES": str(empty)}
    result = run_check("-c", "flowchart TD\n  A-->B", env=env)
    assert result.returncode == 3
    assert "mermaid or jsdom" in (result.stdout + result.stderr) or "Mermaid 12.0.0" in result.stdout


def test_pin_matches_workflow() -> None:
    script = CHECK.read_text()
    workflow = WORKFLOW.read_text()
    assert re.search(r'^REQUIRED_MERMAID_VERSION="12\.0\.0"$', script, re.M)
    assert "mermaid@12.0.0" in workflow
    # The workflow must provision the same pin the parser loads, and assert the core version.
    assert "jsdom" in workflow
    assert "v!=='12.0.0'" in workflow or "12.0.0" in workflow


def test_validates_by_parsing_not_rendering() -> None:
    # The decision: parse-only. No render tooling in the validation path.
    script = CHECK.read_text()
    assert "mermaid-parse.mjs" in script
    for forbidden in ("mmdc", "puppeteer", "chromium", "mermaid-cli", "error-placeholder"):
        assert forbidden.lower() not in script.lower(), f"check.sh still references {forbidden!r}"
    assert PARSER.exists()


@needs_parse
def test_identical_runs_give_identical_output() -> None:
    source = "flowchart TD\n  A --> B\n  B --> --> C\n"
    first = run_check("-c", source)
    second = run_check("-c", source)
    assert first.returncode == second.returncode == 1
    assert first.stdout == second.stdout


# --- line reporting ---------------------------------------------------------------------


@needs_parse
def test_parse_error_reports_line_3() -> None:
    result = run_check("-c", "flowchart TD\n  A --> B\n  B --> --> C\n")
    assert result.returncode == 1
    assert "FAIL line 3:   B --> --> C" in result.stdout
    assert "Parse error on line 3" in result.stdout  # the parser message follows


@needs_parse
def test_line_counts_frontmatter() -> None:
    source = "---\nconfig:\n  layout: elk\n---\nflowchart TD\n  A --> B\n  B --> --> C\n"
    result = run_check("-c", source)
    assert result.returncode == 1
    assert "FAIL line 7:   B --> --> C" in result.stdout


@needs_parse
def test_unknown_diagram_reports_line_unknown() -> None:
    result = run_check("-c", "notadiagram\n  A\n")
    assert result.returncode == 1
    first = result.stdout.splitlines()[0]
    assert first.startswith("FAIL line unknown: ")
    assert "No diagram type detected" in first


@needs_parse
def test_passing_diagram_exits_0() -> None:
    result = run_check("-c", "flowchart TD\n  A --> B\n")
    assert result.returncode == 0
    assert "PASS" in result.stdout


# --- whole-batch parse bound ------------------------------------------------------------


def _sleeping_node(tmp_path: Path) -> Path:
    """A fake `node` that answers the version probe but sleeps when asked to parse.

    check.sh first runs `node -e "...require(.../mermaid/package.json).version..."` to verify the
    pin, then `node mermaid-parse.mjs` to parse. Echo the pinned version for the `-e` probe so
    check.sh reaches the parse step, then sleep past the bound for the parse run itself.
    """
    fake = tmp_path / "fake"
    fake.mkdir()
    write_exe(
        fake / "node",
        'case "$1" in\n'
        '  -e) echo 12.0.0 ;;\n'
        '  *) sleep 30 ;;\n'
        'esac\n',
    )
    return fake


@needs_parse
def test_batch_timeout_fails_and_says_timeout(tmp_path: Path) -> None:
    # Point check.sh at a node_modules that already has the deps (so it reaches the parse step),
    # but put a sleeping `node` first on PATH so the parse process outlives the bound.
    assert os.environ.get("MERMAID_PARSE_NODE_MODULES"), "conftest provisions the pin"
    fake = _sleeping_node(tmp_path)
    env = {
        **os.environ,
        "PATH": f"{fake}:{os.environ['PATH']}",
        "MERMAID_CHECK_TIMEOUT": "1",
    }
    result = run_check("-c", "flowchart TD\n  A-->B", env=env)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "timeout" in (result.stdout + result.stderr).lower()


# --- Markdown mode ----------------------------------------------------------------------

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
# The bad fence's content starts on Markdown line 21; its parser line 3 is Markdown line 23.
BAD_MD_LINE = 23


@needs_parse
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


@needs_parse
def test_markdown_all_good_passes(tmp_path: Path) -> None:
    md = tmp_path / "good.md"
    md.write_text(MIXED_MD.split("```mermaid\nflowchart TD\n  A --> B\n  B -->")[0])
    result = run_check("--markdown", str(md))
    assert result.returncode == 0, result.stdout
    assert f"PASS {md} (2 fences)" in result.stdout


@needs_parse
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
