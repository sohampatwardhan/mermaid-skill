"""render.py CLI: exit codes 0, 1, 2, the stderr format, and no output file on failure."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from skill_docs import SKILL_DIR

RENDER = SKILL_DIR / "scripts" / "render.py"
INFO = {"diagram": "info", "target": "info"}


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(RENDER), *args], capture_output=True, text=True, timeout=60)


def test_valid_ir_exits_0_to_stdout(tmp_path: Path) -> None:
    ir = tmp_path / "ok.json"
    ir.write_text(json.dumps(INFO))
    result = run(str(ir))
    assert result.returncode == 0
    assert result.stdout == "info\n"
    assert result.stderr == ""


def test_valid_ir_exits_0_to_output_file(tmp_path: Path) -> None:
    ir = tmp_path / "ok.json"
    ir.write_text(json.dumps(INFO))
    out = tmp_path / "ok.mmd"
    result = run(str(ir), "-o", str(out))
    assert result.returncode == 0
    assert result.stdout == ""
    assert out.read_text() == "info\n"


def test_ir_error_exits_1_with_path_and_no_output_file(tmp_path: Path) -> None:
    ir = tmp_path / "bad.json"
    ir.write_text(json.dumps({"diagram": "graph", "target": "no-such-target"}))
    out = tmp_path / "bad.mmd"
    result = run(str(ir), "-o", str(out))
    assert result.returncode == 1
    assert result.stderr.startswith("ERROR: no-such-target: /target: ")
    assert result.stdout == ""
    assert not out.exists()


def test_missing_file_exits_2(tmp_path: Path) -> None:
    out = tmp_path / "x.mmd"
    result = run(str(tmp_path / "absent.json"), "-o", str(out))
    assert result.returncode == 2
    assert "file not found" in result.stderr
    assert not out.exists()


def test_invalid_json_exits_2(tmp_path: Path) -> None:
    ir = tmp_path / "broken.json"
    ir.write_text("{not json")
    out = tmp_path / "x.mmd"
    result = run(str(ir), "-o", str(out))
    assert result.returncode == 2
    assert "not valid JSON" in result.stderr
    assert not out.exists()


def test_unreadable_file_exits_2(tmp_path: Path) -> None:
    result = run(str(tmp_path))  # a directory cannot be read as a file
    assert result.returncode == 2
    assert result.stderr.startswith("ERROR: cannot read")
