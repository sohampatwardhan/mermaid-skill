"""SKILL.md is a lean index (Requirement 2) and README documents install (Requirement 7)."""

from __future__ import annotations

import re

from skill_docs import REFERENCE, REPO_DIR, SKILL_DIR, coverage_rows, split_row, tables, type_set

SKILL = SKILL_DIR / "SKILL.md"
README = REPO_DIR / "README.md"
REMOVED = ("type-cheatsheets.md", "ir-catalog.md", "iso-5807-flowcharts.md")


def frontmatter(text: str) -> dict[str, str]:
    assert text.startswith("---\n")
    block = text.split("---\n", 2)[1]
    out = {}
    for line in block.splitlines():
        if ":" in line and not line.startswith(" "):
            key, value = line.split(":", 1)
            out[key.strip()] = value.strip()
    return out


def index_rows() -> list[list[str]]:
    for table in tables(SKILL.read_text()):
        if table[0] == ["Type", "Keywords", "Use for", "Catalog"]:
            return table[1:]
    raise AssertionError("SKILL.md has no Type | Keywords | Use for | Catalog index")


# --- Requirement 2 --------------------------------------------------------------------------


def test_name_is_mermaid_and_folder_is_mermaid() -> None:
    assert frontmatter(SKILL.read_text())["name"] == "mermaid"
    assert SKILL_DIR.name == "mermaid"


def test_skill_is_at_most_120_lines() -> None:
    assert len(SKILL.read_text().splitlines()) <= 120


def test_index_has_one_row_per_type_linking_an_existing_catalog_file() -> None:
    rows = index_rows()
    types = {row[0] for row in rows}
    assert types == type_set(), f"missing: {sorted(type_set() - types)}; extra: {sorted(types - type_set())}"
    for row in rows:
        link = re.fullmatch(r"\[[^\]]+\]\((reference/catalog/[^)]+)\)", row[3])
        assert link, f"{row[0]}: Catalog cell is not a link: {row[3]}"
        assert (SKILL_DIR / link.group(1)).exists(), f"{row[0]} links a missing file: {link.group(1)}"


def test_index_keywords_match_coverage() -> None:
    by_type = {row.type_id: row for row in coverage_rows()}
    for row in index_rows():
        listed = {k.strip().strip("`") for k in re.split(r",|…", row[1]) if k.strip() and k.strip() != "`"}
        keywords = set(by_type[row[0]].keywords)
        # The index may abbreviate a long keyword list, but every keyword it names must be real.
        bogus = listed - keywords - {"graph"}  # `graph` is the documented flowchart alias
        assert not bogus, f"{row[0]} index names unknown keyword(s): {bogus}"


def test_no_per_type_syntax_beyond_the_index() -> None:
    # No column-0 ```mermaid fence in SKILL.md: it routes, it does not teach syntax.
    assert not re.search(r"^```mermaid\s*$", SKILL.read_text(), re.M)


def test_skill_states_the_check_rule() -> None:
    text = SKILL.read_text()
    assert "scripts/check.sh" in text
    assert "12.0.0" in text
    assert "unverified" in text  # 2.7: say once that an unchecked diagram is unverified


def test_removed_files_are_absent_and_unlinked() -> None:
    for name in REMOVED:
        assert not (REFERENCE / name).exists(), f"{name} should be deleted"
    for path in list(SKILL_DIR.rglob("*.md")) + [README]:
        text = path.read_text()
        for name in REMOVED:
            assert name not in text, f"{path} still links {name}"


# --- Requirement 7 --------------------------------------------------------------------------


def test_readme_documents_both_skills_commands() -> None:
    text = README.read_text()
    assert "npx skills add sohampatwardhan/mermaid-skill -g" in text
    assert "npx skills update" in text and "-g" in text


def test_readme_names_the_skill_and_links_index_and_coverage() -> None:
    text = README.read_text()
    assert "`mermaid`" in text
    assert "mermaid/SKILL.md" in text
    assert "mermaid/reference/coverage.md" in text
