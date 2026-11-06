"""Post-layout LEC: the standard cells were loaded TWICE, so nothing was proven.

THE DEFECT (measured, long-standing — the published spm specimen ships it)
=========================================================================
`build_yosys_equiv_script` read the Liberty and then read the PDK's blackbox
Verilog for the SAME library. Both files declare the same standard cells, and
plain `read_verilog -lib` OVERWRITES an existing module, so Yosys refused:

    sky130_fd_sc_hd__blackbox.v:37: ERROR: Re-definition of module
    `\\sky130_fd_sc_hd__a2bb2o_1'!

The whole proof aborted -> `lec_post_layout.json` verdict RUN_ERROR, yosys_rc 1,
proven_points null. Equivalence was never proven for any routed netlist.

WHICH SOURCE THE PROOF NEEDS
----------------------------
The Liberty is the ONLY source that carries cell FUNCTION; the blackbox Verilog
declares the same cells as EMPTY modules and exists solely to name the cells the
Liberty does NOT model (fill / tap / endcap / diode / IO pads) so `hierarchy`
does not abort. So neither source may be dropped and the Liberty must WIN:
`-nooverwrite` makes the blackbox read purely ADDITIVE. Silencing the collision
the other way (letting the stub win) would replace every functional model with a
function-less box and the proof would become vacuous in the worst way — a
NAND-for-NOR swap would "prove".

TWO MORE THINGS THE SAME PROOF NEEDED TO PRODUCE A REAL NUMBER
--------------------------------------------------------------
(b) GOLD was hard-coded to `<top>_synth.v`, the PRE-DFT netlist, while PnR
    routes `post_dft_netlist.v` on any design with a scan chain. `equiv_make`
    then aborts "Can't match gate port `shift_gate' to a gold port" — another
    RUN_ERROR that says nothing about the routed logic. Gold is now the netlist
    `pnr_input_netlist` says PnR actually routed.
(c) `_synthesize_physical_cell_stubs` decided which cells to blackbox by reading
    the Liberty with a plain HOST `Path(...).read_text()`. The Liberty lives
    inside the EDA container, so that raised OSError, the "cells the Liberty
    models" set was EMPTY, and the generated stub file blackboxed every cell in
    the design (MEASURED on spm x sky130A: 46 stubs, nand2 / a211oi / mux2
    included). That file is read into the same proof.

Every test below drives the REAL shipped functions.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGS))

import lec_post_layout_check as LEC  # noqa: E402


TOP = "widget"
BB = "/pdk/libs.ref/sc/verilog/sc__blackbox.v"
LIB = "/pdk/libs.ref/sc/lib/sc__tt.lib"


# ---------------------------------------------------------------------------
# (a) THE REDEFINITION — the blackbox read must never overwrite a Liberty cell
#
# MUTATION THESE CATCH: restore `read_verilog -lib {q}` in
# `build_yosys_equiv_script` / `_read_blackbox_cmd`.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("functional", [True, False])
def test_blackbox_verilog_can_never_overwrite_a_liberty_cell(functional):
    ys = LEC.build_yosys_equiv_script("gold.v", "gate.v", LIB, TOP,
                                      blackbox_v=[BB, "/w/stubs.v"],
                                      functional_lib=functional)
    reads = [ln for ln in ys.splitlines() if ln.startswith("read_verilog -lib")]
    assert reads, "the blackbox inputs must still be read — dropping them " \
                  "leaves fill/tap/pads undefined and hierarchy aborts"
    for ln in reads:
        assert "-nooverwrite" in ln, (
            f"{ln!r} lets an EMPTY blackbox module replace the Liberty cell of "
            f"the same name; Yosys refuses the collision outright "
            f"('Re-definition of module') and the whole proof aborts")


@pytest.mark.parametrize("functional", [True, False])
def test_the_liberty_is_read_before_every_blackbox_file(functional):
    """`-nooverwrite` KEEPS whatever is already defined, so the source that
    carries FUNCTION has to be read first for the priority to be the right way
    round."""
    ys = LEC.build_yosys_equiv_script("gold.v", "gate.v", LIB, TOP,
                                      blackbox_v=[BB], functional_lib=functional)
    lines = ys.splitlines()
    lib_at = [i for i, ln in enumerate(lines) if ln.startswith("read_liberty")]
    bb_at = [i for i, ln in enumerate(lines) if ln.startswith("read_verilog -lib")]
    assert lib_at and bb_at
    for b in bb_at:
        assert any(l < b for l in lib_at), \
            "a blackbox file is read before any read_liberty on its side"


def test_a_redefinition_abort_is_a_run_error_never_a_pass():
    """The exact transcript the defect produced (specimen v1.10.18_sky130A).
    A recipe that cannot even load its inputs must not report equivalence."""
    log = (
        "1. Executing Liberty frontend: /pdk/sc__tt.lib\n"
        "Imported 428 cell types from liberty file.\n"
        "3. Executing Verilog-2005 frontend: /pdk/sc__blackbox.v\n"
        "sc__blackbox.v:37: ERROR: Re-definition of module `\\sc__a2bb2o_1'!\n")
    parsed = LEC.parse_equiv_log(log)
    assert parsed["verdict"] == LEC.V_RUN_ERROR
    assert parsed["equivalent"] is False
    assert parsed["proven"] is None and parsed["total"] is None
    assert LEC.evaluate_report({
        "verdict": parsed["verdict"], "total_points": parsed["total"],
        "proven_points": parsed["proven"], "unproven_points": parsed["unproven"],
        "equivalent": parsed["equivalent"], "skipped": False,
    })["result"] == "FAIL"


# ---------------------------------------------------------------------------
# helpers for the runner-level tests
# ---------------------------------------------------------------------------









# ---------------------------------------------------------------------------
# (b) GOLD — the reference has to be the netlist PnR actually routed
#
# MUTATION THESE CATCH: restore `gold = synth_out / f"{top}_synth.v"`.
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# (c) STUBS — only for cells the Liberty genuinely does not model
#
# MUTATION THESE CATCH: restore `Path(pdk.liberty).read_text(...)` (host-only)
# in `_synthesize_physical_cell_stubs`.
# ---------------------------------------------------------------------------







# ---------------------------------------------------------------------------
# (d) THE CHECK MUST STILL REFUSE WHEN IT GENUINELY CANNOT RUN
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# (e) THE ANTI-VACUITY LINE — a run that compares nothing is not a pass
# ---------------------------------------------------------------------------

def test_a_clean_run_that_compared_nothing_is_not_a_pass():
    doc = {"verdict": LEC.V_PASS, "total_points": 0, "proven_points": 0,
           "unproven_points": 0, "equivalent": True, "skipped": False}
    assert LEC.evaluate_report(doc)["result"] == "FAIL"


def test_measured_spm_numbers_pass_clean_and_fail_when_mutated():
    """The two ends actually measured on the spm run with the fixed recipe:
    455/455 proven on the routed netlist, and 451/454 with ONE cell function
    swapped in a copy of it."""
    clean = {"verdict": LEC.V_PASS, "total_points": 455, "proven_points": 455,
             "unproven_points": 0, "equivalent": True, "skipped": False}
    assert LEC.evaluate_report(clean)["result"] == "PASS"
    mutated = {"verdict": LEC.V_UNPROVEN, "total_points": 454,
               "proven_points": 451, "unproven_points": 3,
               "equivalent": False, "skipped": False}
    assert LEC.evaluate_report(mutated)["result"] == "FAIL"
