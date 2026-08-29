#!/usr/bin/env python3
"""The EM and IR-drop audits judged an OpenSTA timing report.

Both discover their candidates with SUBSTRING globs. `*ir*.rpt` matches any
name containing the two letters "ir" ANYWHERE -- including
`sta_spef_repaired.rpt`, because "repa(ir)ed" contains them.

MEASURED 2026-08-29, spm x gf180mcuD on v1.12.65, against that run's real
project tree:

    mode      files_found  ERROR findings
    em             4            2          both -> sta_spef_repaired.rpt
    ir_drop        4            2          both -> sta_spef_repaired.rpt

    EM_REPORT_TOO_SMALL       report 976 B is below minimum 1024 B --
                              suggests a hand-typed stub, not a real em
                              tool output
    EM_NO_TOOL_SIGNATURE      report lacks any known em tool signature
    IR_DROP_REPORT_TOO_SMALL  (same file)
    IR_DROP_NO_TOOL_SIGNATURE (same file)

Four ERROR-severity findings accusing a genuine STA report of being a
hand-typed EM stub, from one glob.

WHAT IT DID AND DID NOT BREAK. Neither step's verdict moved: both need only one
authentic report and the real `em.rpt` (3314 B, OpenROAD PSM, 32101 segments)
is authentic, so `passed` was True before and is True after. What changed is
what the operator is TOLD -- the phase-3 headline for a PASSing step read
`PASS em_signoff EM_REPORT_TOO_SMALL: ... suggests a hand-typed stub`. The fix
removes false accusations; it narrows no verdict and weakens no floor. Every
report that was genuinely in scope is still discovered and still judged.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import eda_report_audit as A  # noqa: E402

_EM = ("em", "electromigration", "ir")
_IR = ("ir", "power", "voltage", "psm")


def test_subject_the_sta_report_that_started_this():
    """SUBJECT: the exact filename from the run, for both modes."""
    assert A._name_token_match("sta_spef_repaired.rpt", _EM) is False
    assert A._name_token_match("sta_spef_repaired.rpt", _IR) is False


def test_control_every_intentional_name_is_still_matched():
    """CONTROL -- the inputs the fix must NOT change.

    These were discovered before the fix and must still be discovered after,
    so they are green on BOTH sides. Without them, deleting the pattern list
    outright would satisfy the subject case."""
    for n in ("em.rpt", "em_signoff.rpt", "pnr_em.rpt", "electromigration.rpt",
              "EM.rpt", "ir_drop.rpt", "static_ir.rpt", "irdrop.rpt"):
        assert A._name_token_match(n, _EM) or A._name_token_match(n, _IR), n
    for n in ("ir_drop.rpt", "power_grid.rpt", "voltage_drop.rpt",
              "static_ir.rpt", "IR.rpt"):
        assert A._name_token_match(n, _IR), n


def test_other_accidental_interior_matches_are_also_excluded():
    """The defect is a CLASS, not one filename: any token merely CONTAINING
    the letters must be excluded, not just the one that was measured."""
    for n in ("placement.rpt",      # 'plac(em)ent'
              "post_hold_timing.rpt",
              "system_summary.rpt",  # 'syst(em)'
              "wire_repair.rpt"):    # 'repa(ir)'
        assert A._name_token_match(n, _EM) is False, n


def test_token_boundaries_are_what_decide_it():
    # a token that STARTS with the prefix counts
    assert A._name_token_match("emx.rpt", ("em",)) is True
    # the same letters INSIDE a token do not
    assert A._name_token_match("them.rpt", ("em",)) is False
    # separators split tokens
    assert A._name_token_match("a-b_em.c.rpt", ("em",)) is True
    # case is normalised
    assert A._name_token_match("EM_REPORT.RPT", ("em",)) is True
    # no extension at all is still lexed
    assert A._name_token_match("em", ("em",)) is True


def test_both_checkers_apply_the_filter():
    """WIRING: the helper is worthless if neither checker calls it."""
    import inspect
    for fn in (A._check_em, A._check_ir_drop):
        assert "_name_token_match" in inspect.getsource(fn), fn.__name__
