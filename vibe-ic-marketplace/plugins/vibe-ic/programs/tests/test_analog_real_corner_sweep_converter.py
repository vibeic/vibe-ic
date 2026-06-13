#!/usr/bin/env python3
"""tests/test_analog_real_corner_sweep_converter.py

Template-render tests for the converter / modulator block-type family added to
analog_real_corner_sweep.py per ORGANIC-20260528-a4.

These tests do NOT run ngspice (ngspice is not available on the CI host). They
assert only that each new btype's deck TEMPLATE format-fills with no KeyError
and is structurally a valid ngspice deck (has a .param where parametric, a
transient analysis, a .measure, a corner-stamped .lib line, and terminates with
.end). The decks are derived verbatim from the canonical hand-authored decks in
u_hawaii_adc_v0125_rerun/phase3/analog/ (delta_sigma.sp, integrator_settle.sp,
comparator.sp, adc.sp) — see the module docstring for provenance.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

PROG = (Path(__file__).resolve().parent.parent / "analog_real_corner_sweep.py")

# A representative sky130 lib path string (the file need not exist — we only
# render the template; ngspice is never invoked).
PDK_LIB = "/foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice"

# The new converter / modulator family this backlog adds. comparator has no
# swept parameter (single latched-compare deck, faithful to comparator.sp),
# so it is exempt from the `.param` structural assertion.
NEW_BTYPES = ["delta_sigma", "modulator", "adc", "comparator"]
PARAMETRIC_BTYPES = ["delta_sigma", "modulator", "adc"]

# The documented IC sim corner names (process sections of the SKY130 ngspice
# lib). The new templates stamp {corner} into the .lib line exactly like the
# pre-existing templates hardcoded `tt`.
CORNERS = ["ss", "tt", "ff"]


def _load_module():
    spec = importlib.util.spec_from_file_location("analog_real_corner_sweep", PROG)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _render(m, btype, corner="tt"):
    """Format-fill the template for the first sweep point of `btype`."""
    knob, val = m.SWEEPS[btype][0]
    kw = {(knob if knob != "__noop__" else "_unused"): val}
    return m.T[btype].format(block="u_block", pdk="sky130",
                             pdk_lib=PDK_LIB, corner=corner, **kw)


# -- Each new btype is wired into the dispatch (T + SWEEPS + TARGETS) so it no
#    longer falls to the deterministic stub (`if btype not in T: return 2`). --

@pytest.mark.parametrize("btype", NEW_BTYPES)
def test_btype_wired_into_dispatch(btype):
    m = _load_module()
    assert btype in m.T,       f"{btype} missing from template dict T"
    assert btype in m.SWEEPS,  f"{btype} missing from SWEEPS"
    assert btype in m.TARGETS, f"{btype} missing from TARGETS"


# -- Each new btype renders with no KeyError for every documented sweep point. --

@pytest.mark.parametrize("btype", NEW_BTYPES)
def test_renders_no_keyerror_all_sweep_points(btype):
    m = _load_module()
    for knob, val in m.SWEEPS[btype]:
        kw = {(knob if knob != "__noop__" else "_unused"): val}
        deck = m.T[btype].format(block="b", pdk="sky130",
                                 pdk_lib=PDK_LIB, corner="tt", **kw)
        # No leftover '{...}' placeholder would mean a future .format() raises.
        assert "{" not in deck, f"{btype}: leftover format placeholder in deck"


# -- Structurally a valid ngspice deck: .tran + .measure + corner-stamped .lib
#    + terminating .end. --

@pytest.mark.parametrize("btype", NEW_BTYPES)
def test_deck_structure(btype):
    m = _load_module()
    deck = _render(m, btype)
    # transient analysis present (control-block `tran ...`)
    assert "tran " in deck, f"{btype}: no transient analysis"
    # at least one .measure / meas statement
    assert "meas " in deck or ".measure" in deck, f"{btype}: no .measure"
    # corner-stamped .lib line
    assert ".lib" in deck, f"{btype}: no .lib stamp"
    # MEAS echo line so _MEAS_LINE_RE can scrape the result back
    assert "MEAS" in deck, f"{btype}: no MEAS echo line"
    # terminates with .end
    assert deck.strip().endswith(".end"), f"{btype}: deck does not end with .end"


# -- Parametric btypes carry a .param (the swept knob). --

@pytest.mark.parametrize("btype", PARAMETRIC_BTYPES)
def test_parametric_btype_has_param(btype):
    m = _load_module()
    deck = _render(m, btype)
    assert ".param" in deck, f"{btype}: parametric btype missing .param"


# -- The {corner} placeholder is honoured: each documented corner name stamps
#    the .lib line exactly. --

@pytest.mark.parametrize("btype", NEW_BTYPES)
@pytest.mark.parametrize("corner", CORNERS)
def test_corner_stamp(btype, corner):
    m = _load_module()
    deck = _render(m, btype, corner=corner)
    assert f"sky130.lib.spice {corner}" in deck, \
        f"{btype}: corner {corner} not stamped into .lib line"


# -- delta_sigma / modulator expose the parametric Cs the backlog asks for, and
#    measure UGBW + the SC-integrator settle (quantizer/integrator metrics). --

def test_delta_sigma_parametric_cs_and_metrics():
    m = _load_module()
    deck = _render(m, "delta_sigma")
    assert ".param cs=" in deck, "delta_sigma: no parametric Cs"
    assert ".param ci=" in deck, "delta_sigma: no Ci (integrating cap)"
    assert "ugbw" in deck, "delta_sigma: no UGBW measure (integrator settling proxy)"
    # the swept knob is cs and brackets the reference cs=0.5p
    knobs = {k for k, _ in m.SWEEPS["delta_sigma"]}
    assert knobs == {"cs"}, f"delta_sigma sweep knob should be cs, got {knobs}"
    vals = [v for _, v in m.SWEEPS["delta_sigma"]]
    assert "0.5p" in vals, "delta_sigma Cs sweep must include the reference 0.5p"


def test_modulator_is_delta_sigma_alias():
    m = _load_module()
    # modulator is the same physical block as delta_sigma (alias).
    assert m.T["modulator"] is m.T["delta_sigma"] or \
        m.T["modulator"] == m.T["delta_sigma"]


# -- adc sweeps OSR (incremental-ΔΣ cycles). --

def test_adc_sweeps_osr():
    m = _load_module()
    knobs = {k for k, _ in m.SWEEPS["adc"]}
    assert knobs == {"osr"}, f"adc sweep knob should be osr, got {knobs}"
    deck = _render(m, "adc")
    assert ".param osr=" in deck, "adc: no parametric OSR"


# -- comparator measures the latch decision split (resolve) + offset surrogate
#    across two evaluate windows, verbatim from comparator.sp. --

def test_comparator_resolve_and_offset():
    m = _load_module()
    deck = _render(m, "comparator")
    assert "oa_win1" in deck and "oa_win2" in deck, \
        "comparator: missing two evaluate-window decision samples (resolve)"
    assert "voffset" in deck, "comparator: missing offset surrogate"
    # comparator has no swept parameter (single latched-compare deck).
    assert m.SWEEPS["comparator"] == [("__noop__", 0)]


# -- Existing templates must still render with the newly-added `corner` kwarg
#    present in the .format() call (regression guard). --

@pytest.mark.parametrize("btype", ["ldo", "bandgap", "por", "pull", "trim",
                                   "oscillator", "esd", "charge_pump"])
def test_existing_templates_unbroken(btype):
    m = _load_module()
    knob, val = m.SWEEPS[btype][0]
    kw = {(knob if knob != "__noop__" else "_unused"): val}
    deck = m.T[btype].format(block="b", pdk="sky130",
                             pdk_lib=PDK_LIB, corner="tt", **kw)
    assert deck.strip().endswith(".end")
