"""tests/test_phase1_issue6_multi_layer_hardcode.py — v1.6.64

Closes GitHub issue #6 — six independent extractor defects on
L4 / L7 / L8 / L9 / L11 / L13:

  Bug A  L7.test_modes           hardcoded [FUNCTIONAL, TEST_MODE,
                                  ENGINEER_MODE] template
  Bug B  L8.timing_constants     hardcoded 10-entry EXAMPLE_PROTOCOL-protocol
                                  template
  Bug C  L13.calibration_targets hardcoded [VBG, VLDO, fOSC]
                                  placeholders
  Bug D  L4.registers            extractor never fires
  Bug E  L9.top_module_pins      EXAMPLE_PROTOCOL-class hardcoded scaffold even
                                  when L1.pin_table has real pins
  Bug F  L11.otp_layout          empty even when L4.otp_layout
                                  populated for same project

Each test asserts the v1.6.64 fix:

  * For Bugs A/B/C: empty list + `no_X_in_input: true` flag when
    no extraction evidence exists; populated when evidence does
    exist; non-identical across IC classes.
  * For Bug D: the new register-table parser harvests `0xNN  NAME
    R/W  description` rows.
  * For Bug E: when L1.pin_table has real entries, L9.top_module_pins
    promotes them rather than emitting the EXAMPLE_PROTOCOL 3-pin scaffold.
  * For Bug F: when L4.otp_layout has field entries, L11.otp_layout
    mirrors them.
"""
from __future__ import annotations

import json
from pathlib import Path

from programs.phase1_one_shot_runner import (
    gen_l4_regmap,
    gen_l7_test_debug,
    gen_l8_timing_waveform,
    gen_l9_integration_spec,
    gen_l11_otp_content,
    gen_l13_lab_calibration,
)
import pytest

_GEN_DIR = Path("phase1") / "generated_docs"


def _seed(tmp_path: Path, l_docs: dict[str, dict] | None = None) -> Path:
    project = tmp_path
    (project / _GEN_DIR).mkdir(parents=True, exist_ok=True)
    for name, content in (l_docs or {}).items():
        (project / _GEN_DIR / f"{name}.json").write_text(json.dumps(content))
    return project


def _read(project: Path, name: str) -> dict:
    return json.loads((project / _GEN_DIR / f"{name}.json").read_text())


# ---------------------------------------------------------------------------
# Bug A — L7.test_modes
# ---------------------------------------------------------------------------

def test_l7_no_evidence_emits_empty_with_flag(tmp_path: Path) -> None:
    """Block-cipher / hash-core projects have no test-mode concept;
    L7 must NOT emit the FUNCTIONAL/TEST_MODE/ENGINEER_MODE template."""
    project = _seed(tmp_path)
    extracted = {
        "aes_spec.txt": "Verilog AES core. Pure combinational rounds.\n",
    }
    gen_l7_test_debug(project, extracted)
    l7 = _read(project, "L7_TEST_DEBUG")
    assert l7["test_modes"] == []
    assert l7["no_test_modes_in_input"] is True
    # Critical: the v1.6.62 hardcoded template must not appear.
    names = [tm.get("name") for tm in l7["test_modes"]]
    assert "FUNCTIONAL" not in names
    assert "ENGINEER_MODE" not in names


def test_l7_extracts_real_test_modes_from_prose(tmp_path: Path) -> None:
    project = _seed(tmp_path)
    extracted = {
        "datasheet.txt": (
            "Test mode entry: TEST_MODE = 0x40\n"
            "Engineering mode: ENG_MODE = 0x42\n"
            "TM_BURNIN: production-only, requires unlock token.\n"
        ),
    }
    gen_l7_test_debug(project, extracted)
    l7 = _read(project, "L7_TEST_DEBUG")
    names = {tm.get("name") for tm in l7["test_modes"]}
    assert "TEST_MODE" in names
    assert "ENG_MODE" in names or "TM_BURNIN" in names
    assert l7["no_test_modes_in_input"] is False


# ---------------------------------------------------------------------------
# Bug B — L8.timing_constants
# ---------------------------------------------------------------------------

def test_l8_no_evidence_emits_empty_with_flag(tmp_path: Path) -> None:
    """Block cipher has no timing constants; L8 must not emit the
    10-entry EXAMPLE_PROTOCOL-protocol template."""
    project = _seed(tmp_path)
    extracted = {
        "aes_spec.txt": "Verilog AES core. Pure combinational rounds.\n",
    }
    gen_l8_timing_waveform(project, extracted)
    l8 = _read(project, "L8_RTL_CONSTANTS")
    assert l8["timing_constants"] == []
    assert l8["no_timing_constants_in_input"] is True
    # Critical: EXAMPLE_PROTOCOL protocol names must not appear.
    names = [tc.get("name") for tc in l8["timing_constants"]]
    assert "T_BIT0_LOW_TICKS" not in names
    assert "T_WAKE_PULSE_TICKS" not in names


def test_l8_extracts_timing_constants_from_assignments(
        tmp_path: Path) -> None:
    project = _seed(tmp_path)
    extracted = {
        "timing_spec.txt": (
            "T_REFRESH = 7800 ns\n"
            "T_RAS_MIN = 50000 ticks\n"
            "T_RP = 13500 cycles\n"
        ),
    }
    gen_l8_timing_waveform(project, extracted)
    l8 = _read(project, "L8_RTL_CONSTANTS")
    names = {tc.get("name") for tc in l8["timing_constants"]}
    assert "T_REFRESH" in names
    assert "T_RAS_MIN" in names
    assert l8["no_timing_constants_in_input"] is False


# ---------------------------------------------------------------------------
# Bug C — L13.calibration_targets
# ---------------------------------------------------------------------------

def test_l13_no_evidence_emits_empty_with_flag(tmp_path: Path) -> None:
    project = _seed(tmp_path)
    extracted = {
        "aes_spec.txt": "Verilog AES core. Pure digital, no calibration.\n",
    }
    gen_l13_lab_calibration(project, extracted)
    l13 = _read(project, "L13_LAB_CALIBRATION")
    assert l13["calibration_targets"] == []
    assert l13["no_lab_calibration_in_input"] is True
    targets = [t.get("target") for t in l13["calibration_targets"]]
    assert "VBG" not in targets
    assert "VLDO" not in targets
    assert "fOSC" not in targets


def test_l13_extracts_trim_targets(tmp_path: Path) -> None:
    project = _seed(tmp_path)
    extracted = {
        "trim_spec.txt": (
            "TRIM_BANDGAP: 4-bit, ±2%/LSB\n"
            "OSC_TRIM_FREQ: 6-bit\n"
            "VBG = 1.205 V across PVT\n"
        ),
    }
    gen_l13_lab_calibration(project, extracted)
    l13 = _read(project, "L13_LAB_CALIBRATION")
    targets = {t.get("target") for t in l13["calibration_targets"]}
    assert "TRIM_BANDGAP" in targets or "OSC_TRIM_FREQ" in targets
    assert l13["no_lab_calibration_in_input"] is False


def test_l13_emits_both_name_and_target_keys(tmp_path: Path) -> None:
    """v1.6.65 — closes issue-#6 v1.6.64 follow-up Bug C complaint
    that L13 entries showed `name=None` to the verifier. v1.6.65
    emits BOTH `name` AND `target` keys."""
    project = _seed(tmp_path)
    extracted = {
        "trim.txt": "TRIM_BANDGAP: 4-bit\nVBG = 1.205V\n",
    }
    gen_l13_lab_calibration(project, extracted)
    l13 = _read(project, "L13_LAB_CALIBRATION")
    assert len(l13["calibration_targets"]) >= 1
    for entry in l13["calibration_targets"]:
        assert entry.get("name") is not None, \
            f"v1.6.65 must emit `name` key (was: {entry!r})"
        assert entry.get("target") is not None
        assert entry["name"] == entry["target"]


# ---------------------------------------------------------------------------
# Bug D — L4.registers
# ---------------------------------------------------------------------------

def test_l4_extracts_register_rows_whitespace_form(tmp_path: Path) -> None:
    project = _seed(tmp_path)
    extracted = {
        "regmap.txt": (
            "Register map:\n"
            "0x00  CTRL    R/W  control register\n"
            "0x04  STATUS  RO   status flags\n"
            "0x08  DATA    R/W  data input/output\n"
        ),
    }
    gen_l4_regmap(project, extracted)
    l4 = _read(project, "L4_REGMAP")
    names = {r.get("name") for r in l4["registers"]}
    assert "CTRL" in names
    assert "STATUS" in names
    assert "DATA" in names
    assert l4["no_registers_in_input"] is False


def test_l4_extracts_register_rows_pipe_form(tmp_path: Path) -> None:
    project = _seed(tmp_path)
    extracted = {
        "regmap.txt": (
            "0x00 | CFG     | RW | 0x00 | configuration register\n"
            "0x10 | INTMASK | RW | 0xFF | interrupt mask\n"
        ),
    }
    gen_l4_regmap(project, extracted)
    l4 = _read(project, "L4_REGMAP")
    names = {r.get("name") for r in l4["registers"]}
    assert "CFG" in names
    assert "INTMASK" in names


def test_l4_no_evidence_emits_empty_with_flag(tmp_path: Path) -> None:
    project = _seed(tmp_path)
    extracted = {
        "aes_spec.txt": "Pure combinational AES; no MMIO interface.\n",
    }
    gen_l4_regmap(project, extracted)
    l4 = _read(project, "L4_REGMAP")
    assert l4["registers"] == []
    assert l4["no_registers_in_input"] is True


def test_l4_extracts_addr_h_form_example_chip_datasheet(tmp_path: Path) -> None:
    """v1.6.65 — closes issue-#6 v1.6.64 follow-up Bug D. EXAMPLE_CHIP
    datasheet renders registers as `<addr>h (footnote) <NAME>
    <bit-fields>` rather than the canonical `0xNN NAME R/W`
    form. v1.6.67 anchors matches to a register-table header line
    (issue #8 Bug C). Verbatim header + rows from
    extracted_docs/EXAMPLE_CHIP_Short_Datasheet_0v06.txt."""
    project = _seed(tmp_path)
    extracted = {
        "EXAMPLE_CHIP_Short_Datasheet_0v06.txt": (
            "Register Address Map\n"
            "\n"
            "   Addr            Name            <D7>        <D6>"
            "        <D5>      <D4>        <D3>      <D2>"
            "         <D1>     <D0>\n"
            "\n"
            "   80h (1)      POWER_STAT          ovps  ovpr  ocps  "
            "lrl  hot  tst  ocpr  hots\n"
            "   81h (1)      CONTROL             ph    pt    gpm   "
            "gps  rd_dis  -  -  cc_pd_on\n"
        ),
    }
    gen_l4_regmap(project, extracted)
    l4 = _read(project, "L4_REGMAP")
    names = {r.get("name") for r in l4["registers"]}
    assert "POWER_STAT" in names
    # v1.6.67 closes issue-#8 Bug-C: CONTROL is a real register name
    # in many chips and must NO LONGER be rejected by an
    # over-aggressive blocklist.
    assert "CONTROL" in names
    assert l4["no_registers_in_input"] is False
    # Address comes through as 0x80 / 0x81.
    addrs = {r.get("address") for r in l4["registers"]}
    assert "0x80" in addrs
    assert "0x81" in addrs
    # v1.6.67 — bit-fields are now parsed into a typed `bits[]`
    # array rather than left as a single description string.
    pwr = next(r for r in l4["registers"] if r["name"] == "POWER_STAT")
    bit_names = {b["name"] for b in pwr.get("bits", [])}
    assert {"ovps", "ovpr", "ocps", "lrl", "hot",
            "tst", "ocpr", "hots"} <= bit_names


def test_l4_addr_h_form_skips_when_no_header_present(
        tmp_path: Path) -> None:
    """v1.6.67 — the `<addr>h <NAME>` parser must NOT fire on docs
    that have NO register-table header line. Closes issue-#8 Bug C
    sub-symptom: command/response table rows like `E9h  CB1
    CB1_Hash  CB2  CB3` were falsely matching as register rows on
    the EXAMPLE_CHIP datasheet's response-payload section."""
    project = _seed(tmp_path)
    extracted = {
        # No `Addr  Name  <D7>` header — this is a command table.
        "datasheet.txt": (
            "Get Factory Control Bits and Hash:\n"
            "E9h  CB1   CB1_Hash   CB2   CB2_Hash   CB3   CB7_Hash   CRC\n"
            "EBh  LOCK0  LOCK1  LOCK2  00h  CRC\n"
        ),
    }
    gen_l4_regmap(project, extracted)
    l4 = _read(project, "L4_REGMAP")
    # No header → no `_reg_row_re_c` matches → list stays empty.
    names = {r.get("name") for r in l4["registers"]}
    assert "CB1" not in names
    assert "LOCK0" not in names


# ---------------------------------------------------------------------------
# Bug E — L9.top_module_pins promoted from L1
# ---------------------------------------------------------------------------

def test_l9_promotes_l1_pin_table_when_present(tmp_path: Path) -> None:
    """When L1.pin_table carries real extracted pins, L9 must emit
    those — not the EXAMPLE_PROTOCOL-class clk / reset_n / id_bus scaffold."""
    project = _seed(tmp_path, l_docs={
        "L1_DATASHEET": {
            "schema_version": 2,
            "ic_name": "MyDRAMCtrl",
            "pin_table": [
                {"name": "DDR_CLK", "mode": "output", "io_standard": "SSTL"},
                {"name": "DDR_DQ", "mode": "inout", "io_standard": "SSTL"},
                {"name": "DDR_DQS", "mode": "inout", "io_standard": "SSTL"},
                {"name": "DDR_CKE", "mode": "output", "io_standard": "SSTL"},
            ],
        },
    })
    gen_l9_integration_spec(project, {}, l3={})
    l9 = _read(project, "L9_INTEGRATION_SPEC")
    pin_names = {p.get("name") for p in l9["top_module_pins"]}
    # fixture-flip-acknowledged: phase1:DDR_CLK -> ddr_clk
    # v1.6.86 (#18 Bug 1) canonicalises L9 port names to lowercase so
    # they match the RTL emitter's chip_top.sv. Both sides must agree.
    assert "ddr_clk" in pin_names
    assert "ddr_dq" in pin_names
    # EXAMPLE_PROTOCOL scaffold names must NOT appear when L1 provides real pins.
    # (`id_bus` is the EXAMPLE_PROTOCOL scaffold; here L1 carries DDR pins, so the
    # EXAMPLE_PROTOCOL scaffold must not appear.)
    assert not any(n in ("clk", "reset_n") and "ddr" not in n
                   for n in pin_names if n)


def test_l9_emits_empty_with_flag_when_l1_empty(
        tmp_path: Path) -> None:
    """v1.6.65 — closes issue-#6 v1.6.64 follow-up Bug E thin-input
    complaint. When L1.pin_table is empty, L9 must emit `[]` plus
    `no_integration_in_input: true` — NOT the v1.6.64 EXAMPLE_PROTOCOL 3-port
    hardcode (`clk` / `reset_n` / `id_bus`)."""
    project = _seed(tmp_path)
    gen_l9_integration_spec(project, {}, l3={})
    l9 = _read(project, "L9_INTEGRATION_SPEC")
    assert l9["top_module_pins"] == []
    assert l9["ports"] == []
    assert l9["no_integration_in_input"] is True
    pin_names = {p.get("name") for p in l9["top_module_pins"]}
    # Critical: EXAMPLE_PROTOCOL-flavoured pin names must NOT appear on a project
    # whose L1.pin_table is empty.
    assert "id_bus" not in pin_names
    assert "clk" not in pin_names
    assert "reset_n" not in pin_names


def test_l9_promotes_l6_fsm_states_when_present(tmp_path: Path) -> None:
    project = _seed(tmp_path, l_docs={
        "L6_CONTROL_LOGIC": {
            "schema_version": 2,
            "fsm_states": [
                {"name": "S_PRECHARGE", "transitions": []},
                {"name": "S_ACTIVATE", "transitions": []},
                {"name": "S_RW", "transitions": []},
            ],
        },
    })
    gen_l9_integration_spec(project, {}, l3={})
    l9 = _read(project, "L9_INTEGRATION_SPEC")
    state_names = {s.get("name") for s in l9["fsm_states"]}
    assert "S_PRECHARGE" in state_names
    assert "S_ACTIVATE" in state_names
    # EXAMPLE_PROTOCOL scaffold states must NOT win over the real L6.
    assert "S_VALIDATE" not in state_names


# ---------------------------------------------------------------------------
# Bug F — L11.otp_layout mirrors L4.otp_layout
# ---------------------------------------------------------------------------

def test_l11_mirrors_l4_otp_layout(tmp_path: Path) -> None:
    project = _seed(tmp_path, l_docs={
        "L4_REGMAP": {
            "schema_version": 2,
            "otp_layout": {
                "fields": [
                    {"field": "ID[0]", "address_hint": "0x00"},
                    {"field": "ID[1]", "address_hint": "0x01"},
                ],
                "depth_bytes": 128,
                "width_bits": 8,
            },
        },
    })
    gen_l11_otp_content(project, {})
    l11 = _read(project, "L11_OTP_CONTENT")
    fields = {f.get("field")
              for f in l11.get("otp_layout", {}).get("fields", [])}
    assert "ID[0]" in fields
    assert "ID[1]" in fields
    assert l11["no_otp_layout_in_input"] is False


def test_l11_no_l4_otp_layout_emits_empty_with_flag(tmp_path: Path) -> None:
    project = _seed(tmp_path)
    gen_l11_otp_content(project, {})
    l11 = _read(project, "L11_OTP_CONTENT")
    # v1.6.70 — issue #10 Bug A: L11.otp_layout is now `None` (was
    # `{}`) when no OTP evidence is present. Either is acceptable for
    # the "empty / no-evidence" semantic; assert flag instead.
    assert l11["otp_layout"] in (None, {})
    assert l11["no_otp_layout_in_input"] is True


# ---------------------------------------------------------------------------
# Cross-IC fingerprint guard — the original issue-#6 complaint was that
# 11 different IC classes produced *structurally identical* L7/L8/L13.
# Assert that distinct IC inputs produce distinct outputs.
# ---------------------------------------------------------------------------

def test_l7_l8_l13_diverge_across_three_ic_classes(
        tmp_path_factory) -> None:
    aes_dir = tmp_path_factory.mktemp("aes")
    dram_dir = tmp_path_factory.mktemp("dram")
    aid_dir = tmp_path_factory.mktemp("example_protocol")
    _seed(aes_dir)
    _seed(dram_dir)
    _seed(aid_dir)
    # AES — pure combinational, no test modes / no timing / no trim.
    gen_l7_test_debug(aes_dir,
                      {"aes_spec.txt": "Verilog AES. Combinational.\n"})
    gen_l8_timing_waveform(aes_dir,
                           {"aes_spec.txt": "Combinational.\n"})
    gen_l13_lab_calibration(aes_dir,
                            {"aes_spec.txt": "No calibration.\n"})
    # DRAM — has timing constants, no test modes, no trim.
    gen_l7_test_debug(dram_dir,
                      {"dram_spec.txt": "DRAM controller.\n"})
    gen_l8_timing_waveform(
        dram_dir,
        {"timing.txt": "T_REFRESH = 7800 ticks\nT_RP = 13500 ticks\n"},
    )
    gen_l13_lab_calibration(dram_dir,
                            {"dram_spec.txt": "no trim required.\n"})
    # EXAMPLE_PROTOCOL — has test modes, has trim, has its own timing.
    gen_l7_test_debug(
        aid_dir,
        {"aid_test_spec.txt": "TEST_MODE = 0x40\nENG_MODE = 0x42\n"},
    )
    gen_l8_timing_waveform(
        aid_dir,
        {"timing.txt": "T_BIT_CELL = 440 ticks\nT_WAKE = 1120 ticks\n"},
    )
    gen_l13_lab_calibration(
        aid_dir,
        {"trim_spec.txt": "TRIM_BANDGAP: 4-bit\n"},
    )
    # Aggregate: each layer's `<field>` list must produce distinct
    # shapes across the 3 classes.
    l7_aes = _read(aes_dir, "L7_TEST_DEBUG")["test_modes"]
    l7_dram = _read(dram_dir, "L7_TEST_DEBUG")["test_modes"]
    l7_aid = _read(aid_dir, "L7_TEST_DEBUG")["test_modes"]
    assert l7_aes == [] and l7_dram == [] and len(l7_aid) >= 1, \
        f"L7 hardcode: {l7_aes!r} {l7_dram!r} {l7_aid!r}"
    l8_aes = _read(aes_dir, "L8_RTL_CONSTANTS")["timing_constants"]
    l8_dram = _read(dram_dir, "L8_RTL_CONSTANTS")["timing_constants"]
    l8_aid = _read(aid_dir, "L8_RTL_CONSTANTS")["timing_constants"]
    distinct_l8 = {tuple(sorted(tc.get("name") for tc in lst))
                   for lst in (l8_aes, l8_dram, l8_aid)}
    assert len(distinct_l8) >= 3, \
        f"L8 collapsed to {len(distinct_l8)} distinct shapes"
    l13_aes = _read(aes_dir, "L13_LAB_CALIBRATION")["calibration_targets"]
    l13_aid = _read(aid_dir, "L13_LAB_CALIBRATION")["calibration_targets"]
    assert l13_aes == [] and len(l13_aid) >= 1
