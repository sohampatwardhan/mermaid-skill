"""Reliability checks for one IR builder (Requirement 4). Pure Python except `run_batch`.

Each `check_*` function returns a list of problem strings; an empty list means the builder
passed. `tests/test_builders.py` runs them for every kept builder, and the self-test runs
them against toy builders to prove they fail when they should.
"""

from __future__ import annotations

import copy
import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from corpus import HOSTILE, PLAIN
from skill_docs import CATALOG_DIR, SKILL_DIR, run_check_markdown, sections, tables, unticked

FIXTURES = SKILL_DIR / "tests" / "fixtures"
NOT_RENDERED = "does not render in 12.0.0"
UNKNOWN_KEY = "x-unknown"
PROBE_VALUES = {"number": True, "enum": "x-no-such-value", "ref": "x_undeclared_ref"}
PROBE_KINDS = ("object", "number", "enum", "ref")


# --- JSON Pointer helpers -------------------------------------------------------------------


def tokens(pointer: str) -> list[str]:
    if pointer == "":
        return []
    assert pointer.startswith("/"), pointer
    return [t.replace("~1", "/").replace("~0", "~") for t in pointer[1:].split("/")]


def escape(token: Any) -> str:
    return str(token).replace("~", "~0").replace("/", "~1")


def get(doc: Any, pointer: str) -> Any:
    node = doc
    for token in tokens(pointer):
        node = node[int(token)] if isinstance(node, list) else node[token]
    return node


def with_value(doc: Any, pointer: str, value: Any) -> Any:
    """A deep copy of doc with the value at pointer replaced."""
    out = copy.deepcopy(doc)
    *parents, last = tokens(pointer)
    node = out
    for token in parents:
        node = node[int(token)] if isinstance(node, list) else node[token]
    if isinstance(node, list):
        node[int(last)] = value
    else:
        node[last] = value
    return out


def matches(doc: Any, pattern: str) -> list[str]:
    """Concrete pointers in doc matching a pattern (`*` = any key or index, optional `=value`)."""
    expected: str | None = None
    if "=" in pattern:
        pattern, expected = pattern.split("=", 1)
    found: list[str] = []

    def walk(node: Any, rest: list[str], at: str) -> None:
        if not rest:
            if expected is None or (node if isinstance(node, str) else json.dumps(node)) == expected:
                found.append(at)
            return
        head, tail = rest[0], rest[1:]
        if isinstance(node, dict):
            keys = list(node) if head == "*" else [head] if head in node else []
            for key in keys:
                walk(node[key], tail, f"{at}/{escape(key)}")
        elif isinstance(node, list):
            indexes = range(len(node)) if head == "*" else [int(head)] if head.isdigit() and int(head) < len(node) else []
            for index in indexes:
                walk(node[index], tail, f"{at}/{index}")

    walk(doc, tokens(pattern), "")
    return found


# --- fixtures and catalog -------------------------------------------------------------------


def load_fixtures(type_id: str, kind: str, root: Path = FIXTURES) -> dict[str, dict]:
    """`minimal*.json` or `maximal*.json` for a type, keyed by file name, sorted."""
    folder = root / type_id
    return {p.name: json.loads(p.read_text()) for p in sorted(folder.glob(f"{kind}*.json"))}


def primary(docs: dict[str, dict]) -> tuple[str, dict]:
    name = "maximal.json" if "maximal.json" in docs else next(iter(docs))
    return name, docs[name]


def catalog_features(type_id: str, catalog_dir: Path = CATALOG_DIR) -> list[str]:
    """Feature ids of a catalog file, minus rows marked as not rendering in 12.0.0."""
    body = sections((catalog_dir / f"{type_id}.md").read_text())["Features"]
    header, *rows = tables(body)[0]
    return [unticked(row[0]) for row in rows if NOT_RENDERED not in row[1]]


# --- checks ---------------------------------------------------------------------------------

Render = Callable[[dict], str]


@dataclass
class Case:
    label: str
    source: str


def check_fixtures(render: Render, minimal: dict[str, dict], maximal: dict[str, dict]) -> tuple[list[str], list[Case]]:
    problems: list[str] = []
    cases: list[Case] = []
    if not minimal:
        problems.append("no minimal*.json fixture")
    if not maximal:
        problems.append("no maximal*.json fixture")
    for name, doc in {**minimal, **maximal}.items():
        try:
            first = render(doc)
            second = render(copy.deepcopy(doc))
        except Exception as exc:  # noqa: BLE001 - any failure is a problem to report
            problems.append(f"{name}: does not render: {exc}")
            continue
        if first != second:
            problems.append(f"{name}: two renders differ")
        if not first.endswith("\n") or first.endswith("\n\n"):
            problems.append(f"{name}: source must end in exactly one newline")
        cases.append(Case(name, first))
    return problems, cases


def check_parity(features: dict[str, str], catalog_ids: list[str], maximal: dict[str, dict]) -> list[str]:
    problems = []
    for feature_id in catalog_ids:
        if feature_id not in features:
            problems.append(f"catalog feature {feature_id} has no feature path in the builder")
    for feature_id, pattern in features.items():
        if feature_id not in catalog_ids:
            problems.append(f"builder feature {feature_id} is not in the catalog Features table")
        elif not any(matches(doc, pattern) for doc in maximal.values()):
            problems.append(f"feature {feature_id}: pattern {pattern} matches no maximal fixture")
    return problems


def corpus_targets(text_fields: tuple[str, ...], maximal: dict[str, dict]) -> Iterator[tuple[str, str, str | None]]:
    """(pattern, fixture name, first concrete pointer or None) for each text field."""
    for pattern in text_fields:
        for name, doc in maximal.items():
            found = matches(doc, pattern)
            if found:
                yield pattern, name, found[0]
                break
        else:
            yield pattern, "", None


def check_corpus(
    render: Render, error_type: type, text_fields: tuple[str, ...], maximal: dict[str, dict]
) -> tuple[list[str], list[Case]]:
    problems: list[str] = []
    cases: list[Case] = []
    if not text_fields:
        problems.append("builder declares no text_fields")
    for pattern, name, pointer in corpus_targets(text_fields, maximal):
        if pointer is None:
            problems.append(f"text field {pattern} matches no maximal fixture")
            continue
        for value in PLAIN + HOSTILE:
            doc = with_value(maximal[name], pointer, value)
            label = f"{name} {pointer} = {json.dumps(value, ensure_ascii=False)}"
            try:
                source = render(doc)
            except error_type as err:
                if value in PLAIN:
                    problems.append(f"{label}: plain string rejected: {err}")
                elif getattr(err, "path", None) != pointer:
                    problems.append(f"{label}: rejected at {getattr(err, 'path', None)!r}, expected {pointer}")
                continue
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{label}: crashed with {type(exc).__name__}: {exc}")
                continue
            if value in PLAIN and value not in source:
                problems.append(f"{label}: accepted but the text is missing from the source (dropped)")
            cases.append(Case(label, source))
    return problems, cases


def expect_error(render: Render, error_type: type, doc: dict, pointer: str, what: str) -> list[str]:
    try:
        render(doc)
    except error_type as err:
        if getattr(err, "path", None) != pointer:
            return [f"{what}: IRError at {getattr(err, 'path', None)!r}, expected {pointer}"]
        return []
    except Exception as exc:  # noqa: BLE001
        return [f"{what}: crashed with {type(exc).__name__}: {exc}"]
    return [f"{what}: accepted, expected IRError at {pointer}"]


def check_strictness(render: Render, error_type: type, probes: dict, maximal: dict[str, dict]) -> list[str]:
    problems: list[str] = []
    if not maximal:
        return ["no maximal fixture"]
    _name, doc = primary(maximal)
    problems += expect_error(render, error_type, {**doc, UNKNOWN_KEY: 1}, f"/{UNKNOWN_KEY}", "unknown root key")
    for kind in PROBE_KINDS:
        if kind not in probes:
            problems.append(f"probes has no {kind!r} entry (use None when the IR has none)")
            continue
        pointer = probes[kind]
        if pointer is None:
            continue
        try:
            current = get(doc, pointer)
        except (KeyError, IndexError, ValueError, TypeError):
            problems.append(f"{kind} probe {pointer} does not exist in the maximal fixture")
            continue
        if kind == "object":
            if not isinstance(current, dict) or pointer == "":
                problems.append(f"object probe {pointer} is not a nested object")
                continue
            bad = with_value(doc, pointer, {**current, UNKNOWN_KEY: 1})
            problems += expect_error(render, error_type, bad, f"{pointer}/{UNKNOWN_KEY}", "unknown nested key")
        else:
            bad = with_value(doc, pointer, PROBE_VALUES[kind])
            problems += expect_error(render, error_type, bad, pointer, f"{kind} probe")
    return problems


# --- pinned check batch ---------------------------------------------------------------------


def batch_markdown(cases: list[Case]) -> tuple[str, list[tuple[int, str]]]:
    """One Markdown document with a fence per case, plus (first content line, label) pairs."""
    out: list[str] = []
    starts: list[tuple[int, str]] = []
    for case in cases:
        out += [f"Case: {case.label}", "", "```mermaid"]
        starts.append((len(out) + 1, case.label))
        out += case.source.rstrip("\n").split("\n")
        out += ["```", ""]
    return "\n".join(out) + "\n", starts


def run_batch(cases: list[Case]) -> list[str]:
    """Render every case through `check.sh --markdown` once; return failures by case label."""
    text, starts = batch_markdown(cases)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "batch.md"
        path.write_text(text)
        result = run_check_markdown(path)
    if result.returncode == 0:
        return []
    problems = []
    for line in result.stdout.splitlines():
        hit = re.match(rf"{re.escape(str(path))}:(\d+): (.*)", line)
        if hit:
            number = int(hit.group(1))
            label = max((s for s in starts if s[0] <= number), default=(0, "?"))[1]
            problems.append(f"{label}: {hit.group(2)}")
    return problems or [result.stdout + result.stderr]
