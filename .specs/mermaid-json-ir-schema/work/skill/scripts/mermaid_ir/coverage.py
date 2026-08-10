"""Verify exact equality between upstream inventory and target-owned coverage evidence."""

import json
from pathlib import Path


def check_coverage(inventory_dir: Path, coverage_dir: Path) -> dict[str, list[dict]]:
    """Return coverage by target or reject missing, orphaned, or incomplete entries."""

    result = {}
    for inventory_path in sorted(inventory_dir.glob("*.json")):
        inventory = json.loads(inventory_path.read_text())
        target = inventory["target"]
        owned = json.loads((coverage_dir / f"{target}.json").read_text())["entries"]
        expected, actual = set(inventory["constructs"]), {entry["constructId"] for entry in owned}
        if expected != actual:
            raise ValueError(f"{target}: missing={sorted(expected-actual)}, orphan={sorted(actual-expected)}")
        required = {"constructId", "jsonPointer", "presence", "defaultPolicy", "schemaRef", "serializerSymbol", "testIds"}
        for entry in owned:
            if set(entry) != required or not entry["testIds"]:
                raise ValueError(f"{target}: incomplete coverage entry {entry.get('constructId')!r}")
        result[target] = owned
    return result
