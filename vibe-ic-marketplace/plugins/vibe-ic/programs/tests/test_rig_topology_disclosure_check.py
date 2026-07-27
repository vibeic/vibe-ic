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

def _write_fpga_audit(project: Path, verdict: str, sof_present) -> None:
    d = project / "reports" / "phase2" / "fpga"
    d.mkdir(parents=True, exist_ok=True)
    (d / "quartus_map_audit.json").write_text(json.dumps(
        {"verdict": verdict, "sof_present": sof_present}))


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
