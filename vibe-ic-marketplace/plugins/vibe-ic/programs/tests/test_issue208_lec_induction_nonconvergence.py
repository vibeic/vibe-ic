#!/usr/bin/env python3
"""Regression for #208 — LEC must classify equiv_induct NON-CONVERGENCE as
INCONCLUSIVE, not a false LEC_NOT_EQUIVALENT.

A COMPLETED equiv_make miter can leave points `unproven` for two very different
reasons: a genuine difference (which yosys backs with a COUNTEREXAMPLE), or
equiv_induct's SAT induction simply not converging on a large sequential design
(a flat wall — proved nothing, recorded no counterexample). The old code booked
BOTH as FAIL ("the RTL and gate netlist may genuinely differ"), emitting
LEC_NOT_EQUIVALENT with zero counterexamples. Non-convergence is not
non-equivalence: a real difference produces a counterexample.

Fix: lec_run classifies the flat-wall signatures (`Circuit inherently
diverges!`, or an equiv_induct pass that `Proved 0 previously unproven`) as
INCONCLUSIVE when NO counterexample is present; the downstream gate
lec_equivalence_check treats that INCONCLUSIVE (unproven>0, non_equiv==0) as a
non-blocking sign-off-LEC gap, not LEC_NOT_EQUIVALENT.

§4.05 PRECISION-first / NO-LEAK: a recorded counterexample (a phrase in the log,
or non_equivalent_points>0) ALWAYS wins — it stays a hard FAIL. The re-class
fires only on POSITIVE non-convergence evidence with NO counterexample.

chip-AGNOSTIC: captured yosys log shapes only; no chip/PDK/vendor literal.
"""
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import lec_run                       # noqa: E402
import lec_equivalence_check as gate  # noqa: E402


# equiv_induct diverges at the SAT base case — the opentitan_aes signature.
DIVERGE_OUTPUT = """\
equiv_simple: Starting.
Found 30781 unproven $equiv cells (30781 groups) in equiv:
Proved 18631 previously unproven $equiv cells.
equiv_induct: Proving $equiv cells in module equiv.
Solving problem with 3034373 variables and 1166031 clauses..
Warning: Circuit inherently diverges! (base case failed at step 2)
Proved 0 previously unproven $equiv cells.
equiv_status: Found 30781 $equiv cells in equiv:
  Of those cells 18631 are proven and 12150 are unproven.
"""

# equiv_induct -seq 4/16/64 each prove 0 — a flat wall (the ibex signature).
FLAT_WALL_OUTPUT = """\
equiv_simple: Starting.
Found 7259 unproven $equiv cells (7259 groups) in equiv:
Proved 6350 previously unproven $equiv cells.
equiv_induct: Proving $equiv cells in module equiv (-seq 4).
Found 909 unproven $equiv cells in module equiv:
Proved 0 previously unproven $equiv cells.
equiv_induct: Proving $equiv cells in module equiv (-seq 16).
Proved 0 previously unproven $equiv cells.
equiv_induct: Proving $equiv cells in module equiv (-seq 64).
Proved 0 previously unproven $equiv cells.
equiv_status: Found 7259 $equiv cells in equiv:
  Of those cells 6350 are proven and 909 are unproven.
"""

# A GENUINE difference: equiv records a counterexample. Stays FAIL.
COUNTEREXAMPLE_OUTPUT = """\
equiv_simple: Starting.
Found 40 unproven $equiv cells (40 groups) in equiv:
Proved 33 previously unproven $equiv cells.
equiv_induct: Proving $equiv cells in module equiv.
Trying to prove $equiv for \\p[3]: failed, found counterexample.
equiv_status: Found 40 $equiv cells in equiv:
  Of those cells 33 are proven and 7 are unproven.
"""

# A flat wall that ALSO recorded a counterexample — the counterexample wins.
FLAT_WALL_WITH_CTREX = """\
equiv_simple: Starting.
Found 15 unproven $equiv cells (15 groups) in equiv:
Proved 10 previously unproven $equiv cells.
equiv_induct: Proving $equiv cells in module equiv.
Proved 0 previously unproven $equiv cells.
Trying to prove $equiv for \\q: failed, found counterexample.
equiv_status: Found 15 $equiv cells in equiv:
  Of those cells 10 are proven and 5 are unproven.
"""


# ---------------------------------------------------------------------------
# parser — non-convergence ⇒ INCONCLUSIVE (not FAIL).
# ---------------------------------------------------------------------------
def test_diverges_is_inconclusive_not_fail():
    p = lec_run.parse_equiv_output(DIVERGE_OUTPUT)
    assert p["verdict"] == "INCONCLUSIVE", p["verdict_explanation"]
    assert p["equivalent"] is False           # visible non-PASS, never vacuous
    assert p["unproven"] == 12150
    assert "diverge" in p["verdict_explanation"].lower()


def test_flat_wall_is_inconclusive_not_fail():
    p = lec_run.parse_equiv_output(FLAT_WALL_OUTPUT)
    assert p["verdict"] == "INCONCLUSIVE", p["verdict_explanation"]
    assert p["equivalent"] is False
    assert p["unproven"] == 909
    assert "converge" in p["verdict_explanation"].lower()


def test_report_marks_non_convergence_and_inconclusive():
    p = lec_run.parse_equiv_output(FLAT_WALL_OUTPUT)
    r = lec_run.build_report(p, "chip_top", "netlist.v", None)
    assert r["verdict"] == "INCONCLUSIVE"
    assert r["inconclusive"] is True
    assert r["non_convergence"] is True
    assert r["non_equivalent_points"] == 0     # zero counterexamples


# ---------------------------------------------------------------------------
# §4.05 NO-LEAK — a real counterexample ALWAYS stays FAIL.
# ---------------------------------------------------------------------------
def test_genuine_counterexample_is_fail():
    p = lec_run.parse_equiv_output(COUNTEREXAMPLE_OUTPUT)
    assert p["verdict"] == "FAIL", p["verdict_explanation"]
    assert p["equivalent"] is False


def test_flat_wall_with_counterexample_stays_fail():
    p = lec_run.parse_equiv_output(FLAT_WALL_WITH_CTREX)
    assert p["verdict"] == "FAIL", (
        "a counterexample must win over the flat-wall signature (§4.05)")


# ---------------------------------------------------------------------------
# downstream gate — non-convergence INCONCLUSIVE is non-blocking, NOT
# LEC_NOT_EQUIVALENT; a counterexample still FAILs.
# ---------------------------------------------------------------------------
def _run_gate(tmp_path, raw):
    p = lec_run.parse_equiv_output(raw)
    r = lec_run.build_report(p, "chip_top", "netlist.v", None)
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "lec.json").write_text(json.dumps(r))
    (tmp_path / "reports" / "lec.rpt").write_text(raw)
    res = gate.audit(tmp_path)
    return res, gate.main([str(tmp_path)])


def test_gate_flat_wall_is_non_blocking_inconclusive(tmp_path):
    res, rc = _run_gate(tmp_path, FLAT_WALL_OUTPUT)
    assert res.inconclusive is True
    assert res.passed is False
    rules = {f.rule for f in res.findings}
    assert "LEC_INCONCLUSIVE_NONCONVERGENCE" in rules
    assert "LEC_NOT_EQUIVALENT" not in rules
  # #208 follow-up: still NON-BLOCKING (flow_compliance resolves rc=3 +
    # the PASS_WITH_WAIVERS sentinel to WAIVED-DEFERRED, so the step does
    # not fail and nothing cascades to MISSING) but no longer a BARE PASS,
    # which rc=0 silently was at the `program_exit_zero` gate.
    assert rc == 3, "INCONCLUSIVE: non-blocking, but never a bare PASS"


def test_gate_counterexample_is_hard_fail(tmp_path):
    res, rc = _run_gate(tmp_path, COUNTEREXAMPLE_OUTPUT)
    assert res.passed is False
    assert res.inconclusive is False
    assert rc == 1, "a genuine counterexample must remain a hard FAIL"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
