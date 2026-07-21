#!/usr/bin/env python3
"""#189 — netgen wraps `Final result:` onto two lines on stdout.

    report file : "Final result: Circuits match uniquely."
    stdout      : "Final result: \\nCircuits match uniquely."

Callers classify `transcript + report`, so the blob carries both forms. The bare
`Final result: ` from stdout is an unreadable terminal line; under the unanimity
rule that blocks MATCH — while a real MISMATCH still classifies correctly,
because its token matches anywhere in the blob. That asymmetry means a genuinely
clean LVS can never be reported as MATCH.

Measured on `spm` @ v1.4.74, fresh run, instrumented at the call site:

    classify(report only)         -> MATCH
    classify(transcript + report) -> INCOMPLETE
        finals = ['Final result: ', 'Final result: Circuits match uniquely.']

These tests exercise ONLY the public `classify()` with the verbatim shapes netgen
emits, so any correct implementation satisfies them — they do not encode how the
fix is written. The negative half is the load-bearing half: folding a wrapped line
must never manufacture positive evidence.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lvs_verdict_tokens as lvt            # noqa: E402

# ── verbatim shapes captured from a real run ──────────────────────────────
REPORT_MATCH = (
    "Cell pin lists are equivalent.\n"
    "Device classes spm and spm are equivalent.\n"
    "\n"
    "Final result: Circuits match uniquely.\n"
)

# netgen stdout: the verdict text lands on the NEXT line, and a Tcl error
# follows it (`localize_nets` throws in every observed run).
STDOUT_MATCH = (
    "Circuit 1 contains 339 devices, Circuit 2 contains 339 devices.\n"
    "Circuit 1 contains 369 nets,    Circuit 2 contains 369 nets.\n"
    "\n"
    "\n"
    "Final result: \n"
    "Circuits match uniquely.\n"
    ".\n"
    'can\'t read "lvs_final": no such variable\n'
    '    while executing\n'
    '"netgen::localize_nets $lvs_final"\n'
)

REPORT_MISMATCH = (
    "Cell pin lists for spm and spm altered to match.\n"
    "\n"
    "Final result: Top level cell failed pin matching.\n"
)

STDOUT_MISMATCH = (
    "Circuit 1 contains 369 nets,    Circuit 2 contains 371 nets. *** MISMATCH ***\n"
    "\n"
    "Final result: \n"
    "Top level cell failed pin matching.\n"
)


class FinalResultLineWrapTest(unittest.TestCase):
    # ── the defect ────────────────────────────────────────────────────────
    def test_clean_lvs_survives_the_wrapped_stdout_form(self):
        """The whole point: a clean compare must classify MATCH on the blob."""
        blob = STDOUT_MATCH + "\n" + REPORT_MATCH
        self.assertEqual(lvt.classify(blob), "MATCH")

    def test_wrapped_form_alone_is_readable(self):
        """stdout on its own carries a real verdict; it is not 'no verdict'."""
        self.assertEqual(lvt.classify(STDOUT_MATCH), "MATCH")

    def test_report_only_was_already_correct(self):
        """Guards the half that never broke, so a fix cannot regress it."""
        self.assertEqual(lvt.classify(REPORT_MATCH), "MATCH")

    # ── the load-bearing negative half ────────────────────────────────────
    def test_real_mismatch_stays_mismatch_in_both_forms(self):
        self.assertEqual(lvt.classify(REPORT_MISMATCH), "MISMATCH")
        self.assertEqual(lvt.classify(STDOUT_MISMATCH), "MISMATCH")
        self.assertEqual(
            lvt.classify(STDOUT_MISMATCH + "\n" + REPORT_MISMATCH), "MISMATCH")

    def test_a_wrapped_mismatch_beside_a_clean_report_is_a_mismatch(self):
        """Power-aware fails while plain LVS passes — the failure must win."""
        blob = STDOUT_MISMATCH + "\n" + REPORT_MATCH
        self.assertEqual(lvt.classify(blob), "MISMATCH")

    def test_truncated_run_stays_incomplete(self):
        """A killed compare has a bare line with NOTHING after it — no verdict
        may be conjured from the void."""
        blob = ("Flattening unmatched subcell spm_sub in circuit 1\n"
                "Final result: \n")
        self.assertEqual(lvt.classify(blob), "INCOMPLETE")

    def test_bare_line_followed_by_unrelated_text_is_not_a_pass(self):
        """Folding must not let arbitrary following output become the verdict."""
        blob = ("Final result: \n"
                "Reading netlist file spm_extracted.sp\n")
        self.assertNotEqual(lvt.classify(blob), "MATCH")

    def test_blank_lines_between_do_not_bridge_into_a_pass(self):
        """Only an immediate continuation is netgen's wrap; a verdict separated
        by blank lines is not the same statement."""
        blob = ("Final result: \n"
                "\n"
                "\n"
                "Circuits match uniquely.\n")
        self.assertNotEqual(blob.count("Final result:"), 0)
        self.assertIn(lvt.classify(blob), ("INCOMPLETE", "MISMATCH"))

    def test_design_named_escape_still_cannot_buy_a_pass(self):
        """The anchored-token guard must survive the fold: a design/path that
        contains the phrase is not a verdict."""
        blob = ("Final result: \n"
                "read from /work/circuits match uniquely/top.spice\n")
        self.assertNotEqual(lvt.classify(blob), "MATCH")


if __name__ == "__main__":
    unittest.main(verbosity=2)
