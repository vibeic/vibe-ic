"""PR-B2b (#180) — captable discovery falls back to the cell LEF when the tech
LEF was staged out of a /libs.ref/ path (e.g. asap7's normalized tech LEF).

The primary captable derivation slices the PDK root from the TECH-LEF path's
`/libs.ref/` substring. A named PDK whose tech LEF is staged into the project
(asap7, normalized for negative OFFSETs) no longer carries `/libs.ref/`, so the
primary derivation finds nothing. The fix adds a fallback that derives the PDK
root from the CELL LEF (always under <PDK>/libs.ref/ in-container). Guards:
(a) the fallback block IS emitted with the cell-LEF path when cell_lef_c is given,
(b) sky130/gf180-style callers are unaffected — the fallback is guarded by
    `_prs_rules eq ""` so it only runs when the primary derivation missed.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))

import phase3_one_shot_runner as R  # noqa: E402


def test_fallback_block_emitted_with_cell_lef():
    clef = "/foss/pdks/asap7/libs.ref/asap7sc7p5t/lef/asap7sc7p5t_28.lef"
    tcl = R._post_route_spef_repair_tcl("/work/out", "/work/staged_tech.lef", clef)
    assert "PR-B2b" in tcl
    assert clef in tcl
    assert 'set _prs_j [string first "/libs.ref/" $_prs_clef]' in tcl
    # guarded so it only runs when the primary derivation found nothing
    assert 'if {$_prs_rules eq ""}' in tcl


def test_default_no_cell_lef_is_backward_compatible():
    # legacy 2-arg style still works (cell_lef_c defaults to "")
    tcl = R._post_route_spef_repair_tcl("/work/out", "/work/tech.lef")
    assert isinstance(tcl, str) and tcl


def test_fallback_globs_the_same_librelane_captable_convention():
    clef = "/foss/pdks/gf180mcuD/libs.ref/gf180mcu_fd_sc_mcu7t5v0/lef/x.lef"
    tcl = R._post_route_spef_repair_tcl("/work/out", "/work/staged.lef", clef)
    # same rules.openrcx.*.nom[.magic] glob convention as the primary (chip-agnostic)
    assert "rules.openrcx.*.nom.magic" in tcl
    assert "rules.openrcx.*.nom" in tcl
    assert "libs.tech/{librelane,openlane}" in tcl
