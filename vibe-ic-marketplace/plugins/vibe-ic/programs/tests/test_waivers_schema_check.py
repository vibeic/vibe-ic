"""Unit tests for waivers_schema_check.py.

Covers: missing file (OK), rubber-stamp (FAIL), valid waiver (OK),
duplicate ids, invalid types, self-approver rejection.
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "waivers_schema_check.py"
assert SCRIPT.exists()


def _run(project_dir: Path):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(project_dir)],
        capture_output=True,
        text=True,
    )


def _write(path: Path, data: dict):
    path.write_text(json.dumps(data))


def test_missing_file_is_ok(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0


def test_valid_waiver(tmp_path):
    _write(tmp_path / "waivers.json", {
        "waived_steps": [
            {
                "id": 11,
                "reason": "Commercial ATPG tool not available in this environment; manual scan insertion will be run at sign-off",
                "approver": "reyerchu",
                "ticket": "OPS-100",
            }
        ]
    })
    r = _run(tmp_path)
    assert r.returncode == 0, f"stderr: {r.stderr}"


def test_reject_todo_placeholder(tmp_path):
    _write(tmp_path / "waivers.json", {
        "waived_steps": [{"id": 11, "reason": "TODO", "approver": "user"}]
    })
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "placeholder" in (r.stdout + r.stderr).lower() or "short" in (r.stdout + r.stderr).lower()


def test_reject_self_approval(tmp_path):
    _write(tmp_path / "waivers.json", {
        "waived_steps": [
            {
                "id": 11,
                "reason": "No FPGA board available and board required for on-board test",
                "approver": "agent",
            }
        ]
    })
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "self" in (r.stdout + r.stderr).lower() or "approver" in (r.stdout + r.stderr).lower()


def test_reject_short_reason(tmp_path):
    _write(tmp_path / "waivers.json", {
        "waived_steps": [
            {"id": 11, "reason": "no tool", "approver": "reyerchu"}
        ]
    })
    r = _run(tmp_path)
    assert r.returncode == 1


def test_reject_duplicate_id(tmp_path):
    _write(tmp_path / "waivers.json", {
        "waived_steps": [
            {"id": 11, "reason": "reason one long enough to pass validation check", "approver": "reyerchu"},
            {"id": 11, "reason": "reason two long enough to pass validation check", "approver": "reyerchu"},
        ]
    })
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "duplicate" in (r.stdout + r.stderr).lower() or "more than once" in (r.stdout + r.stderr).lower()


def test_reject_id_out_of_range(tmp_path):
    _write(tmp_path / "waivers.json", {
        "waived_steps": [
            {"id": 99, "reason": "this is a sufficiently long reason string to pass", "approver": "reyerchu"}
        ]
    })
    r = _run(tmp_path)
    assert r.returncode == 1


def test_malformed_json(tmp_path):
    (tmp_path / "waivers.json").write_text("{not json")
    r = _run(tmp_path)
    assert r.returncode == 1
