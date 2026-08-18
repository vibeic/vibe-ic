"""#169 (A9) — a STAGED silicon SDC carries the ORIGINATING PDK's design-rule
(DRV) limits. Re-used verbatim under a DIFFERENT active PDK the VALUES are wrong
(sky130's 1.5 ns slew / 5 pF cap are not ASAP7's); unit-scaling fixes the UNITS
but keeps the stale VALUE. `_reconcile_staged_sdc_drv` stamps provenance and, on
a PDK mismatch, re-derives the DRV limits from the active liberty (or drops them).

These tests use a SYNTHETIC active liberty with DIFFERENT DRV numbers than any
real PDK, so a hardcoded value would fail them.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402


# A synthetic ACTIVE liberty declaring DRV limits DIFFERENT from sky130's.
_ACTIVE_LIB_WITH_DRV = """\
library(active_pdk) {
  time_unit : "1ns" ;
  capacitive_load_unit (1, pf) ;
  default_max_transition : 0.42 ;
  default_max_capacitance : 0.19 ;
  cell (INV) { pin (Y) { direction : output ; max_capacitance : 0.19 ; } }
}
"""

# A synthetic active liberty declaring NEITHER DRV limit (no default_* / no pin
# max_capacitance) — the stale lines must be DROPPED, never kept.
_ACTIVE_LIB_NO_DRV = """\
library(bare_pdk) {
  time_unit : "1ns" ;
  capacitive_load_unit (1, pf) ;
  cell (INV) { pin (Y) { direction : output ; } }
}
"""

# A staged SDC that a prior sky130 run wrote: stamped sky130A, carrying sky130's
# DRV values (1.5 ns / 5 pF) plus a design-authored clock (must be preserved).
_STAGED_SKY130_SDC = """\
# VIBEIC_SDC_PDK_PROVENANCE: sky130A
create_clock -name clk -period 10 [get_ports clk]
set_max_transition 1.5 [current_design]
set_max_capacitance 5 [current_design]
"""


def _lib(tmp, text, name="active.lib"):
    p = tmp / name
    p.write_text(text)
    return str(p)


def test_cross_pdk_rederives_drv_from_active_liberty(tmp_path):
    lib = _lib(tmp_path, _ACTIVE_LIB_WITH_DRV)
    out = R._reconcile_staged_sdc_drv(_STAGED_SKY130_SDC, "active_pdk", lib)
    # the stale sky130 numbers are gone; the active liberty's numbers are in.
    assert "set_max_transition 1.5" not in out
    assert "set_max_capacitance 5 " not in out
    assert "set_max_transition 0.42" in out
    assert "set_max_capacitance 0.19" in out
    # the design-authored clock is UNTOUCHED, and the provenance is re-stamped.
    assert "create_clock -name clk -period 10" in out
    assert "VIBEIC_SDC_PDK_PROVENANCE: active_pdk" in out
    assert "VIBEIC_SDC_PDK_PROVENANCE: sky130A" not in out


def test_active_liberty_without_drv_drops_stale_lines(tmp_path):
    lib = _lib(tmp_path, _ACTIVE_LIB_NO_DRV)
    out = R._reconcile_staged_sdc_drv(_STAGED_SKY130_SDC, "bare_pdk", lib)
    # no fabricated limit — the stale DRV COMMAND lines are DROPPED entirely
    # (the disclosure comment may still name the directives; check command lines
    # only, i.e. non-comment lines).
    cmd_lines = [l.strip() for l in out.split("\n")
                 if l.strip() and not l.strip().startswith("#")]
    assert not any(l.startswith("set_max_transition") for l in cmd_lines)
    assert not any(l.startswith("set_max_capacitance") for l in cmd_lines)
    assert "create_clock -name clk -period 10" in out


def test_matching_provenance_is_byte_identical(tmp_path):
    # re-run under the SAME PDK the SDC was staged for → values are correct →
    # unchanged (no reconcile, no re-stamp churn).
    lib = _lib(tmp_path, _ACTIVE_LIB_WITH_DRV)
    out = R._reconcile_staged_sdc_drv(_STAGED_SKY130_SDC, "sky130A", lib)
    assert out == _STAGED_SKY130_SDC


def test_unstamped_hand_authored_sdc_never_touched(tmp_path):
    # A hand-authored project SDC has NO provenance stamp; it is returned
    # byte-identical even under a different PDK (sky130/nangate unchanged).
    hand = ("create_clock -name clk -period 8 [get_ports clk]\n"
            "set_max_transition 0.75 [current_design]\n")
    lib = _lib(tmp_path, _ACTIVE_LIB_WITH_DRV)
    assert R._reconcile_staged_sdc_drv(hand, "active_pdk", lib) == hand


def test_stamp_is_idempotent():
    once = R._stamp_sdc_provenance("create_clock -period 10 clk\n", "sky130A")
    twice = R._stamp_sdc_provenance(once, "sky130A")
    assert twice == once
    assert once.count("VIBEIC_SDC_PDK_PROVENANCE") == 1
    # re-stamping to a new PDK replaces (does not stack) the marker.
    renamed = R._stamp_sdc_provenance(once, "asap7")
    assert renamed.count("VIBEIC_SDC_PDK_PROVENANCE") == 1
    assert "asap7" in renamed and "sky130A" not in renamed
