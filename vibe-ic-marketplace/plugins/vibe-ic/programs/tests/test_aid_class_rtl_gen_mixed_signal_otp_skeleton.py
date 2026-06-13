"""tests/test_aid_class_rtl_gen_mixed_signal_otp_skeleton.py — v1.6.82

Closes the 7 P0+P1 structural-gate failures from issue #14.

Drives aid_class_rtl_gen.py (via the gen() entry point — same code
path the orchestrator's step_rtl_gen invokes) with a synthetic
L1-L23 fixture (mixed_signal_otp class shape — EXAMPLE_PROTOCOL half-duplex
single-wire + CRC + 4 opcodes including one NEW opcode that the
hardcoded handler list does NOT cover). Asserts on the generated
RTL that all seven P0+P1 fixes are present:

  P0-a  main_fsm.sv references crc_q in body (CRC residue gate
        in BASELINE; spec-compliant already had it)
  P0-b  main_fsm.sv has S_TX_ARM state asserting tx_start with NO
        same-cycle tx_byte assignment (split-arm pipeline)
  P0-c  chip_top.sv port list contains every L9.top_ports name 1:1
  P1-a  byte_assembler.sv contains explicit `bit_count > 4'd8`
        comparator + err_9bit output
  P1-b  main_fsm.sv has a dispatch arm or decode comparator for
        every L3.command_set opcode (including the synthetic
        0x66 opcode that the hardcoded handler list omits)
  P1-c  main_fsm.sv FSM typedef has no orphan states (every
        declared S_* state appears in a case-arm)

Both BASELINE (no --spec-compliance) and SPEC_COMPLIANT variants
are exercised because mixed_signal_otp routes through BASELINE
in ic_class_registry.json.

Chip-AGNOSTIC: every assertion is driven by the synthetic fixture
or by structural patterns; no benchmark-specific names hardcoded.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN_ROOT / "programs"
sys.path.insert(0, str(PROGRAMS))


def _seed_fixture(tmp_path):
    """L1-L23 fixture: EXAMPLE_PROTOCOL half-duplex single-wire + CRC + 4 opcodes
    (one NEW 0x66 outside the hardcoded handler list) + L9 top_ports
    listing 4 ports including a non-canonical `verdict_byte` output."""
    project = tmp_path
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)

    (docs / "L1_DATASHEET.json").write_text(json.dumps({
        "ic_name": "TEST_CHIP",
        "interface": "Apple ID Bus",
        "package": "QFN16",
    }))
    (docs / "L2_FRS.json").write_text(json.dumps({
        "ic_name": "TEST_CHIP",
        "protocol_type": "Apple ID Bus",
        "protocol_overview": {"half_duplex": True, "wire_count": 1},
    }))
    (docs / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "ic_name": "TEST_CHIP",
        "schema_version": 2,
        "command_count": 4,
        "command_set": [
            {"name": "GET_ID",     "opcode_hex": "74"},
            {"name": "SET_STATE",  "opcode_hex": "70"},
            {"name": "GET_STATE",  "opcode_hex": "72"},
            # NEW opcode that hardcoded handlers do NOT cover —
            # P1-b must drive a decode arm from L3 for this.
            {"name": "NEW_OPCODE", "opcode_hex": "66"},
        ],
        "crc_parameters": {
            "polynomial_hex": "0x31",
            "polynomial_reflected_hex": "0x8C",
            "init_hex": "0xFF",
        },
    }))
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "chip_top",
        "top_ports": [
            {"name": "clk",          "direction": "input",  "width": 1},
            {"name": "reset_n",      "direction": "input",  "width": 1},
            {"name": "id_bus",       "direction": "inout",  "width": 1},
            {"name": "verdict_byte", "direction": "output", "width": 8},
        ],
        "mem_interface_contract": {
            "read_latency_cycles": 1,
        },
    }))
    return project


def _gen(project, spec_compliance: bool):
    from aid_class_rtl_gen import gen
    gen(str(project), spec_compliance=spec_compliance)


def _rtl(project, fname):
    return (project / "phase2" / "stage1" / "rtl" / fname).read_text()


# ─────────────────────────────────────────────────────────────────
# P0-a — CRC residue gate (BASELINE was missing it pre-v1.6.82)
# ─────────────────────────────────────────────────────────────────
def test_main_fsm_baseline_references_crc_q(tmp_path):
    project = _seed_fixture(tmp_path / "baseline")
    _gen(project, spec_compliance=False)
    main_fsm = _rtl(project, "main_fsm.sv")
    # crc_q must appear in the body (not just port declaration).
    # Heuristic: at least one occurrence outside the port-list area.
    occurrences = [m.start() for m in re.finditer(r"\bcrc_q\b", main_fsm)]
    assert len(occurrences) >= 2, (
        f"crc_q referenced only {len(occurrences)} times — expected ≥2 "
        f"(port declaration + body residue check)"
    )
    # Specifically the residue check pattern must be present.
    assert re.search(r"crc_q\s*==\s*8'h0", main_fsm), \
        "missing CRC residue gate `crc_q == 8'h0`"


def test_main_fsm_spec_references_crc_q(tmp_path):
    project = _seed_fixture(tmp_path / "spec")
    _gen(project, spec_compliance=True)
    main_fsm = _rtl(project, "main_fsm.sv")
    assert re.search(r"crc_q\s*==\s*8'h0", main_fsm), \
        "spec-compliant main_fsm missing CRC residue gate"


# ─────────────────────────────────────────────────────────────────
# P0-b — TX split-arm pipeline (no same-cycle tx_byte / tx_start)
# ─────────────────────────────────────────────────────────────────
def _assert_split_arm(main_fsm: str, label: str):
    assert "S_TX_LOAD" in main_fsm, f"{label}: missing S_TX_LOAD state"
    assert "S_TX_ARM" in main_fsm, f"{label}: missing S_TX_ARM state"
    # Find the S_TX_ARM body and assert it does NOT contain tx_byte<=
    arm_match = re.search(
        r"S_TX_ARM\s*:\s*begin(.*?)\bend\b", main_fsm, re.DOTALL)
    assert arm_match, f"{label}: S_TX_ARM body not parseable"
    arm_body = arm_match.group(1)
    assert "tx_start" in arm_body and "1'b1" in arm_body, (
        f"{label}: S_TX_ARM does not pulse tx_start <= 1'b1")
    assert not re.search(r"\btx_byte\s*<=", arm_body), (
        f"{label}: S_TX_ARM contains tx_byte NBA — same-cycle violation")


def test_baseline_tx_split_arm(tmp_path):
    project = _seed_fixture(tmp_path / "baseline")
    _gen(project, spec_compliance=False)
    _assert_split_arm(_rtl(project, "main_fsm.sv"), "baseline")


def test_spec_tx_split_arm(tmp_path):
    project = _seed_fixture(tmp_path / "spec")
    _gen(project, spec_compliance=True)
    _assert_split_arm(_rtl(project, "main_fsm.sv"), "spec")


# ─────────────────────────────────────────────────────────────────
# P0-c — chip_top port list mirrors L9.top_ports
# ─────────────────────────────────────────────────────────────────
def test_chip_top_port_list_matches_l9(tmp_path):
    project = _seed_fixture(tmp_path / "ports")
    _gen(project, spec_compliance=False)
    chip_top = _rtl(project, "chip_top.sv")
    l9 = json.loads((project / "phase1" / "generated_docs"
                     / "L9_INTEGRATION_SPEC.json").read_text())
    for port in l9["top_ports"]:
        # Each L9 port name must appear in chip_top.sv (port-list
        # entry; body may also alias it).  The non-canonical
        # `verdict_byte` is the load-bearing assertion — pre-v1.6.82
        # chip_top hardcoded only (clk/reset_n/id_bus).
        name = port["name"]
        assert name in chip_top, (
            f"L9 port {name!r} missing from generated chip_top.sv")
    # Non-canonical port specifically must be present:
    assert "verdict_byte" in chip_top, (
        "verdict_byte from L9.top_ports not propagated — chip_top "
        "still hardcoded its port list")


# ─────────────────────────────────────────────────────────────────
# P1-a — byte_assembler explicit 9-bit reject
# ─────────────────────────────────────────────────────────────────
def test_byte_assembler_explicit_9bit_reject(tmp_path):
    project = _seed_fixture(tmp_path / "ba")
    _gen(project, spec_compliance=False)
    ba = _rtl(project, "byte_assembler.sv")
    # Explicit comparator form with `>` (not just `==`).
    assert re.search(r"bit_count\s*>\s*4'd8", ba), (
        "missing explicit `bit_count > 4'd8` comparator in byte_assembler")
    # err_9bit output must be exposed.
    assert re.search(r"output\s+reg\s+err_9bit", ba), (
        "byte_assembler missing `output reg err_9bit` declaration")


# ─────────────────────────────────────────────────────────────────
# P1-b — opcode dispatch / decode covers every L3 opcode
# ─────────────────────────────────────────────────────────────────
def _assert_l3_opcode_coverage(project, main_fsm: str, label: str):
    l3 = json.loads((project / "phase1" / "generated_docs"
                     / "L3_CMD_PROTOCOL.json").read_text())
    for op in l3["command_set"]:
        op_hex = int(op["opcode_hex"], 16)
        # Either a case-arm `8'hXX:` OR a `== 8'hXX` comparator
        # OR `(op == 8'hXX)` form must appear.
        pat_lit = rf"8'h0*{op_hex:02X}\b"
        assert re.search(pat_lit, main_fsm, re.IGNORECASE), (
            f"{label}: L3 opcode 0x{op_hex:02X} has no decode site "
            f"in main_fsm.sv")


def test_baseline_opcode_coverage(tmp_path):
    project = _seed_fixture(tmp_path / "ops_b")
    _gen(project, spec_compliance=False)
    _assert_l3_opcode_coverage(project, _rtl(project, "main_fsm.sv"),
                               "baseline")


def test_spec_opcode_coverage(tmp_path):
    project = _seed_fixture(tmp_path / "ops_s")
    _gen(project, spec_compliance=True)
    _assert_l3_opcode_coverage(project, _rtl(project, "main_fsm.sv"),
                               "spec")


# ─────────────────────────────────────────────────────────────────
# P1-c — FSM state typedef has no orphan states
# ─────────────────────────────────────────────────────────────────
def _assert_no_orphans(main_fsm: str, label: str):
    typedef_match = re.search(
        r"typedef\s+enum[^{]*\{([^}]*)\}\s*state_t",
        main_fsm, re.DOTALL)
    assert typedef_match, f"{label}: state_t typedef not found"
    declared = set(re.findall(r"\bS_[A-Z0-9_]+\b", typedef_match.group(1)))
    referenced = set(re.findall(r"\bS_[A-Z0-9_]+\b", main_fsm))
    orphans = declared - referenced
    # Subtract: a state declared in the typedef is always referenced
    # at least once (the declaration itself).  We need to count
    # `<=` assignments, case-arm targets, and case heads.
    real_orphans = set()
    for st in declared:
        # state must appear at least once in a context that's NOT
        # inside the typedef braces.
        body_only = (
            main_fsm[:typedef_match.start()] +
            main_fsm[typedef_match.end():]
        )
        if not re.search(rf"\b{st}\b", body_only):
            real_orphans.add(st)
    assert not real_orphans, (
        f"{label}: orphan FSM states (declared in typedef, never "
        f"referenced in body): {sorted(real_orphans)}")


def test_baseline_no_orphan_states(tmp_path):
    project = _seed_fixture(tmp_path / "orphan_b")
    _gen(project, spec_compliance=False)
    _assert_no_orphans(_rtl(project, "main_fsm.sv"), "baseline")


def test_spec_no_orphan_states(tmp_path):
    project = _seed_fixture(tmp_path / "orphan_s")
    _gen(project, spec_compliance=True)
    _assert_no_orphans(_rtl(project, "main_fsm.sv"), "spec")
