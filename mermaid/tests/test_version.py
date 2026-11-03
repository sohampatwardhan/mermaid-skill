"""Every SKILL.md carries a SemVer 2.0.0 version in its frontmatter metadata (Requirement 8).

The skill package declares its version the way the kiro-sdd-skills family does, under a
`metadata:` frontmatter block:

    metadata:
      author: sohampatwardhan
      version: "2.0.0"

This module fails if any SKILL.md in the repository is missing `metadata.version` or carries a
string that is not valid SemVer 2.0.0. The bump rule (PATCH / MINOR / MAJOR) is documented in
the README.
"""

from __future__ import annotations

import re

import pytest

from skill_docs import REPO_DIR

# The official SemVer 2.0.0 grammar, anchored, from https://semver.org (the regex the spec
# publishes), with its named groups flattened to plain groups.
SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)


def skill_files() -> list:
    return sorted(REPO_DIR.rglob("SKILL.md"))


def metadata_version(text: str) -> str | None:
    """The `version:` value inside the frontmatter `metadata:` block, unquoted, or None."""
    if not text.startswith("---\n"):
        return None
    frontmatter = text.split("---\n", 2)[1]
    in_metadata = False
    for line in frontmatter.splitlines():
        if re.match(r"^metadata:\s*$", line):
            in_metadata = True
            continue
        # A new top-level key (no leading space) ends the metadata block.
        if in_metadata and line and not line[0].isspace():
            in_metadata = False
        if in_metadata:
            match = re.match(r"\s+version:\s*(.+?)\s*$", line)
            if match:
                return match.group(1).strip().strip('"').strip("'")
    return None


def test_repo_has_at_least_one_skill() -> None:
    assert skill_files(), "no SKILL.md found in the repository"


@pytest.mark.parametrize("path", skill_files(), ids=lambda p: str(p.relative_to(REPO_DIR)))
def test_skill_has_valid_semver_version(path) -> None:
    version = metadata_version(path.read_text())
    assert version is not None, f"{path}: frontmatter has no metadata.version"
    assert SEMVER.match(version), f"{path}: metadata.version {version!r} is not valid SemVer 2.0.0"
