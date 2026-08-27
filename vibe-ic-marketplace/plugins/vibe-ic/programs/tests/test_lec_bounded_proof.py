#!/usr/bin/env python3
"""An unconvergeable equivalence proof must SAY SO -- and a real mismatch must
still say FAIL.

MEASURED 2026-08-27 on a clean-room VerilogEval-Human sweep (Prob030_popcount255,
a 255-bit popcount whose gold is purely combinational). Two separate defects,
both in how the plugin CALLS yosys and what it RECORDS -- yosys itself behaved
correctly throughout.

  (1) NOTHING WAS RECORDED WHEN THE BOUND FIRED. `yosys -s reports/lec_equiv.ys`
      ground at 99.9% CPU for the whole 7195s container budget inside
      `equiv_simple` and was SIGTERMed. That leaves `parse_error=True` (no
      equiv_status was reached), and `should_retry_gold_with_slang` keyed on
      exactly that observable -- "the built-in gold read built NO miter" -- so
      it read the budget kill as a GOLD-READ failure and re-ran the entire
      proof under `read_slang` with the SAME budget. Observed live: the first
      yosys went <defunct> at the deadline, `reports/lec_equiv.ys` was
      rewritten with `read_slang` 20s later, and a fresh yosys started on it.
      No reports/lec.json and no reports/lec.rpt existed at the deadline --
      not a FAIL, not a SKIPPED-CONDITION, nothing. The `-DSYNTHESIS` rung
      makes three full budgets reachable before the honest answer hits disk.

  (2) THE CHECKER WENT BLIND ON COMBINATIONAL MISMATCHES. A `popcount8` gold
      was synthesised and exactly ONE gate in the netlist was mutated
      ($_NAND_ -> $_NOR_). Unpatched main 40d0e14c08 reported that genuinely
      non-equivalent pair as **INCONCLUSIVE**, not FAIL, because the script
      runs `equiv_induct -seq 4/16/64` on a miter with no state, where every
      rung necessarily prints `Proved 0 previously unproven $equiv cells.` --
      the exact phrase `induction_did_not_converge` reads as "a flat induction
      wall" and the classifier uses to re-class NOT_EQUIVALENT to INCONCLUSIVE.
      On a stateless design that signature fires on EVERY real mismatch.

INCONCLUSIVE / SKIPPED-CONDITION is NOT PASS and NOT FAIL, and the tests below
pin all three corners: the honest shrug, the genuine PASS, and the genuine FAIL.

chip-AGNOSTIC: pure log/verdict fixtures; no chip, PDK or vendor literal.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lec_run  # noqa: E402
import design_one_shot_runner as dosr  # noqa: E402


_STAT_COMB = """
=== equiv ===

        +----------Local Count, excluding submodules.
        |
      222 wires
      113 cells
       25   $_NAND_
       33   $_NOR_
       11   $_NOT_
        8   $add
       36   $equiv
"""

_STAT_SEQ = _STAT_COMB.replace("        8   $add", "        8   $_DFF_P_")

_FLAT_WALL = """
19. Executing EQUIV_INDUCT pass.
Found 4 unproven $equiv cells in module equiv:
  Proof for induction step failed. Trying to prove individual $equiv from workset.
Proved 0 previously unproven $equiv cells.
22. Executing EQUIV_STATUS pass.
Found 6 $equiv cells in module equiv:
  Of those cells 2 are proven and 4 are unproven.
Found a total of 4 unproven $equiv cells.
"""


class BudgetKillIsNotAFrontendFailure(unittest.TestCase):
    """Defect (1): a wall-budget kill must not be retried as a gold-read
    failure. BOTH POLES -- the budget kill declines the retry, an ACTUAL
    frontend abort with the SAME parse_error still gets it."""

    def test_budget_killed_log_blocks_the_retry(self):
        log = "Yosys 0.68\n17. Executing EQUIV_SIMPLE pass.\n" + \
            f"{lec_run._TIMEOUT_MARKER} after 7195s"
        blocked, why = lec_run.budget_kill_blocks_frontend_retry(log)
        self.assertTrue(blocked)
        self.assertIn("wall budget", why)
        retry, reason = lec_run.should_retry_gold_with_slang(
            {"parse_error": True}, log, requires_sv2017=False)
        self.assertFalse(
            retry,
            "a wall-budget kill was retried under a different gold frontend; "
            "that spends the budget again and records nothing")
        self.assertIn("was NOT the failure", reason)

    def test_a_real_frontend_abort_still_gets_the_retry(self):
        """THE CONTROL. The discriminator must not fire on everything: a
        zero-miter run with NO budget marker keeps the read_slang fallback it
        has always had."""
        log = ("Yosys 0.68\nERROR: Parameter with non-constant value.\n")
        blocked, _ = lec_run.budget_kill_blocks_frontend_retry(log)
        self.assertFalse(blocked)
        retry, _ = lec_run.should_retry_gold_with_slang(
            {"parse_error": True}, log, requires_sv2017=True)
        self.assertTrue(
            retry,
            "the capable SV-2017 gold frontend must still be tried on a "
            "genuine zero-miter frontend abort")

    def test_budget_kill_records_a_visible_non_pass_not_nothing(self):
        log = ("Yosys 0.68\n17. Executing EQUIV_SIMPLE pass.\n"
               f"{lec_run._TIMEOUT_MARKER} after 120s")
        p = lec_run.parse_equiv_output(log)
        self.assertEqual(p["verdict"], "SKIPPED-CONDITION")
        self.assertFalse(p["equivalent"])
        self.assertNotEqual(p["verdict"], "PASS")


class StatelessMiterCannotHaveAnInductionDepthProblem(unittest.TestCase):
    """Defect (2): the flat-induction-wall re-class must require positive
    evidence that the miter HOLDS STATE. BOTH POLES."""

    def test_combinational_miter_is_recognised_as_stateless(self):
        stateless, why = lec_run.miter_is_stateless(_STAT_COMB)
        self.assertTrue(stateless)
        self.assertIn("NO state", why)

    def test_sequential_miter_is_not_claimed_stateless(self):
        """THE CONTROL. One flip-flop in the histogram and the predicate must
        say 'unknown', so every sequential design keeps its old verdict."""
        stateless, why = lec_run.miter_is_stateless(_STAT_SEQ)
        self.assertFalse(stateless)
        self.assertIn("$_DFF_P_", why)

    def test_liberty_mapped_miter_is_not_claimed_stateless(self):
        """Fail-open: an unrecognised (PDK) cell name is NOT proof of
        statelessness."""
        stat = _STAT_COMB.replace("        8   $add",
                                  "        8   some_pdk_cell_xyz")
        self.assertFalse(lec_run.miter_is_stateless(stat)[0])

    def test_no_stat_block_leaves_behaviour_unchanged(self):
        self.assertFalse(lec_run.miter_is_stateless("Yosys 0.68\n")[0])

    def test_combinational_mismatch_is_FAIL_not_INCONCLUSIVE(self):
        """THE REGRESSION. This is the exact shape that unpatched main called
        INCONCLUSIVE."""
        p = lec_run.parse_equiv_output(_STAT_COMB + _FLAT_WALL)
        self.assertEqual(
            p["verdict"], "FAIL",
            "a stateless miter with unproven points was softened to a "
            "non-blocking verdict by an induction-depth excuse that cannot "
            "apply to a design with no state")
        self.assertFalse(p["equivalent"])

    def test_sequential_flat_wall_is_still_INCONCLUSIVE(self):
        """THE CONTROL FOR THE FIX. The same log with ONE flip-flop in the
        histogram must keep the sequential-depth INCONCLUSIVE -- the fix must
        not turn every non-convergent deep-sequential proof into a false
        FAIL."""
        p = lec_run.parse_equiv_output(_STAT_SEQ + _FLAT_WALL)
        self.assertEqual(p["verdict"], "INCONCLUSIVE")
        self.assertFalse(p["equivalent"])


class InconclusiveIsNeverConsumedAsEquivalence(unittest.TestCase):
    """The guard the task asks for: this FAILS if a future change ever lets an
    undecided proof be counted as equivalence. It pins BOTH the producer's own
    `equivalent` field and the downstream step-status consumer."""

    NON_PASS = ("INCONCLUSIVE", "SKIPPED-CONDITION", "FAIL", "", "UNKNOWN")

    def test_producer_never_marks_a_non_pass_verdict_equivalent(self):
        for verdict in self.NON_PASS:
            with self.subTest(verdict=verdict):
                rep = lec_run.build_report(
                    {"proven": 1, "unproven": 1, "total": 2,
                     "sat_model_unsupported_cells": [], "unproven_cells": [],
                     "success_line": False, "parse_error": False,
                     "equivalent": False, "verdict": verdict,
                     "verdict_explanation": "x"},
                    "top", "netlist.v", None)
                self.assertFalse(
                    rep["equivalent"],
                    f"verdict {verdict!r} was recorded as equivalent")

    def test_downstream_step_status_never_promotes_a_non_pass_to_PASS(self):
        for verdict in self.NON_PASS:
            with self.subTest(verdict=verdict):
                with tempfile.TemporaryDirectory() as d:
                    f = Path(d) / "lec.json"
                    f.write_text(json.dumps({"verdict": verdict}))
                    status, _ = dosr.lec_step_status_from_report(f)
                    self.assertNotEqual(
                        status, "PASS",
                        f"step status for verdict {verdict!r} was PASS -- an "
                        "undecided or failed equivalence proof was consumed "
                        "as a proven equivalence")

    def test_a_real_PASS_is_still_a_PASS(self):
        """THE CONTROL. The guard above must not be satisfiable by refusing
        every verdict."""
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "lec.json"
            f.write_text(json.dumps({"verdict": "PASS"}))
            self.assertEqual(dosr.lec_step_status_from_report(f)[0], "PASS")


class TheBoundIsRecordedWithTheOutcome(unittest.TestCase):
    """An honest INCONCLUSIVE must carry what ran out, not just say so in
    prose."""

    def test_the_script_asks_yosys_for_the_evidence_it_needs(self):
        script = lec_run.build_equiv_script(
            ["/g/gold.sv"], "/g/netlist.v", "top", None,
            gate_is_generic=True)
        self.assertIn("equiv_make gold gate equiv", script)
        self.assertIn("\nstat\n", script)
        self.assertLess(
            script.index("\nstat\n"), script.index("equiv_struct"),
            "`stat` must run on the built miter, before the proof stages")


if __name__ == "__main__":
    unittest.main()
