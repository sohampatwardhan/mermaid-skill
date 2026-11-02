"""Shared parsers for the skill's Markdown: type set, coverage matrix, catalog files."""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = SKILL_DIR.parent
REFERENCE = SKILL_DIR / "reference"
SYNTAX_DIR = REFERENCE / "syntax"
CATALOG_DIR = REFERENCE / "catalog"
COVERAGE = REFERENCE / "coverage.md"
CHECK = SKILL_DIR / "scripts" / "check.sh"
BASH = shutil.which("bash") or "/bin/bash"
HAVE_CLI = bool(shutil.which("mmdc") or shutil.which("npx"))

SECTIONS = (
    "Keywords",
    "When to use",
    "Syntax",
    "Features",
    "Configuration and theming",
    "Traps",
    "Complete example",
    "Builder",
)
BUILDER_STATES = ("builder", "hand-author-only")


def load_render():
    spec = importlib.util.spec_from_file_location("render", SKILL_DIR / "scripts" / "render.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def type_set() -> set[str]:
    """Syntax page stems at the pinned version, minus README and examples, plus info."""
    stems = {p.stem for p in SYNTAX_DIR.glob("*.md")} - {"README", "examples"}
    return stems | {"info"}


def split_row(line: str) -> list[str]:
    """Split one Markdown table row on unescaped pipes."""
    body = line.strip()
    assert body.startswith("|") and body.endswith("|"), line
    cells = re.split(r"(?<!\\)\|", body[1:-1])
    return [cell.strip().replace("\\|", "|") for cell in cells]


def tables(text: str) -> list[list[list[str]]]:
    """Every Markdown table in text, as rows of cells, header first, separator dropped."""
    found: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in text.splitlines() + [""]:
        if line.strip().startswith("|"):
            cells = split_row(line)
            if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                continue
            current.append(cells)
        elif current:
            found.append(current)
            current = []
    return found


def unticked(cell: str) -> str:
    return cell.strip().strip("`")


@dataclass
class CoverageRow:
    type_id: str
    keywords: list[str]
    catalog: str
    builder: str
    tests: str
    gaps: str


def coverage_rows() -> list[CoverageRow]:
    text = COVERAGE.read_text()
    for table in tables(text):
        if table[0] == ["Type", "Keywords", "Catalog", "Builder", "Tests", "Gaps"]:
            rows = []
            for cells in table[1:]:
                assert len(cells) == 6, cells
                link = re.fullmatch(r"\[[^\]]+\]\(([^)]+)\)", cells[2])
                rows.append(
                    CoverageRow(
                        type_id=unticked(cells[0]),
                        keywords=[unticked(k) for k in cells[1].split(",") if k.strip()],
                        catalog=link.group(1) if link else cells[2],
                        builder=cells[3],
                        tests=cells[4],
                        gaps=cells[5],
                    )
                )
            return rows
    raise AssertionError("coverage.md has no Type | Keywords | Catalog | Builder | Tests | Gaps table")


def sections(text: str) -> dict[str, str]:
    """H2 sections of a catalog file, in order, keyed by heading."""
    out: dict[str, str] = {}
    current = None
    in_fence = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
        if not in_fence and line.startswith("## "):
            current = line[3:].strip()
            out[current] = ""
            continue
        if current is not None:
            out[current] += line + "\n"
    return out


def feature_ids(text: str) -> list[str]:
    """Feature ids from the first table of the Features section."""
    body = sections(text).get("Features", "")
    found = tables(body)
    assert found, "Features section has no table"
    header, *rows = found[0]
    assert header[:3] == ["Feature id", "Construct", "Snippet"], header
    return [unticked(row[0]) for row in rows]


def builder_state(text: str) -> str:
    """First backticked word of the Builder section."""
    body = sections(text).get("Builder", "")
    match = re.search(r"`([a-z-]+)`", body)
    return match.group(1) if match else ""


def run_check_markdown(*files: Path, timeout: int = 1800) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BASH, str(CHECK), "--markdown", *map(str, files)],
        capture_output=True, text=True, timeout=timeout,
    )
