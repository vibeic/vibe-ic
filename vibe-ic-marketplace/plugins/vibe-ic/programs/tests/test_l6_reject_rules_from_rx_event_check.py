"""tests/test_l6_reject_rules_from_rx_event_check.py
Wave 37 (v0.119.69) — BACKLOG v0.119.70 Item 3b.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (
    Path(__file__).resolve().parent.parent / "l6_reject_rules_from_rx_event_check.py"
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


def _l6(project: Path, *, with_wake: bool, reject_rules=None) -> None:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    body = {"ic_name": "EXAMPLE_PROTOCOL-X", "fsm_states": [{"name": "IDLE"}]}
    if with_wake:
        body["wake_gating"] = {"awake_latch_on": "0x74"}
    if reject_rules is not None:
        body["reject_rules"] = reject_rules
    (gd / "L6_CONTROL_LOGIC.json").write_text(json.dumps(body))


def _l3(project: Path, *, with_pre_wake_false: bool) -> None:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    op_get_id: dict = {
        "hex": "0x74", "name": "GET_ID",
        "pre_wake_allowed": True,
    }
    op_write: dict = {"hex": "0xE2", "name": "WRITE"}
    if with_pre_wake_false:
        op_write["pre_wake_allowed"] = False
    else:
        op_write["pre_wake_allowed"] = True
    (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "ic_name": "EXAMPLE_PROTOCOL-X",
        "physical_layer": "EXAMPLE_PROTOCOL half-duplex single-wire",
        "opcodes": [op_get_id, op_write],
    }))


# 1. PASS — wake-gated chip, pre_wake_allowed=false opcode exists,
#           reject rule references pre-wake whitelist.
def test_pass_pre_wake_reject_present(tmp_path: Path):
    project = tmp_path / "aid_pass"
    project.mkdir(parents=True, exist_ok=True)
    _aid_l1_l2(project)
    _l6(project, with_wake=True, reject_rules=[
        "pre-wake opcode not in pre_wake whitelist => reject",
        "bit count not multiple of 8 => discard frame",
    ])
    _l3(project, with_pre_wake_false=True)
    r = _run(project)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


# 2. FAIL — wake-gated + pre_wake_false opcode, but no reject rule.
def test_fail_no_reject_rule(tmp_path: Path):
    project = tmp_path / "aid_fail"
    project.mkdir(parents=True, exist_ok=True)
    _aid_l1_l2(project)
    _l6(project, with_wake=True, reject_rules=[
        "bit count not multiple of 8 => discard frame",
    ])
    _l3(project, with_pre_wake_false=True)
    r = _run(project)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout


# 3. SKIP — no wake gating
def test_skip_no_wake_gating(tmp_path: Path):
    project = tmp_path / "aid_no_wake"
    project.mkdir(parents=True, exist_ok=True)
    _aid_l1_l2(project)
    _l6(project, with_wake=False)
    _l3(project, with_pre_wake_false=True)
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


# 5. SKIP — no opcode marks pre_wake_allowed=false
def test_skip_no_pre_wake_false(tmp_path: Path):
    project = tmp_path / "aid_no_false"
    project.mkdir(parents=True, exist_ok=True)
    _aid_l1_l2(project)
    _l6(project, with_wake=True, reject_rules=[
        "bit count not multiple of 8 => discard frame",
    ])
    _l3(project, with_pre_wake_false=False)  # all opcodes True
    r = _run(project)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP" in r.stdout


# 6. PASS — alternative wording (awake_latch=0 ... reject)
def test_pass_alt_wording(tmp_path: Path):
    project = tmp_path / "aid_alt"
    project.mkdir(parents=True, exist_ok=True)
    _aid_l1_l2(project)
    _l6(project, with_wake=True, reject_rules=[
        "if awake_latch == 0 and opcode != GET_ID then reject frame",
    ])
    _l3(project, with_pre_wake_false=True)
    r = _run(project)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


# 7. Waiver
def test_waiver(tmp_path: Path):
    project = tmp_path / "aid_waiver"
    project.mkdir(parents=True, exist_ok=True)
    _aid_l1_l2(project)
    _l6(project, with_wake=True, reject_rules=[
        "bit count not multiple of 8 => discard frame",
    ])
    _l3(project, with_pre_wake_false=True)
    (project / "waivers.json").write_text(json.dumps({
        "l6_pre_wake_reject_rule_intentional":
            "Reject path is implemented in dispatcher RTL via "
            "wake_immune function; L6 keeps the global gate and "
            "the per-opcode whitelist is encoded in L3."
    }))
    r = _run(project)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS_WITH_WAIVER" in r.stdout
