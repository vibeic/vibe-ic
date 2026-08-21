"""An instance supply terminal the grid solver could not reach must decide.

THE DEFECT
==========
The supply question the flow gates is net OWNERSHIP — is a terminal's net
pointer non-NULL. A terminal attached to a rail that is declared but never
built passes that test perfectly: the pointer is valid, the name is right, and
no conductor arrives. Ownership is a LOGICAL property; being reached is a
PHYSICAL one, and the gate measured the one that cannot detect the defect.

The physical witness was already produced, already parsed, and already written
to the report under the name `unconnected_supply_pins` — and no verdict read
it. So the report stated the defect and passed.

WHAT IS PINNED HERE
===================
1.  the rule      — an unreached instance terminal makes the verdict FAIL, and
                    it decides BEFORE the budget comparison
2.  the boundary  — an unconnected SHAPE does NOT escalate (proves the rule
                    discriminates instead of failing everything)
3.  the wording   — a reworded tool sentence still counts (a witness that goes
                    quiet on a rewording is this module's own known failure)
4.  the wiring    — the production call site passes the terminals, so the rule
                    cannot be reverted at the call site while this file passes

Synthetic logs throughout — generic rail names, no design, process, vendor or
part is named anywhere in this file.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
from psm_analysis_coverage import (analysis_coverage,  # noqa: E402
                                   ir_verdict, unconnected_instances,
                                   verdict_basis)

CLEAN = """=== PSM_NET VPWR ===
Worst IR drop  : 0.021 V
=== PSM_NET VGND ===
Worst IR drop  : 0.018 V
"""

# A shape is an island of metal; an instance is a consumer. Both in one log so
# every test below discriminates rather than merely detecting "something".
SHAPE_ONLY = CLEAN + (
    "[WARNING PSM-0038] Unconnected shape on net VPWR at "
    "(1.000um, 2.000um) - (3.000um, 4.000um), layer: M3.\n")

UNREACHED = SHAPE_ONLY + (
    "[WARNING PSM-0039] Unconnected instance u_top.u_blk/VPWR at location "
    "(5.000um, 6.000um).\n"
    "[WARNING PSM-0039] Unconnected instance u_top.u_blk/VPROG at location "
    "(7.000um, 8.000um).\n")

NETS = ["VPWR", "VGND"]
# 0.021 V worst against a 10%-of-1.8V budget — comfortably inside it, so any
# FAIL below is the new rule and never the budget.
WORST_UV, BUDGET_UV = 21000.0, 180000.0


def test_the_terminals_are_parsed_as_terminals_not_as_sentences():
    assert unconnected_instances(UNREACHED) == [
        "u_top.u_blk/VPWR", "u_top.u_blk/VPROG"]


def test_an_unreached_terminal_fails_a_verdict_the_budget_would_pass():
    """The whole defect in one assertion."""
    cov = analysis_coverage(UNREACHED, NETS)
    assert cov["analysis_failed"] == [], "the budget path must be the live one"
    assert WORST_UV <= BUDGET_UV, "the budget alone would pass this run"
    assert ir_verdict(WORST_UV, BUDGET_UV, cov["analysis_failed"],
                      cov["unconnected_instances"]) == "FAIL"


def test_an_unconnected_shape_alone_does_not_escalate():
    """A floating island of supply metal is an imperfection, not a starved
    consumer. Without this the rule would be "PSM said something", which
    passes test 2 while gating the wrong property all over again."""
    cov = analysis_coverage(SHAPE_ONLY, NETS)
    assert cov["connectivity"], "the 0038 line is still reported"
    assert cov["unconnected_instances"] == []
    assert ir_verdict(WORST_UV, BUDGET_UV, cov["analysis_failed"],
                      cov["unconnected_instances"]) == "PASS"


def test_a_clean_log_still_passes():
    cov = analysis_coverage(CLEAN, NETS)
    assert ir_verdict(WORST_UV, BUDGET_UV, cov["analysis_failed"],
                      cov["unconnected_instances"]) == "PASS"


def test_an_over_budget_run_still_fails_for_the_budget_reason():
    cov = analysis_coverage(CLEAN, NETS)
    assert ir_verdict(BUDGET_UV + 1.0, BUDGET_UV, cov["analysis_failed"],
                      cov["unconnected_instances"]) == "FAIL"


def test_a_reworded_tool_sentence_still_counts():
    """`_PSM0069_RE` lost every real log to a trailing period once already. A
    witness whose only shape is today's sentence is a witness that will go
    quiet without anyone noticing, so an unparsable 0039 still yields an
    entry — the count is never silently zero."""
    reworded = CLEAN + "[WARNING PSM-0039] instance supply terminal unreached\n"
    found = unconnected_instances(reworded)
    assert len(found) == 1
    assert ir_verdict(WORST_UV, BUDGET_UV, [], found) == "FAIL"


def test_the_count_the_basis_quotes_is_not_a_display_cap():
    """`connectivity` caps at 20 because it is a display sample. This list is a
    decision input whose length is quoted back to the reader, and a length that
    saturates at a cap reads "20" on a design with 60."""
    many = CLEAN + "".join(
        f"[WARNING PSM-0039] Unconnected instance u_top.u_b{i}/VPWR at "
        f"location ({i}.000um, 0.000um).\n" for i in range(60))
    cov = analysis_coverage(many, NETS)
    assert len(cov["connectivity"]) == 20, "the display sample is still capped"
    assert len(cov["unconnected_instances"]) == 60
    assert "60 instance" in verdict_basis([], cov["unconnected_instances"])


def test_the_basis_names_the_reason_the_verdict_is_not_a_pass():
    cov = analysis_coverage(UNREACHED, NETS)
    basis = verdict_basis(cov["analysis_failed"], cov["unconnected_instances"])
    assert "u_top.u_blk/VPWR" in basis
    assert "reach" in basis


def test_both_reasons_survive_together():
    """Taking either side of a composed condition alone drops the other."""
    both = UNREACHED + "PSM_NONFATAL VGND: PSM-0069\n"
    cov = analysis_coverage(both, NETS)
    assert cov["analysis_failed"] == ["VGND"]
    assert cov["unconnected_instances"]
    basis = verdict_basis(cov["analysis_failed"], cov["unconnected_instances"])
    assert "reach" in basis and "VGND" in basis


def test_the_terminals_argument_is_required_of_every_caller():
    """A default would let a new call site restore the defect in silence."""
    with pytest.raises(TypeError):
        ir_verdict(WORST_UV, BUDGET_UV, [])          # type: ignore[call-arg]
    with pytest.raises(TypeError):
        verdict_basis([])                            # type: ignore[call-arg]


# ── the paired guard: the rule is only worth as much as its wiring ──────────

_RUNNER = _PROGRAMS / "phase3_one_shot_runner.py"


def _calls_to(tree: ast.AST, name: str):
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == name]


@pytest.mark.parametrize("fn,argc", [("ir_verdict", 4), ("verdict_basis", 2)])
def test_the_production_call_site_passes_the_terminals(fn, argc):
    """Reverting the fix at the CALL SITE — dropping the argument, or passing
    a literal empty list to quiet it — is the cheap way to restore the defect
    with every unit test above still green. This reads the runner's own source
    so that edit cannot be silent."""
    tree = ast.parse(_RUNNER.read_text(encoding="utf-8"))
    calls = _calls_to(tree, fn)
    assert calls, f"{fn} is not called by the runner at all"
    for call in calls:
        assert len(call.args) == argc, (
            f"{fn} called with {len(call.args)} args at line {call.lineno}; "
            f"the unreached-terminal argument is not optional")
        last = call.args[-1]
        assert not isinstance(last, (ast.List, ast.Tuple)) or last.elts, (
            f"{fn} at line {call.lineno} is passed an empty literal — that "
            f"satisfies the signature and restores the defect")


def test_the_runner_does_not_re_derive_the_rule_inline():
    """Two implementations of one rule drift into two answers about one log.
    The runner used to re-parse PSM-0039 with its own regex; it must read the
    module instead."""
    src = _RUNNER.read_text(encoding="utf-8")
    offenders = [i + 1 for i, l in enumerate(src.splitlines())
                 if "PSM-0039" in l and ("re.findall" in l or "re.compile" in l
                                         or "re.search" in l)]
    assert not offenders, (
        f"the runner parses PSM-0039 itself at line(s) {offenders}; "
        f"psm_analysis_coverage.unconnected_instances is the one implementation")
