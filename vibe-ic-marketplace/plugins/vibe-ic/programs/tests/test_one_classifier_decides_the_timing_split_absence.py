"""R-0915-119 rework (lane ictier1c) — the escape certifies "no protocol timing
here" only when check()'s OWN classifier finds nothing to split.

`internal_vs_external_timing_check`'s structural-absence escape used a second
vocabulary (`_PROTO_GROUP_TOKENS`) over key NAMES only, and required non-empty
values where `check()` accepts an empty group. The pre-landing review of
next/icspm5-s2 (95c9184a1) CONFIRMED three inputs on which the escape published
NOT_APPLICABLE_BY_STRUCTURE while `check()` over the SAME document FAILs:

  (a) the v068 flat shape  {"timing_parameters": {"tDW0_us", "tB_break_us",
      "tIBT_us"}}            -> check(): missing_rx_group + missing_tx_group
  (b) timing_groups {detect_thresholds, drive_widths} with no IBT on the drive
      side                   -> check(): tx_missing_symbols ['IBT']
  (c) timing_groups {rx_timing: {}, tx_timing: {}}
                             -> check(): rx/tx_missing_symbols

Each is pinned here as a gate run that must end FAIL (rc 1), never NABS. The
real spm L8 (run22) still reads NABS {scanned 13, found 0}.

AND THE WRAPPER'S HALF, which no test drove: the rc-0 site of
`_check_program_exit_zero` hands the guard the report's structural-absence
enumeration, and the ledger row is written with the same evidence. The tests
below drive the REAL gate through the wrapper and through `check_step`; they go
red when either `evidence=` kwarg is removed (measured, see the commit).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import _flow_reason_taxonomy as TAX                          # noqa: E402

SPM_L8 = PROGRAMS / "tests" / "fixtures" / "spm_run22_L8_TIMING_WAVEFORM.json"
SPM_LAYER = PROGRAMS / "tests" / "fixtures" / "spm_run22_L8_RTL_CONSTANTS.json"
L8_REL = "phase1/generated_docs/L8_TIMING_WAVEFORM.json"
NABS = TAX.NOT_APPLICABLE_BY_STRUCTURE
CMD = (f"internal_vs_external_timing_check {L8_REL} "
       "--json reports/phase2/gates/int_vs_ext_timing.json")


#: R-0915-156 — the declaration under which check() applies. A test about
#: what check() finds declares it; a silent L2 is its own branch (INCOMPLETE).
HD_TRUE = {"protocol_overview": {"half_duplex": True}}
HD_FALSE = {"protocol_overview": {"half_duplex": False}}


def _project(tmp_path: Path, l8, l2=None) -> Path:
    proj = tmp_path / "proj"
    doc = proj / L8_REL
    doc.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(l8, Path):
        shutil.copyfile(l8, doc)
    else:
        doc.write_text(json.dumps(l8))
    if l2 is not None:
        (doc.parent / "L2_FRS.json").write_text(json.dumps(l2))
    return proj




# ── the three confirmed inputs: FAIL, never NABS ───────────────────────────

_V068_FLAT = {"clock_specification": {"main_clk_hz": 5000000},
              "timing_parameters": {"tDW0_us": {"nom": 7.2},
                                    "tB_break_us": {"nom": 13.8},
                                    "tIBT_us": {"nom": 22}}}
_DETECT_DRIVE = {"timing_groups": {
    "detect_thresholds": {"H0": [10, 30], "H1": [1, 9], "BR": [31, 65],
                          "IBT": 5},
    "drive_widths": {"H0": 35, "H1": 9, "BR": 69}}}
_EMPTY_RX_TX = {"timing_groups": {"rx_timing": {}, "tx_timing": {}}}


def _assert_incomplete(rc, rep):
    """R-0915-156: silent L2 + protocol timing -> INCOMPLETE naming the
    missing declaration; never NABS, never PASS, never FAIL."""
    assert (rc, rep.get("verdict")) == (2, "INCOMPLETE"), rep
    assert rep.get("reason_class") == "BLOCKED_BY_UPSTREAM", rep
    assert rep["missing_declaration"]["key"] == "protocol_overview.half_duplex"
    assert "L2_FRS.json" in rep["missing_declaration"]["path"]














# ── the wrapper: the rc-0 site honours the enumeration ─────────────────────





# ── round 2 (review of 8646e1862): the escape may not be NARROWER than the gate ──

_EMPTY_CANON = {"timing_windows": [], "timing_constants": [], "waveforms": []}
_H1_SCALARS = dict(_EMPTY_CANON, H0_low_us=7.2, H1_low_us=1.8, BR_low_us=13.8,
                   IBT_us=22.0)
_H1_SYMBOL_LIST = dict(_EMPTY_CANON, symbol_timing=[
    {"name": "H0", "low_us": 7.2}, {"name": "H1", "low_us": 1.8},
    {"name": "BR", "low_us": 13.8}, {"name": "IBT", "low_us": 22.0}])
_H1_WINDOWS = dict(_EMPTY_CANON, break_window={"min_us": 13, "max_us": 20},
                   ibt_window={"min_us": 20, "max_us": 30})
_H2_MASTER_SLAVE = {"timing_groups": {
    "master_side": {"bit0_low_us": 7.2, "bit1_low_us": 1.8},
    "slave_side": {"bit0_low_us": 7.0, "bit1_low_us": 2.0}}}
_H2_PROTOCOL = {"protocol_timing": {"rx_side": {"H0": 7, "H1": 2},
                                    "tx_side": {"H0": 7, "H1": 2}}}
_H2_LAYER = {"TX_IBT_us": 70, "BR_MIN_us": 62}
















def test_spm_run22_with_its_layer_constants_still_reads_nabs(tmp_path):
    """The flow clause passes --layer; spm's constants carry
    `rx_classifier_ticks: null` and `no_rx_classifier_ticks_in_input: true`
    -- declarations of absence, not timing."""
    proj = _project(tmp_path, SPM_L8)
    lp = proj / "phase1/generated_docs/L8_RTL_CONSTANTS.json"
    shutil.copyfile(SPM_LAYER, lp)
    rep = proj / "gate.json"
    doc = json.loads(rep.read_text())
    assert doc["reason_class"] == NABS, doc
    assert doc["structural_absence"]["found"] == 0, doc


# ── both directions through the wrapper ────────────────────────────────────

_CMD_LAYER = (f"internal_vs_external_timing_check {L8_REL} --layer "
              "phase1/generated_docs/L8_RTL_CONSTANTS.json "
              "--json reports/phase2/gates/int_vs_ext_timing.json")








# ── round 3 (review ictier1c-r2): decide by FIELD, tokenize identifiers ─────

def _spm_plus(**extra):
    doc = json.loads(SPM_L8.read_text())
    doc.update(extra)
    return doc


#: FALSE-FAIL shapes: naming / provenance, where main returned VACUOUS_PASS.
_NAMING_SHAPES = {
    "waveform_caption": _spm_plus(waveforms=[
        {"name": "Wishbone master read cycle",
         "signal": [{"name": "clk", "wave": "p...."}]}]),
    "constant_named_master_clk": _spm_plus(timing_constants=[
        {"name": "master_clk", "value": 10.0, "unit": "MHz"}]),
    "asciidoc_source_document": _spm_plus(source_documents=[
        "L3_external_interface.asciidoc"]),
}
#: NARROW shapes: timing on the page that round 2 missed.
_TIMING_SHAPES = {
    "slash_joined_key": dict(_EMPTY_CANON, **{"H0/H1/BR/IBT_low_us": 7.2}),
    "fused_TIBT_US": dict(_EMPTY_CANON, TIBT_US=22.0),
    "fused_TBR_MIN_US": dict(_EMPTY_CANON, TBR_MIN_US=13.0),
    "fused_IBTmin": dict(_EMPTY_CANON, IBTmin=20.0),
    "fused_H0low": dict(_EMPTY_CANON, H0low=7.2),
    "fused_tbreak_us": dict(_EMPTY_CANON, tbreak_us=13.8),
}


#: The wrapper's word for an INCOMPLETE class: BLOCKED_BY_UPSTREAM reads
#: BLOCKED, any other INCOMPLETE class reads INCOMPLETE. Never NOT_APPLICABLE,
#: PASS or FAIL.
_INCOMPLETE_WORDS = ("INCOMPLETE", "BLOCKED")




import pytest                                                 # noqa: E402










# ── R-0915-153: the L8 schema decides; --layer only as check() reads it ─────



_LAYER_WORDS_THAT_ARE_NOT_TIMING = {
    # wishbone_protocol_synth (review wttwkqmyu): "master" on a list key
    "key_constants_for_RTL_authoring": {
        "wishbone_min_master_signals": ["CLK_I", "RST_I", "ADR_O"]},
    "SHA256_H0_0": "0x6a09e667",      # SHA-2 H(0)
    "TH1_RELOAD": 253,                # 8051 timer reload
    "OPCODE_BR": 22,                  # a branch opcode
}






# ── R-0915-156: the four branches of the contract ──────────────────────────

#: A real half-duplex L8 shape: host-side (rx) and DUT-side (tx) groups.
_SPLIT_GOOD = {"timing_groups": {
    "rx_host_side": {"H0_us": [10, 30], "H1_us": [1, 9], "BR_us": [31, 65],
                     "IBT_us": [5, 20]},
    "tx_dut_side": {"H0_us": 20, "H1_us": 5, "BR_us": 40, "IBT_us": 10}}}
_SPLIT_BAD = {"timing_groups": {
    "rx_host_side": {"H0_us": [10, 30], "H1_us": [1, 9], "BR_us": [31, 65],
                     "IBT_us": [5, 20]},
    "tx_dut_side": {"H0_us": 20, "H1_us": 5, "BR_us": 40, "IBT_us": 70}}}












# ── review wd54r7zx6 (round 6) ──────────────────────────────────────────────



#: The mdio / espi shape: top-level rx_timing / tx_timing groups, BR spelled
#: BRK. Coverage (`_symbols_in`) and the IBT<BR number (`_find_numeric_us`)
#: must read the SAME symbol from the same key.
_BRK_GOOD = {"rx_timing": {"H0_us": [10, 30], "H1_us": [1, 9],
                           "BRK_us": [31, 65], "IBT_us": [5, 20]},
             "tx_timing": {"H0_us": 20, "H1_us": 5, "BRK_us": 40,
                           "IBT_us": 10}}
_BRK_BAD = {"rx_timing": dict(_BRK_GOOD["rx_timing"]),
            "tx_timing": dict(_BRK_GOOD["tx_timing"], IBT_us=70)}






# ── R-0915-164 (round 7): declared half-duplex, but not in THIS symbol family ─

#: Real corpus shapes (values abridged): turnaround timing that is real but not
#: expressed in the H0/H1/BR/IBT single-wire pulse-symbol family.
_MILSTD1553_LIKE = {"timing_intervals": {"RT_RESPONSE_TIME_MIN_us": 4.0,
                                         "RT_RESPONSE_TIME_MAX_us": 12.0,
                                         "BC_NO_RESPONSE_TIMEOUT_us": 14.0}}
_DALI_LIKE = {"request_response_timing": {"forward_to_backward_min_ms": 2.92,
                                          "forward_to_backward_max_ms": 9.17}}
_SDMMC_LIKE = {"cmd_frame_waveform": {"response_timing_NCR":
                                      "Card responds 2..64 CLK after CMD end"}}






# ── review w0z2lp3a7 (round 8) ──────────────────────────────────────────────

#: The v068 host-only shape: family symbols carried as `parameter` labels.
_V068_PARAMETER_ROWS = {"timing_windows": [
    {"parameter": "H1_low", "min_us": 1, "max_us": 9},
    {"parameter": "IBT", "max_us": 20}]}
#: The same family written as ALLCAPS+Capital camel names.
_CAMEL_NAMES = {"timing_parameters": {"tBRMin_us": 31, "tIBTMin_us": 20}}








_RS485_LIKE = {"direction_control_timing_half_duplex": {
    "TX_setup": "DE asserts before first start-bit edge",
    "RX_to_TX_gap": "3.5 character times"}}
