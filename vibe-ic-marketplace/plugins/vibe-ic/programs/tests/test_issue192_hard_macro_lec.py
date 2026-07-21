#!/usr/bin/env python3
"""#192 — a hard macro staged on only ONE side aborts `hierarchy -check`, and
that never-ran comparison was booked as a hard FAIL.

    ERROR: Module `\\fakeram45_2048x39' referenced in module `\\top' in cell
           `\\u_sram' is not part of the design.

`hierarchy -check` aborts BEFORE `equiv_make`, so 0 points are compared — that
is evidence the comparison never STARTED, not evidence of non-equivalence. The
old generic `parse_error` branch booked it as FAIL (`the RTL and gate netlist
may genuinely differ`), reporting a comparison that never ran as if equivalence
had been tested and failed. The fix classifies this narrow shape INCONCLUSIVE.

WHY NOT auto-stage the macro and compare: in-container negative controls proved
that naive symmetric staging (full behavioural model on both sides) AND a
`-lib` blackbox BOTH produce a FALSE PASS on a memory macro — even for a genuine
logic bug in the netlist that FEEDS the macro — because yosys equiv's name-based
net matching mis-handles the hierarchical macro I/O. A false LEC PASS ships a
broken netlist as verified, strictly worse than the false FAIL removed here.
Sound hard-macro equivalence needs a blackbox assume-guarantee this recipe
cannot guarantee → the honest outcome is a DISCLOSED, non-blocking INCONCLUSIVE
(close with sign-off LEC), never a fabricated verdict in either direction.

These tests exercise ONLY the public `parse_equiv_output` / `build_report` and
the downstream gate `lec_equivalence_check` with the verbatim yosys shapes — so
any correct implementation satisfies them; they do not encode how the fix is
written. The load-bearing negative half is that a REAL mismatch (a miter that
DID run and left points unproven) is UNTOUCHED and still FAILs.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lec_run                       # noqa: E402
import lec_equivalence_check as gate  # noqa: E402  (downstream consumer)

# ── verbatim shape captured from a real vibeic-eda yosys 0.67 run ──────────
# The gold side elaborated and ran MANY non-frontend passes (MEMORY_MAP,
# FLATTEN, ASYNC2SYNC, SPLITNETS); the gate side then read its netlist and the
# HIERARCHY pass aborted on the unstaged macro. So the run got PAST the read —
# `frontend_aborted_before_elaboration` is False here — which is exactly why a
# distinct undefined-module branch is needed and the frontend-abort path does
# not cover it.
HIER_ABORT_LOG = """\
1. Executing Verilog-2005 frontend: /work/rtl/mymacro.v
2. Executing Verilog-2005 frontend: /work/rtl/top.v
3. Executing PREP pass.
3.4. Executing MEMORY_COLLECT pass.
4. Executing MEMORY_MAP pass (converting memories to logic and flip-flops).
5. Executing FLATTEN pass (flatten design).
6. Executing ASYNC2SYNC pass.
7. Executing OPT_CLEAN pass (remove unused cells and wires).
8. Executing SPLITNETS pass (splitting up multi-bit signals).
9. Executing Verilog-2005 frontend: /work/reports/../gate.v
10. Executing HIERARCHY pass (managing design hierarchy).
ERROR: Module `\\fakeram45_2048x39' referenced in module `\\top' in cell \
`\\u_sram' is not part of the design.
"""

# A REAL mismatch: a miter DID run and left points unproven. There is NO
# undefined-module abort here — this is the load-bearing negative control.
REAL_MISMATCH_LOG = """\
9. Executing EQUIV_MAKE pass.
Found 66 $equiv cells in equiv.
11. Executing EQUIV_INDUCT pass.
12. Executing EQUIV_STATUS pass.
Found 66 $equiv cells in equiv:
  Of those cells 64 are proven and 2 are unproven.
"""

# A genuine clean PASS — must be entirely unaffected by the new branch.
CLEAN_PASS_LOG = """\
12. Executing EQUIV_STATUS pass.
Found 65 $equiv cells in equiv:
  Of those cells 65 are proven and 0 are unproven.
  Equivalence successfully proven!
"""


class HardMacroLecTest(unittest.TestCase):
    # ── the defect ────────────────────────────────────────────────────────
    def test_hierarchy_abort_is_inconclusive_not_fail(self):
        """The whole point: a never-ran comparison must NOT be booked FAIL."""
        p = lec_run.parse_equiv_output(HIER_ABORT_LOG)
        self.assertEqual(p["verdict"], "INCONCLUSIVE")
        self.assertFalse(p["equivalent"])
        self.assertTrue(p["parse_error"])

    def test_the_unstaged_macro_is_named(self):
        """The macro must be surfaced so a reviewer sees WHY no miter ran."""
        self.assertEqual(lec_run.undefined_macro_modules(HIER_ABORT_LOG),
                         ["fakeram45_2048x39"])
        p = lec_run.parse_equiv_output(HIER_ABORT_LOG)
        self.assertIn("fakeram45_2048x39", p["undefined_macro_modules"])
        r = lec_run.build_report(p, "top", "netlist.v", None)
        self.assertIn("fakeram45_2048x39", r["undefined_macro_modules"])
        # 0 points compared, and flagged inconclusive for the gate.
        self.assertEqual(r["compared_points"], 0)
        self.assertTrue(r["inconclusive"])

    def test_downstream_gate_treats_it_as_non_blocking_not_fail(self):
        """End-to-end: the gate must NOT hard-FAIL an INCONCLUSIVE 0-point run —
        a hard FAIL cascade-marks downstream steps MISSING."""
        p = lec_run.parse_equiv_output(HIER_ABORT_LOG)
        r = lec_run.build_report(p, "top", "netlist.v", None)
        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            (proj / "reports").mkdir()
            (proj / gate.LEC_JSON_REL).write_text(json.dumps(r))
            (proj / gate.LEC_RPT_REL).write_text(HIER_ABORT_LOG)
            res = gate.audit(proj)
        self.assertTrue(res.inconclusive)
        self.assertFalse(res.passed)
        # Not a hard ERROR verdict — the inconclusive path returns before the
        # substance FAIL findings are appended.
        self.assertFalse(any(f.severity == "ERROR" for f in res.findings))

    # ── the load-bearing negative half ────────────────────────────────────
    def test_real_mismatch_still_fails(self):
        """A miter that RAN and left points unproven is a real FAIL — the new
        branch must never touch it (no undefined-module line, parse_error
        False)."""
        p = lec_run.parse_equiv_output(REAL_MISMATCH_LOG)
        self.assertEqual(p["verdict"], "FAIL")
        self.assertFalse(p["equivalent"])
        self.assertEqual(p["undefined_macro_modules"], [])

    def test_clean_pass_unaffected(self):
        p = lec_run.parse_equiv_output(CLEAN_PASS_LOG)
        self.assertEqual(p["verdict"], "PASS")
        self.assertTrue(p["equivalent"])
        self.assertEqual(p["undefined_macro_modules"], [])

    def test_no_undefined_module_when_absent(self):
        """The detector must not fire on ordinary logs."""
        self.assertEqual(lec_run.undefined_macro_modules(CLEAN_PASS_LOG), [])
        self.assertEqual(lec_run.undefined_macro_modules(REAL_MISMATCH_LOG), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
