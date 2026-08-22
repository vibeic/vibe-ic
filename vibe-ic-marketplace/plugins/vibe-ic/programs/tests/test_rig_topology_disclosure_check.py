"""Tests for rig_topology_disclosure_check.py (D3 gate)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "rig_topology_disclosure_check.py"

VALID_TOPOLOGY = {
    "fpga_board": "DE10-Lite",
    "fpga_pin_assignments": {"SIO": "PIN_V10", "CLK": "PIN_P11"},
    "dut_connection": "SIO directly to MAX10 GPIO via 100Ω series",
    "scope_channel_map": {"ch1": "CLK", "ch4": "SIO"},
    "tester_port": "USB-HID /dev/hidraw0",
}


def _run(project_dir: str, json_out: bool = True) -> tuple[int, dict | str]:
    cmd = [sys.executable, str(PROG), project_dir]
    if json_out:
        cmd.append("--json")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if json_out and r.returncode != 2:
        return r.returncode, json.loads(r.stdout)
    return r.returncode, r.stdout + r.stderr


def test_pass_json_topology(tmp_path: Path):
    (tmp_path / "rig_topology.json").write_text(json.dumps(VALID_TOPOLOGY))
    rc, out = _run(str(tmp_path))
    assert rc == 0
    assert out["verdict"] == "PASS"
    assert out["errors"] == 0
    assert out["warnings"] == 0


def test_pass_in_spec_json(tmp_path: Path):
    spec = {"design_name": "test_ic", "rig_topology": VALID_TOPOLOGY}
    (tmp_path / "spec.json").write_text(json.dumps(spec))
    rc, out = _run(str(tmp_path))
    assert rc == 0
    assert out["verdict"] == "PASS"
    assert "spec.json#rig_topology" in out["source"]


def test_pass_in_l9_json(tmp_path: Path):
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    l9 = {"ports": [], "rig_topology": VALID_TOPOLOGY}
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(l9))
    rc, out = _run(str(tmp_path))
    assert rc == 0
    assert out["verdict"] == "PASS"


def test_pass_in_input_subdir(tmp_path: Path):
    inp = tmp_path / "input"
    inp.mkdir(parents=True, exist_ok=True)
    (inp / "rig_topology.json").write_text(json.dumps(VALID_TOPOLOGY))
    rc, out = _run(str(tmp_path))
    assert rc == 0
    assert out["verdict"] == "PASS"


def test_pass_markdown_topology(tmp_path: Path):
    (tmp_path / "rig_topology.md").write_text("# Rig\nDE10-Lite, SIO on PIN_V10\n")
    rc, out = _run(str(tmp_path))
    assert rc == 0
    assert out["verdict"] == "PASS"
    assert any(f["rule"] == "rig_topology_markdown" for f in out["findings"])


def test_fail_no_topology(tmp_path: Path):
    rc, out = _run(str(tmp_path))
    assert rc == 1
    assert out["verdict"] == "FAIL"
    assert out["errors"] == 1
    assert out["findings"][0]["rule"] == "rig_topology_not_found"


def test_fail_missing_required_fields(tmp_path: Path):
    partial = {"fpga_board": "DE10-Lite"}
    (tmp_path / "rig_topology.json").write_text(json.dumps(partial))
    rc, out = _run(str(tmp_path))
    assert rc == 1
    assert out["verdict"] == "FAIL"
    missing = [f for f in out["findings"] if f["rule"] == "rig_topology_missing_required"]
    assert len(missing) == 2  # fpga_pin_assignments + dut_connection


def test_fail_bad_pin_type(tmp_path: Path):
    bad = {**VALID_TOPOLOGY, "fpga_pin_assignments": "not a dict"}
    (tmp_path / "rig_topology.json").write_text(json.dumps(bad))
    rc, out = _run(str(tmp_path))
    assert rc == 1
    assert any(f["rule"] == "rig_topology_bad_type" for f in out["findings"])


def test_warn_missing_optional(tmp_path: Path):
    minimal = {
        "fpga_board": "DE10-Lite",
        "fpga_pin_assignments": {"SIO": "PIN_V10"},
        "dut_connection": "direct",
    }
    (tmp_path / "rig_topology.json").write_text(json.dumps(minimal))
    rc, out = _run(str(tmp_path))
    assert rc == 0  # warnings don't cause FAIL
    assert out["verdict"] == "PASS"
    assert out["warnings"] == 2  # scope_channel_map + tester_port


def test_no_project_dir_exit2(tmp_path: Path):
    rc, _ = _run(str(tmp_path / "nonexistent"), json_out=False)
    assert rc == 2


def test_help():
    r = subprocess.run([sys.executable, str(PROG), "--help"], capture_output=True, text=True)
    assert r.returncode == 0
    assert "project_dir" in r.stdout


# ── FPGA-skip disclosure exemption (#607 shared predicate) ─────────────
# Measured on the real spm x ihp-sg13g2 campaign: rig_topology.json never
# existed (no FPGA board was ever part of this ASIC PDK sign-off run), so
# this gate hard-FAILed a project whose OWN run already discloses, in the
# established #607 shape, that no hardware rig is involved at all. A
# requirement for hardware wiring is meaningless when there is no hardware.

def _write_fpga_audit(project: Path, verdict: str, sof_present,
                      skip_reason: str = "not_attempted") -> None:
    """GATEKEEPER NARROWING: the cause is now an explicit field. `verdict:
    SKIP` alone is emitted for every non-PASS cause alike — including an FPGA
    path that WAS attempted and was blocked by a missing prerequisite, which
    is 12 of the 32 published audits and is somebody's bug, not an absence of
    hardware. Fixtures that mean "no FPGA is part of this run" now say so."""
    d = project / "reports" / "phase2" / "fpga"
    d.mkdir(parents=True, exist_ok=True)
    (d / "quartus_map_audit.json").write_text(json.dumps(
        {"verdict": verdict, "sof_present": sof_present,
         "skip_reason": skip_reason}))


def test_disclosed_fpga_skip_exempts_missing_topology(tmp_path: Path):
    """DIRECTION 2 — the organic case: a genuine #607 disclosed skip."""
    _write_fpga_audit(tmp_path, "SKIP", False)
    rc, out = _run(str(tmp_path))
    assert rc == 0, out
    assert out["verdict"] == "PASS"
    assert out["errors"] == 0
    assert any(f["rule"] == "rig_topology_na_no_fpga_run" for f in out["findings"])


def test_no_audit_file_at_all_still_fails(tmp_path: Path):
    """DIRECTION 1 — no disclosure exists (the pre-existing default
    behaviour, unchanged): still FAIL."""
    rc, out = _run(str(tmp_path))
    assert rc == 1, out
    assert out["verdict"] == "FAIL"


def test_fpga_genuinely_compiled_still_fails(tmp_path: Path):
    """DIRECTION 1 — FPGA bring-up IS part of this run (sof_present=True):
    the exemption must NOT fire, and a missing rig topology is a real gap."""
    _write_fpga_audit(tmp_path, "PASS", True)
    rc, out = _run(str(tmp_path))
    assert rc == 1, out
    assert out["verdict"] == "FAIL"


def test_non_skip_verdict_still_fails(tmp_path: Path):
    """DIRECTION 1 — an undisclosed/ambiguous state (verdict != SKIP) must
    not be read as an exemption."""
    _write_fpga_audit(tmp_path, "ERROR", False)
    rc, out = _run(str(tmp_path))
    assert rc == 1, out
    assert out["verdict"] == "FAIL"


def test_malformed_audit_json_still_fails(tmp_path: Path):
    """DIRECTION 1 — an unreadable audit file must not be silently treated
    as a disclosure; fail-closed, matching fpga_board_capability's own
    contract."""
    d = tmp_path / "reports" / "phase2" / "fpga"
    d.mkdir(parents=True)
    (d / "quartus_map_audit.json").write_text("{not valid json")
    rc, out = _run(str(tmp_path))
    assert rc == 1, out


def test_a_declared_topology_still_validates_normally_when_fpga_skipped(tmp_path: Path):
    """DIRECTION 1 sibling: if a project DOES declare a topology even while
    FPGA is disclosed-skipped, the exemption must not short-circuit real
    field validation — a present-but-broken declaration still fails on its
    own merits."""
    _write_fpga_audit(tmp_path, "SKIP", False)
    (tmp_path / "rig_topology.json").write_text(json.dumps({"fpga_board": "x"}))
    rc, out = _run(str(tmp_path))
    assert rc == 1, out
    assert out["verdict"] == "FAIL"
    assert any(f["rule"] == "rig_topology_missing_required" for f in out["findings"])


# ── GATEKEEPER ADDITION (Step-2.7 adversarial review of the PR) ─────────────
# The PR read `verdict: SKIP, sof_present: false` as "this run honestly
# discloses no FPGA board is part of it". MEASURED against the writer and the
# published corpus, that is not what the file means.
#
#   design_one_shot_runner:
#       sof_present = bool(step and step.status == "PASS" and step.detail)
#       "verdict": "PASS" if sof_present else "SKIP"
#
# so SKIP is emitted for EVERY non-PASS cause. Over the 32 published audits:
#
#       20  evidence "fpga_compile not run"                  never attempted
#       12  evidence "qsf missing — caller must produce it"   ATTEMPTED, blocked
#
# The second group is somebody's bug. Waiving the rig-topology requirement on
# it would waive a requirement on the strength of a defect — in 12 of 32
# published cells. The cause is now a FIELD, and the predicate reads it.
import json as _json                                            # noqa: E402
import sys as _sys                                              # noqa: E402
from pathlib import Path as _Path                               # noqa: E402

_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
import fpga_board_capability as _CAP                            # noqa: E402


def _audit(tmp_path, **fields):
    p = tmp_path / "reports" / "phase2" / "fpga" / "quartus_map_audit.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_json.dumps(fields))
    return tmp_path


def test_never_attempted_is_a_real_disclosure(tmp_path):
    """THE LOAD-BEARING CASE the PR is for: no FPGA was part of this run."""
    d = _audit(tmp_path, verdict="SKIP", sof_present=False,
               skip_reason="not_attempted")
    assert _CAP.fpga_absent_from_run(d) is True


def test_attempted_but_blocked_is_NOT_a_disclosure(tmp_path):
    """THE PAIRED HALF, and the whole reason for the narrowing. The FPGA path
    ran and was blocked by a prerequisite the caller owed. That is a defect,
    not an absence of hardware, and it must not waive anything."""
    d = _audit(tmp_path, verdict="SKIP", sof_present=False,
               skip_reason="attempted_incomplete")
    assert _CAP.fpga_absent_from_run(d) is False


def test_a_legacy_audit_without_a_reason_fails_closed(tmp_path):
    """All 32 published audits predate the field. Not saying WHICH cause is
    not a disclosure — the same rule the missing-file branch already
    follows, applied to a file that exists but does not say enough."""
    d = _audit(tmp_path, verdict="SKIP", sof_present=False)
    assert _CAP.fpga_absent_from_run(d) is False


def test_a_compiled_fpga_is_never_a_skip(tmp_path):
    d = _audit(tmp_path, verdict="PASS", sof_present=True, skip_reason=None)
    assert _CAP.fpga_absent_from_run(d) is False


def test_the_writer_records_the_cause_it_actually_had():
    """The field is only worth reading if the producer sets it correctly, and
    it is derived from the SAME expression that decides `sof_present` — a step
    object that is absent means never attempted, one that exists and did not
    PASS means attempted."""
    src = (_Path(__file__).resolve().parent.parent
           / "design_one_shot_runner.py").read_text()
    assert '"skip_reason": (None if sof_present' in src, "writer not wired"
    assert 'else "not_attempted" if fpga_compile_step is None' in src
    assert 'else "attempted_incomplete")' in src
