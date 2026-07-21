#!/usr/bin/env python3
"""#192 (item 2) — the phase step verdict must come from the LEC producer's own
`reports/lec.json:verdict`, NOT from the mere presence / exit of the tool.

Before the fix `step_dft_lec_chain` reported the `lec_equivalence` step PASS
whenever `reports/lec.json` existed, regardless of what the report said — so a
report whose `verdict` was FAIL was booked as a PASS step (the same
rc==0-vs-json.verdict drift previously seen on subservient's lec_equivalence).
Combined with a hard-macro run that never actually compared points (item 1),
this produced the worst pairing: a step that says PASS, over a report that says
FAIL, about a comparison that never ran.

`lec_step_status_from_report` is the pure mapper the step now delegates to. These
tests pin it against the exact verdict strings lec_run emits; any correct
implementation satisfies them.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import design_one_shot_runner as dosr  # noqa: E402


def _status_for(doc) -> str:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "lec.json"
        p.write_text(doc if isinstance(doc, str) else json.dumps(doc))
        return dosr.lec_step_status_from_report(p)[0]


class LecStepVerdictTest(unittest.TestCase):
    def test_pass_verdict_is_a_pass_step(self):
        self.assertEqual(_status_for({"verdict": "PASS", "equivalent": True,
                                      "compared_points": 65}), "PASS")

    def test_fail_verdict_is_a_fail_step_not_pass(self):
        """The whole point: a FAIL report must NOT be a PASS step just because
        the file exists."""
        self.assertEqual(_status_for({"verdict": "FAIL", "equivalent": False,
                                      "compared_points": 66,
                                      "unproven_points": 2}), "FAIL")

    def test_inconclusive_is_a_disclosed_skip(self):
        """A 0-compared-points INCONCLUSIVE (e.g. an unstaged hard macro) is a
        disclosed SKIP — never a hard FAIL that cascades, never a vacuous PASS."""
        self.assertEqual(_status_for({"verdict": "INCONCLUSIVE",
                                      "equivalent": False,
                                      "compared_points": 0}), "SKIP")

    def test_skipped_condition_is_a_disclosed_skip(self):
        self.assertEqual(_status_for({"verdict": "SKIPPED-CONDITION",
                                      "equivalent": False}), "SKIP")

    def test_missing_verdict_is_never_a_vacuous_pass(self):
        """Absence of a clean verdict must not buy a PASS — the exact
        report-presence-equals-PASS bug this fixes."""
        self.assertNotEqual(_status_for({"equivalent": True,
                                         "compared_points": 65}), "PASS")

    def test_unreadable_report_is_never_a_pass(self):
        self.assertEqual(_status_for("{ this is not json"), "SKIP")


if __name__ == "__main__":
    unittest.main(verbosity=2)
