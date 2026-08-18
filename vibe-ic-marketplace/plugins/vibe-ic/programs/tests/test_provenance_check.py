"""Unit tests for provenance_check.py."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

LOGGER = Path(__file__).parent.parent / "provenance_logger.py"
CHECKER = Path(__file__).parent.parent / "provenance_check.py"
assert LOGGER.exists() and CHECKER.exists()


def _run_check(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHECKER), *args],
        capture_output=True, text=True, timeout=15,
    )


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _log_entry(project: Path, tool: str, out_rel: str, exit_code: int = 0):
    """Append a hand-constructed entry (simulates a logger run)."""
    abs_p = project / out_rel
    entry = {
        "timestamp": "2026-04-22T10:00:00Z",
        "tool": tool,
        "version": "mock",
        "cwd": str(project),
        "argv": ["mock"],
        "inputs": {},
        "outputs": {out_rel: _sha(abs_p) if abs_p.exists() else "missing"},
        "exit_code": exit_code,
        "duration_s": 0.1,
        "stdout_sha": "sha256:0",
        "stderr_sha": "sha256:0",
        "stdout_tail": "",
        "stderr_tail": "",
    }
    with (project / "provenance.jsonl").open("a") as f:
        f.write(json.dumps(entry) + "\n")


def test_passes_when_log_and_hash_match(tmp_path):
    (tmp_path / "out.txt").write_text("content\n")
    _log_entry(tmp_path, "cat", "out.txt")
    r = _run_check(str(tmp_path), "--output", "out.txt", "--tool", "cat")
    assert r.returncode == 0


def test_fails_when_file_missing(tmp_path):
    # Log claims output but it doesn't exist on disk
    (tmp_path / "provenance.jsonl").write_text(json.dumps({
        "timestamp": "2026-04-22T10:00:00Z",
        "tool": "cat", "version": "", "cwd": str(tmp_path), "argv": [],
        "inputs": {}, "outputs": {"gone.txt": "sha256:abc"},
        "exit_code": 0, "duration_s": 0,
        "stdout_sha": "", "stderr_sha": "", "stdout_tail": "", "stderr_tail": "",
    }) + "\n")
    r = _run_check(str(tmp_path), "--output", "gone.txt", "--tool", "cat")
    assert r.returncode == 1
    assert "missing" in (r.stdout + r.stderr).lower()


def test_fails_on_hash_mismatch(tmp_path):
    f = tmp_path / "out.txt"
    f.write_text("v1")
    _log_entry(tmp_path, "cat", "out.txt")
    # Modify file after logging
    f.write_text("v2-different")
    r = _run_check(str(tmp_path), "--output", "out.txt", "--tool", "cat")
    assert r.returncode == 1
    assert "hash mismatch" in (r.stdout + r.stderr).lower()


def test_fails_on_wrong_tool(tmp_path):
    (tmp_path / "out.txt").write_text("x")
    _log_entry(tmp_path, "cat", "out.txt")
    r = _run_check(str(tmp_path), "--output", "out.txt", "--tool", "yosys,openroad")
    assert r.returncode == 1


def test_fails_on_nonzero_exit_entry(tmp_path):
    (tmp_path / "out.txt").write_text("x")
    _log_entry(tmp_path, "cat", "out.txt", exit_code=1)
    r = _run_check(str(tmp_path), "--output", "out.txt", "--tool", "cat")
    assert r.returncode == 1


def test_fails_with_no_log(tmp_path):
    (tmp_path / "out.txt").write_text("x")
    r = _run_check(str(tmp_path), "--output", "out.txt", "--tool", "cat")
    assert r.returncode == 1


def test_require_entries_mode(tmp_path):
    for i in range(3):
        _log_entry(tmp_path, f"t{i}", f"f{i}")
        (tmp_path / f"f{i}").write_text("x")
    r = _run_check(str(tmp_path), "--require-entries", "3")
    assert r.returncode == 0
    r = _run_check(str(tmp_path), "--require-entries", "5")
    assert r.returncode == 1


def test_logger_and_checker_roundtrip(tmp_path):
    """Invoke provenance_logger end-to-end, then provenance_check it."""
    (tmp_path / "in.txt").write_text("hello")
    subprocess.run([
        sys.executable, str(LOGGER),
        "--project", str(tmp_path),
        "--tool", "echo",
        "--output", "out.txt",
        "--",
        "sh", "-c", "echo roundtrip > out.txt",
    ], check=True, timeout=15)
    r = _run_check(str(tmp_path), "--output", "out.txt", "--tool", "echo")
    assert r.returncode == 0, r.stdout + r.stderr
