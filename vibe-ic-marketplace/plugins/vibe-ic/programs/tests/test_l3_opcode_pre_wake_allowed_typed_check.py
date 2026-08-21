"""tests/test_l3_opcode_pre_wake_allowed_typed_check.py
Wave 37 (v0.119.69) — BACKLOG v0.119.70 Item 3a.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (
    Path(__file__).resolve().parent.parent / "l3_opcode_pre_wake_allowed_typed_check.py"
)


def _run(project: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _aid_l1_l2(project: Path) -> None:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps({
        "ic_name": "EXAMPLE_PROTOCOL-X",
        "interface": "EXAMPLE_PROTOCOL single-wire half-duplex",
    }))
    (gd / "L2_FRS.json").write_text(json.dumps({
        "ic_name": "EXAMPLE_PROTOCOL-X",
        "protocol_type": "single_wire_half_duplex",
    }))


def _aid_l6(project: Path, with_wake: bool) -> None:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    body = {
        "ic_name": "EXAMPLE_PROTOCOL-X",
        "fsm_states": [{"name": "IDLE"}],
    }
    if with_wake:
        body["wake_gating"] = {"awake_latch_on": "0x74"}
    (gd / "L6_CONTROL_LOGIC.json").write_text(json.dumps(body))


def _l3(project: Path, with_pre_wake: bool, *,
        wrong_type: bool = False) -> None:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    op_get_id: dict = {"hex": "0x74", "name": "GET_ID"}
    op_write: dict = {"hex": "0xE2", "name": "WRITE"}
    if with_pre_wake:
        op_get_id["pre_wake_allowed"] = True
        op_write["pre_wake_allowed"] = False
    if wrong_type:
        op_get_id["pre_wake_allowed"] = "true"  # string, not bool
        op_write["pre_wake_allowed"] = 0
    (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "ic_name": "EXAMPLE_PROTOCOL-X",
        "physical_layer": "EXAMPLE_PROTOCOL half-duplex single-wire",
        "opcodes": [op_get_id, op_write],
    }))


# 1. PASS — wake-gated chip with typed pre_wake_allowed
def test_pass_wake_gated_with_typed(tmp_path: Path):
    project = tmp_path / "aid_pass"
    project.mkdir(parents=True, exist_ok=True)
    _aid_l1_l2(project)
    _aid_l6(project, with_wake=True)
    _l3(project, with_pre_wake=True)
    r = _run(project)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


# 2. FAIL — wake-gated chip but L3 missing pre_wake_allowed
def test_fail_wake_gated_missing_field(tmp_path: Path):
    project = tmp_path / "aid_fail"
    project.mkdir(parents=True, exist_ok=True)
    _aid_l1_l2(project)
    _aid_l6(project, with_wake=True)
    _l3(project, with_pre_wake=False)
    r = _run(project)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "missing typed field" in r.stdout


# 3. SKIP — IC has no wake gating
def test_skip_no_wake_gating(tmp_path: Path):
    project = tmp_path / "aid_no_wake"
    project.mkdir(parents=True, exist_ok=True)
    _aid_l1_l2(project)
    _aid_l6(project, with_wake=False)
    _l3(project, with_pre_wake=False)
    r = _run(project)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP" in r.stdout


# 4. SKIP — pure_analog
def test_skip_pure_analog(tmp_path: Path):
    project = tmp_path / "pmic"
    project.mkdir(parents=True, exist_ok=True)
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps({
        "ic_name": "PMIC-X", "interface": "pure analog",
    }))
    (gd / "L2_FRS.json").write_text(json.dumps({
        "ic_name": "PMIC-X", "interface": "pure analog",
    }))
    (gd / "L5_ADI_SPEC.json").write_text(json.dumps({
        "ic_name": "PMIC-X",
        "analog_blocks": [{"name": "BANDGAP_REF"}],
    }))
    r = _run(project)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP" in r.stdout


# 5. FAIL — wrong type
def test_fail_wrong_type(tmp_path: Path):
    project = tmp_path / "aid_wrong_type"
    project.mkdir(parents=True, exist_ok=True)
    _aid_l1_l2(project)
    _aid_l6(project, with_wake=True)
    _l3(project, with_pre_wake=False, wrong_type=True)
    r = _run(project)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "must be bool" in r.stdout


# 6. Wave 42 / MF1 — unknown class with L3 opcodes + L6 wake gating
#    must NOT auto-SKIP on ic_class.
def test_unknown_class_fail_closed_when_evidence_present(tmp_path: Path):
    """L1/L2 absent → ic_class=unknown.  But L3 still has opcodes
    (no pre_wake_allowed) and L6 has wake_gating.  Gate must FAIL,
    not auto-SKIP on ic_class=unknown."""
    project = tmp_path / "unknown_evidence"
    project.mkdir(parents=True, exist_ok=True)
    # No L1/L2 → unknown.
    _aid_l6(project, with_wake=True)
    _l3(project, with_pre_wake=False)
    r = _run(project)
    out = r.stdout + r.stderr
    assert "SKIP — ic_class=unknown not in applicable set" not in out, (
        f"MF1 broken: unknown class auto-SKIPped\n{out}")
