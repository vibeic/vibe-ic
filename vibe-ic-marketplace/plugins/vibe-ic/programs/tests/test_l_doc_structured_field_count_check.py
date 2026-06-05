#!/usr/bin/env python3
"""Tests for l_doc_structured_field_count_check.py (Wave 31)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROG = Path(__file__).resolve().parent.parent / \
    "l_doc_structured_field_count_check.py"


def _run(project: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _put(project: Path, name: str, data: dict):
    d = project / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(data, ensure_ascii=False, indent=2))


def _well_typed_l_docs(project: Path):
    # L1 — 12 typed scalar fields
    l1 = {f"f{i}": f"value{i}" for i in range(12)}
    l1["extraction_evidence"] = []
    _put(project, "L1_DATASHEET.json", l1)
    # L2 — 16 typed scalar fields
    l2 = {f"k{i}": i for i in range(16)}
    _put(project, "L2_FRS.json", l2)
    # L3 — 5 opcodes + crc_parameters
    _put(project, "L3_CMD_PROTOCOL.json", {
        "opcodes": [
            {"hex": f"0x{70+i:02x}", "name": f"OP{i}",
             "response_hex": f"0x{71+i:02x}",
             "payload_bytes": [], "response_payload_bytes": []}
            for i in range(5)
        ],
        "crc_parameters": {
            "polynomial_hex": "0x31", "init_hex": "0xFF",
            "bit_order": "lsb_first",
        },
    })
    # L4 — 5 registers
    _put(project, "L4_REGMAP.json", {
        "registers": [
            {"name": f"R{i}", "address": f"0x{i:02x}", "bits": "[7:0]",
             "default": "0x00", "description": "x"} for i in range(5)
        ],
    })
    # L5 — no_analog
    _put(project, "L5_ADI_SPEC.json", {"no_analog": True})
    # L6 — 5 fsm_states
    _put(project, "L6_CONTROL_LOGIC.json", {
        "fsm_states": [
            {"name": f"S_{i}", "transitions": [], "actions": []}
            for i in range(5)
        ],
    })
    # L7 — 3 scenarios
    _put(project, "L7_TEST_DEBUG.json", {
        "test_scenarios": [{"name": f"T{i}"} for i in range(3)],
    })
    # L8 — 12 timing fields
    l8 = {"timing_parameters": {f"t{i}_us": i for i in range(12)}}
    _put(project, "L8_TIMING_WAVEFORM.json", l8)
    # L9 — top + fsm + ports
    _put(project, "L9_INTEGRATION_SPEC.json", {
        "top_module": "chip_top",
        "fsm_states": [{"name": "S_IDLE"}],
        "ports": [{"name": "clk", "dir": "input"}],
    })
    # L10 — 5 cases
    _put(project, "L10_TEST_CASES.json", {
        "test_cases": [{"name": f"TC{i}"} for i in range(5)],
    })
    # L11 — 3 sequences
    _put(project, "L11_OTP_CONTENT.json", {
        "sequences": [{"name": f"SEQ{i}"} for i in range(3)],
    })
    # L12 — no_calibration
    _put(project, "L12_BEHAVIORAL_SEQUENCES.json", {"no_calibration": True})
    # L13 — 5 cases
    _put(project, "L13_LAB_CALIBRATION.json", {
        "test_cases": [{"name": f"LC{i}"} for i in range(5)],
    })


def test_all_l_docs_well_typed_pass(tmp_path):
    _well_typed_l_docs(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_l3_no_opcodes_fail(tmp_path):
    # v0.2.55: the L3 ≥5-opcode floor applies ONLY to command-driven classes.
    # A doc with ZERO opcodes also flips the detected class to a non-command
    # datapath primitive (digital_arithmetic_primitive), for which the L3
    # opcode floor is correctly N/A — so we keep the IC command-driven by
    # leaving 2 real opcodes (enough for _l3_has_commands → digital_cmd_driven)
    # but below the ≥5 floor, which is the genuine "command IC with too few
    # opcodes → FAIL" path this test means to assert.
    _well_typed_l_docs(tmp_path)
    _put(tmp_path, "L3_CMD_PROTOCOL.json", {
        "opcodes": [
            {"hex": "0x70", "name": "OP_A", "payload_bytes": 1},
            {"hex": "0x72", "name": "OP_B", "payload_bytes": 1},
        ],
        "extraction_evidence": [{"file": "x", "line": 1}],
    })
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "L3_CMD_PROTOCOL" in r.stdout
    # L3 command-protocol-doc insufficiency for a command-driven IC: either the
    # opcode floor or the required crc_parameters block. Both are command-
    # protocol-doc requirements that an arithmetic primitive would (correctly)
    # be exempt from, but a digital_cmd_driven IC must satisfy.
    low = r.stdout.lower()
    assert "opcode" in low or "crc" in low


def test_l8_few_timing_fail(tmp_path):
    _well_typed_l_docs(tmp_path)
    _put(tmp_path, "L8_TIMING_WAVEFORM.json", {
        "timing_parameters": {"t0_us": 1},
    })
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "L8" in r.stdout


def test_no_l_docs_skip(tmp_path):
    # No generated_docs/, no input/docs/.
    r = _run(tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr


def test_wired_into_structural_rtl_gates():
    fcc = Path(__file__).resolve().parent.parent / \
        "flow_compliance_check.py"
    txt = fcc.read_text()
    assert "l_doc_structured_field_count_check" in txt


def test_wave35_l8_constants_list_pass(tmp_path):
    """Wave 35: agents that emit L8 as `constants: [{name, value}, ...]`
    list-of-dicts schema must PASS — each entry counts as one typed
    timing constant.
    """
    _well_typed_l_docs(tmp_path)
    _put(tmp_path, "L8_RTL_CONSTANTS.json", {
        "extraction_evidence": [{"file": "x", "line": 1}],
        "constants": [
            {"name": f"T{i}", "value": i, "type": "int"}
            for i in range(12)
        ],
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_wave35_l8_typed_dict_sidecar_pass(tmp_path):
    """Wave 35: L8_TIMING_WAVEFORM sidecar with typed dict sub-sections
    (clock{}, rx_classifier{}, tx_widths_ticks{}, etc) must PASS even
    without flat `timing_parameters` field.
    """
    _well_typed_l_docs(tmp_path)
    _put(tmp_path, "L8_TIMING_WAVEFORM.json", {
        "extraction_evidence": [{"file": "x", "line": 1}],
        "clock": {"freq_hz": 50000000, "period_ns": 20},
        "rx_classifier": {"H1_MIN": 1, "H1_MAX": 192, "BR_MIN": 613,
                          "IBT_MIN": 274},
        "tx_widths_ticks": {"T_BIT0_LOW": 355, "T_BIT0_HIGH": 85,
                            "T_BIT1_LOW": 90, "T_BIT1_HIGH": 350},
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_wave35_l4_logical_regions_pass(tmp_path):
    """Wave 35: L4 with `logical_regions[]` (OTP-image schema) must PASS
    as an alternative to `registers[]`/`otp_layout{}`.
    """
    _well_typed_l_docs(tmp_path)
    _put(tmp_path, "L4_REGMAP.json", {
        "extraction_evidence": [{"file": "x", "line": 1}],
        "logical_regions": [
            {"name": f"region_{i}", "addr": f"0x{i:02X}", "len": 8}
            for i in range(6)
        ],
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_wave35_l6_fsms_container_pass(tmp_path):
    """Wave 35: L6 with `fsms: [{name, states[]}, ...]` multi-FSM
    container must PASS by summing total states across all enumerated
    FSMs.
    """
    _well_typed_l_docs(tmp_path)
    _put(tmp_path, "L6_CONTROL_LOGIC.json", {
        "extraction_evidence": [{"file": "x", "line": 1}],
        "fsms": [
            {"name": "main",
             "states": [{"name": f"S{i}"} for i in range(6)]},
        ],
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_wave35_l9_submodules_pass(tmp_path):
    """Wave 35: L9 integration spec with `submodules[]` instead of
    `fsm_states[]` must PASS (top_module + ports + submodules >= 3
    typed structural fields).
    """
    _well_typed_l_docs(tmp_path)
    _put(tmp_path, "L9_INTEGRATION_SPEC.json", {
        "extraction_evidence": [{"file": "x", "line": 1}],
        "top_module": "chip_top",
        "top_ports": [{"name": "clk", "dir": "input", "width": 1}],
        "submodules": [{"inst": "u_x", "module": "x"}],
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
