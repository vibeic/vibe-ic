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
