"""Unit tests for provenance_logger.py.

Tests cover the wrap-run-record loop end-to-end using shell commands
(no real EDA tool needed).
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "provenance_logger.py"
assert SCRIPT.exists()


def _run_logger(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, timeout=30,
    )


def test_logs_successful_run(tmp_path):
    (tmp_path / "in.txt").write_text("hello\n")
    r = _run_logger(
        "--project", str(tmp_path),
        "--tool", "cat",
        "--input", "in.txt",
        "--output", "out.txt",
        "--",
        "sh", "-c", "cat in.txt > out.txt",
    )
    assert r.returncode == 0
    log = tmp_path / "provenance.jsonl"
    assert log.exists()
    rec = json.loads(log.read_text().splitlines()[0])
    assert rec["tool"] == "cat"
    assert rec["exit_code"] == 0
    assert rec["inputs"]["in.txt"].startswith("sha256:")
    assert rec["outputs"]["out.txt"].startswith("sha256:")
    # And out.txt exists on disk with the same hash
    assert (tmp_path / "out.txt").exists()


def test_missing_declared_output_fails(tmp_path):
    """Tool exits 0 but declared output wasn't created — wrapper fails with 2."""
    r = _run_logger(
        "--project", str(tmp_path),
        "--tool", "cat",
        "--output", "not_created.txt",
        "--",
        "sh", "-c", "echo noop",
    )
    assert r.returncode == 2
    # Record is still written
    log = tmp_path / "provenance.jsonl"
    assert log.exists()
    rec = json.loads(log.read_text().splitlines()[0])
    assert rec["outputs"]["not_created.txt"] == "missing"


def test_tool_nonzero_exit_propagated(tmp_path):
    r = _run_logger(
        "--project", str(tmp_path),
        "--tool", "false_tool",
        "--",
        "sh", "-c", "exit 7",
    )
    assert r.returncode == 7
    log = tmp_path / "provenance.jsonl"
    assert log.exists()
    rec = json.loads(log.read_text().splitlines()[0])
    assert rec["exit_code"] == 7


def test_cmd_not_found(tmp_path):
    r = _run_logger(
        "--project", str(tmp_path),
        "--tool", "ghost",
        "--",
        "nonexistent_binary_xyz", "--flag",
    )
    assert r.returncode == 127


def test_multiple_entries_appended(tmp_path):
    for i in range(3):
        _run_logger(
            "--project", str(tmp_path),
            "--tool", f"tool{i}",
            "--",
            "sh", "-c", f"echo {i}",
        )
    log = tmp_path / "provenance.jsonl"
    assert log.exists()
    lines = [l for l in log.read_text().splitlines() if l.strip()]
    assert len(lines) == 3
    tools = [json.loads(l)["tool"] for l in lines]
    assert tools == ["tool0", "tool1", "tool2"]
