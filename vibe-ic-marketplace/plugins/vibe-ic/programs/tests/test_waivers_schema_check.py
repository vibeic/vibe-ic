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


def test_reject_unfilled_template_approver(tmp_path):
    """An UNFILLED waivers.json.template must not ship as waivers.json.

    waiver_template_gen.py documents that its placeholders are "GUARANTEED to
    reject", but the only approver rule was SELF_APPROVERS, which the sentinel
    __TODO_HUMAN_NAME__ does not match. With a real (>= MIN_REASON_LEN) reason
    filled in, an unapproved template therefore validated clean.
    """
    _write(tmp_path / "waivers.json", {
        "waived_steps": [
            {"id": 1,
             "reason": "IC class registers rtl_gen=null; RTL authored via the spec-to-rtl skill",
             "approver": "__TODO_HUMAN_NAME__",
             "ticket": "OPS-101"}
        ]
    })
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "placeholder" in (r.stdout + r.stderr).lower()


def test_reject_placeholder_approver_variants(tmp_path):
    """Generalises by SHAPE (dunder sentinel / bracketed / bare filler word),
    not by our own template's literal string."""
    for filler in ("__APPROVER__", "<TODO>", "[name]", "your name", "TBD", "xxx"):
        _write(tmp_path / "waivers.json", {
            "waived_steps": [
                {"id": 11,
                 "reason": "ATPG deferred to sign-off; scan insertion runs on the final netlist",
                 "approver": filler}
            ]
        })
        r = _run(tmp_path)
        assert r.returncode == 1, f"{filler!r} was accepted as an approver"


def test_real_approver_still_accepted(tmp_path):
    """The placeholder rule must not swallow legitimate approvers — including
    the sanctioned machine tier used by waivers_materialize.py."""
    for good in ("reyerchu", "field-agent-attest (fpga-board cap-gap tier)",
                 "Ada Lovelace", "eng-owner@example.com"):
        _write(tmp_path / "waivers.json", {
            "waived_steps": [
                {"id": 11,
                 "reason": "ATPG deferred to sign-off; scan insertion runs on the final netlist",
                 "approver": good}
            ]
        })
        r = _run(tmp_path)
        assert r.returncode == 0, f"{good!r} was wrongly rejected: {r.stdout}{r.stderr}"
