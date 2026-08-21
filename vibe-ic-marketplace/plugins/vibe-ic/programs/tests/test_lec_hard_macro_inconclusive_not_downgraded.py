#!/usr/bin/env python3
"""The #192 hard-macro INCONCLUSIVE must survive the slang-retry finalizer.

`finalize_after_slang_retry` exists for one case: the GOLD RTL could not be
elaborated even by the capable SV-2017 frontend, so a provisional INCONCLUSIVE
must not give a genuine elaboration error a free non-blocking pass.

It was downgrading a second, unrelated INCONCLUSIVE — the #192 GATE-side
hard-macro staging gap, where `hierarchy -check` aborts because the netlist
instantiates a macro whose definition was never staged into the miter. The gold
elaborated fine there; no frontend can supply a module that is not present, so
"slang also failed" says nothing about that design. The downgrade re-introduced
exactly the harm #192 removed — a comparison that never started, booked as a
proven non-equivalence — and its replacement text told the operator to "fix the
elaboration error", pointing at RTL that is provably fine.

Measured 2026-07-22 on a design carrying a `pdk_local` SRAM macro: `lec.json`
recorded `verdict=FAIL`, `compared_points=0`, "Neither read_verilog -sv nor the
read_slang SV-2017 frontend could elaborate the gold" — while the SAME json
carried `undefined_macro_modules: [<the macro>]` and `lec.rpt` ended on the
gate-side `ERROR: Module ... is not part of the design.`, after the gold had
already run 58 passes.

chip-AGNOSTIC: keyed on the recorded `undefined_macro_modules` list, never on a
macro, design or PDK name.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import lec_run  # noqa: E402


def _inconclusive(undef):
    return {
        "verdict": "INCONCLUSIVE",
        "equivalent": False,
        "undefined_macro_modules": list(undef),
        "verdict_explanation": "original #192 remediation text",
    }


def test_hard_macro_inconclusive_is_kept():
    """The load-bearing case: a gate-side staging gap is not a gold failure."""
    p = _inconclusive(["some_hard_macro"])
    out = lec_run.finalize_after_slang_retry(p, slang_retry_failed=True)
    assert out["verdict"] == "INCONCLUSIVE"
    assert out["verdict_explanation"] == "original #192 remediation text"


def test_real_gold_elaboration_failure_is_still_downgraded():
    """The case the finalizer exists for must keep working."""
    p = _inconclusive([])            # no undefined macro recorded
    out = lec_run.finalize_after_slang_retry(p, slang_retry_failed=True)
    assert out["verdict"] == "FAIL"
    assert out["equivalent"] is False
    assert "read_slang" in out["verdict_explanation"]


def test_noop_when_slang_was_not_attempted_or_succeeded():
    for undef in ([], ["some_hard_macro"]):
        p = _inconclusive(undef)
        assert lec_run.finalize_after_slang_retry(
            p, slang_retry_failed=False)["verdict"] == "INCONCLUSIVE"


def test_a_real_pass_or_fail_is_never_touched():
    for v in ("PASS", "FAIL"):
        p = {"verdict": v, "undefined_macro_modules": ["some_hard_macro"]}
        assert lec_run.finalize_after_slang_retry(
            p, slang_retry_failed=True)["verdict"] == v


def test_classifier_on_a_gate_side_hierarchy_abort():
    """End-to-end through the parser: a hierarchy abort naming an unstaged
    module classifies INCONCLUSIVE and records the module, and the finalizer
    leaves it alone."""
    raw = (
        "9. Executing HIERARCHY pass (managing design hierarchy).\n"
        "9.1. Analyzing design hierarchy..\n"
        "Top module:  \\some_top\n"
        "ERROR: Module `\\some_hard_macro' referenced in module `\\some_top' "
        "in cell `\\g_bank[9].u_bank' is not part of the design.\n"
    )
    parsed = lec_run.parse_equiv_output(raw)
    assert parsed["verdict"] == "INCONCLUSIVE"
    assert parsed["undefined_macro_modules"] == ["some_hard_macro"]
    out = lec_run.finalize_after_slang_retry(dict(parsed),
                                             slang_retry_failed=True)
    assert out["verdict"] == "INCONCLUSIVE", (
        "the slang finalizer downgraded a gate-side hard-macro staging gap")
