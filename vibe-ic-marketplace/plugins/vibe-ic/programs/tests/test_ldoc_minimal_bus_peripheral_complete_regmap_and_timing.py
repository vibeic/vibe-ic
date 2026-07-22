"""l_doc_structured_field_count_check — a genuinely MINIMAL bus_peripheral
(e.g. the stock caravel Wishbone-mapped counter) with a COMPLETE-but-small
register map and sparse timing must PASS L4 and L8 without weakening the gate.

Field observation (caravel_user_project × sky130A): the design has exactly ONE
SW register (COUNT) and no OTP, and ~6 typed timing facts (a single 40 MHz clock
+ ack latency). The #677 honest-absence escape only covers ZERO regmap, and the
bus_peripheral class deliberately stays NON-sparse (test #748r2), so:
  - L4 FAILed the ≥5 floor even though registers=1 is COMPLETE vs the input;
  - L8 FAILed the ≥10 floor even though the design genuinely has ~6.

Fixes (check-side, chip-AGNOSTIC, doctrine-respecting):
  - L4: credit a below-floor regmap when it captured EVERY register DECLARED in
        the input register doc (completeness proof), for a minimal_honest_
        absence_ok class with no real OTP content. A DROPPED-registers
        extraction defect (captured < declared) still FAILs.
  - L8: relax to the sparse ≥3 floor for a minimal_honest_absence_ok class whose
        INPUT declares a small COMPLETE register map (1-4 registers). Keys on an
        INSTANCE proof, NOT the class-wide sparse_control_timing predicate
        (unchanged), so bus_interconnect_protocol (no regmap) and rich (≥5-reg)
        peripherals stay strict ≥10.

NEGATIVE controls (load-bearing) below prove neither relaxation is vacuous.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_PROG = (Path(__file__).resolve().parent.parent
         / "l_doc_structured_field_count_check.py")
_spec = importlib.util.spec_from_file_location("_ldoc_minperiph", _PROG)
G = importlib.util.module_from_spec(_spec)
sys.modules["_ldoc_minperiph"] = G
_spec.loader.exec_module(G)

_MINIMAL = "bus_peripheral"          # minimal_honest_absence_ok, NON-sparse
_PROTOCOL = "bus_interconnect_protocol"  # minimal flag too, but stays strict
_RICH = "digital_cmd_driven"

_REG_TABLE_HEADER = "| Offset | Name | Access | Width | Description |\n|---|---|---|---|---|\n"


def _reg_doc(rows):
    lines = [_REG_TABLE_HEADER.rstrip("\n")]
    for i, nm in enumerate(rows):
        lines.append(f"| `0x{i*4:04x}` | {nm} | R/W | 32 | reg {nm} |")
    return "\n".join(lines) + "\n"


def _proj_with_regmap(tmp_path, declared_names):
    p = tmp_path / "periph"
    idoc = p / "phase1" / "input_doc"
    idoc.mkdir(parents=True)
    (idoc / "L5_register_map.txt").write_text(_reg_doc(declared_names))
    return p


def _l4_doc(reg_names, otp=None):
    return {
        "registers": [{"addr_hex": f"0x{i:04x}", "name": nm, "access": "r_w"}
                      for i, nm in enumerate(reg_names)],
        "otp_layout": otp if otp is not None else {
            "fields": [], "read_map": [], "write_map": [], "lockbits": [],
            "otp_ip_specs": None, "trim_registers": [], "mask_sources": [],
            "depth_bytes": 128, "width_bits": 8},
    }


def _l8_doc(n_timing):
    return {"timing_parameters": {f"t{i}": i + 1 for i in range(n_timing)}}


# ── L4 completeness credit ────────────────────────────────────────────────────

def test_l4_complete_minimal_regmap_passes(tmp_path):
    p = _proj_with_regmap(tmp_path, ["COUNT"])          # 1 declared
    ok, msg = G._check_l_doc(4, _l4_doc(["COUNT"]), {}, _MINIMAL, project=p)
    assert ok, f"complete 1-register minimal regmap should PASS: {msg}"


def test_l4_incomplete_regmap_still_fails(tmp_path):
    """NEGATIVE CONTROL (guard (d) preserved): input declares 3 registers but
    extraction captured only 1 → a real DROP → still FAIL."""
    p = _proj_with_regmap(tmp_path, ["A", "B", "C"])    # 3 declared
    ok, _ = G._check_l_doc(4, _l4_doc(["A"]), {}, _MINIMAL, project=p)
    assert not ok, "partial extraction (1 of 3 declared) must still FAIL"


def test_l4_empty_regmap_no_credit(tmp_path):
    """NEGATIVE CONTROL: an empty typed regmap gets no completeness credit."""
    p = _proj_with_regmap(tmp_path, ["COUNT"])
    ok, _ = G._check_l_doc(4, _l4_doc([]), {}, _MINIMAL, project=p)
    assert not ok, "empty regmap must not ride the completeness credit"


def test_l4_credit_requires_no_real_otp(tmp_path):
    """NEGATIVE CONTROL: real OTP content present (an OTP source exists) → the
    complete-minimal-regmap credit does NOT fire (only 1 reg, <5 otp) → FAIL."""
    p = _proj_with_regmap(tmp_path, ["COUNT"])
    otp = {"read_map": [{"a": 1}], "write_map": [], "lockbits": [],
           "otp_ip_specs": None, "trim_registers": [], "mask_sources": [],
           "fields": []}
    ok, _ = G._check_l_doc(4, _l4_doc(["COUNT"], otp=otp), {}, _MINIMAL,
                           project=p)
    assert not ok, "a real OTP source must keep the ≥5 floor"


def test_l4_rich_class_no_credit(tmp_path):
    """NEGATIVE CONTROL: a non-minimal class gets no completeness credit."""
    p = _proj_with_regmap(tmp_path, ["COUNT"])
    ok, _ = G._check_l_doc(4, _l4_doc(["COUNT"]), {}, _RICH, project=p)
    assert not ok, "rich class must keep the ≥5 floor"


def test_l4_no_project_no_credit():
    """NEGATIVE CONTROL: without a project (no completeness proof) the credit
    cannot fire — the #677 unit-test guard (d) is preserved."""
    ok, _ = G._check_l_doc(4, _l4_doc(["COUNT"]), {}, _MINIMAL, project=None)
    assert not ok


# ── L8 minimal-timing relaxation ──────────────────────────────────────────────

def test_l8_minimal_peripheral_relaxed_to_3(tmp_path):
    p = _proj_with_regmap(tmp_path, ["COUNT"])          # 1 declared → minimal
    ok, msg = G._check_l_doc(8, _l8_doc(6), {}, _MINIMAL, project=p)
    assert ok, f"minimal peripheral L8 should relax to ≥3: {msg}"


def test_l8_empty_timing_still_fails(tmp_path):
    """NEGATIVE CONTROL: the ≥3 floor is REAL — <3 typed timing still FAILs."""
    p = _proj_with_regmap(tmp_path, ["COUNT"])
    ok, _ = G._check_l_doc(8, _l8_doc(2), {}, _MINIMAL, project=p)
    assert not ok, "2 typed timing must still FAIL the sparse ≥3 floor"


def test_l8_rich_peripheral_stays_strict(tmp_path):
    """NEGATIVE CONTROL: a bus_peripheral whose input declares a RICH regmap
    (≥5 registers) is not a minimal instance → keeps the strict ≥10 floor."""
    p = _proj_with_regmap(tmp_path, ["A", "B", "C", "D", "E", "F"])
    ok, _ = G._check_l_doc(8, _l8_doc(6), {}, _MINIMAL, project=p)
    assert not ok, "rich (≥5-reg) peripheral L8 must stay ≥10"


def test_l8_protocol_class_stays_strict_even_with_project(tmp_path):
    """NEGATIVE CONTROL: bus_interconnect_protocol has minimal_honest_absence_ok
    too, but a wire-level protocol spec has NO register map → declared is None
    → L8 stays strict ≥10 (test_protocol_stays_strict is preserved)."""
    p = tmp_path / "proto"
    (p / "phase1" / "input_doc").mkdir(parents=True)
    (p / "phase1" / "input_doc" / "L14_protocol.txt").write_text(
        "no register map here — a wire-level protocol spec\n")
    ok, _ = G._check_l_doc(8, _l8_doc(6), {}, _PROTOCOL, project=p)
    assert not ok, "protocol class (no regmap) L8 must stay strict ≥10"
