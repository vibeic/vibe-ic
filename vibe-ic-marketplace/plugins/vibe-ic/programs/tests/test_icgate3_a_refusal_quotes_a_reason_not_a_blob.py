"""R-icgate3 — a refusal must publish a REASON, never a blob, and never a
sentence that stops mid-clause.

MEASURED on spm run15 (8HD-4, `_lane_icspm5/run15`, read over ssh; the report
bytes are transcribed below). Three sign-off rows failed for reasons a reader
could not act on:

  reports/phase3/tapeout_precheck.json, findings[1].message --

      antenna_report_check refused:         "sha256": "c9dc6e...",
              "is_file": true
            }, ...

  a JSON FRAGMENT published as the reason a die was refused. The delegate had
  ALREADY written `reports/phase3/general_precheck/precheck_antenna.json`,
  which on the same bytes says

      ANTENNA_VIOLATIONS_ZERO: Antenna violations present: 4 (net+pin);
      insert diode or re-route

  findings[2] and findings[3].message --

      drc_report_check refused: drc_report_check: audit re-emitted to
      .../precheck_magic_drc.json by the wrapper (eda_report_audit left it
      absent).

  the program names itself twice, and what is published is a housekeeping note
  about the WRAPPER while `precheck_magic_drc.json` held
  `DRC_REAL_VIOLATIONS_FOUND: 10 real DRC violation(s) ...`.

  reports/orchestrator/phase3_one_shot.json, steps[24].detail --

      ...; UNDETERMINED/General.FlowMar

  a byte cut landing inside a rule NAME, with nothing saying it was cut.

THREE PROPERTIES, EACH PROVED BOTH WAYS:
  A. the ladder quotes the delegate's own findings, and falls back to console
     output only when there is no readable verdict -- and says so when it does;
  B. a program's name appears once;
  C. no clause is cut mid-word in silence, and a reader is told which artefact
     holds the whole text.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process. The
transcribed fixtures are this flow's own report SHAPES.
"""
import json
import sys
import unittest
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import general_precheck as GP             # noqa: E402


#: `precheck_antenna.json` as run15 wrote it, trimmed to the keys this reader
#: uses. The four findings and their order are the measured ones.
MEASURED_ANTENNA_REPORT = {
    "program": "eda_report_audit:antenna",
    "passed": False,
    "findings": [
        {"rule": "ANTENNA_NO_TOOL_SIGNATURE", "severity": "ERROR",
         "message": "report lacks any known antenna tool signature (one of: "
                    "['openroad', 'check_antenna', 'ANT-', 'antenna check']"
                    "... ). Hand-typed reports rejected.",
         "file": "reports/phase3/antenna_violations.rpt"},
        {"rule": "ANTENNA_VIOLATIONS_ZERO", "severity": "ERROR",
         "message": "Antenna violations present: 4 (net+pin); insert diode or "
                    "re-route",
         "file": "steps/phase3/stage3/"
                 "26_antenna_check_gate_oxide_protection/antenna.rpt"},
    ],
    "summary": {"files_found": 5, "violations": 4, "clean": False},
}

#: The `tail` run15 actually published as the antenna refusal's whole reason:
#: the closing lines of the delegate's own report, echoed to stdout.
MEASURED_ANTENNA_TAIL = (
    '        "sha256": "c9dc6e6b8bda3be55aeb6edede6008ddca27023e50e589f13d2f'
    'e657a09b4630",\n        "is_file": true\n      }\n    ],\n    "sha256": '
    '"1513993ff695b70b4ca3ed52daaa1b355ab0810c5c97a719b6ad59a15d8264ea"\n  }\n}'
)

MEASURED_DRC_REPORT = {
    "program": "eda_report_audit:drc",
    "passed": False,
    "findings": [
        {"rule": "DRC_REAL_VIOLATIONS_FOUND", "severity": "ERROR",
         "message": "10 real DRC violation(s) found across 2 report(s) with a "
                    "determinable count",
         "file": "steps/phase3/stage3/"
                 "31_physical_verification_drc_lvs_erc_density/drc_signoff.rpt"},
    ],
    "summary": {"files_found": 2, "real_violation_total": 10},
}

#: The `tail` run15 published for both DRC rungs -- a note about the WRAPPER,
#: already opening with the program's own name.
MEASURED_DRC_TAIL = (
    "drc_report_check: audit re-emitted to "
    "reports/phase3/general_precheck/precheck_magic_drc.json by the wrapper "
    "(eda_report_audit left it absent)."
)


class _Tmp(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)

    def tearDown(self):
        self._t.cleanup()

    def _report(self, doc, name="precheck.json"):
        p = self.tmp / name
        p.write_text(json.dumps(doc))
        return p


# --------------------------------------------------------------------------- #
# A — the reason comes from the delegate's own report
# --------------------------------------------------------------------------- #
class RefusalQuotesAReason(_Tmp):

    def test_the_delegates_own_findings_replace_the_echoed_blob(self):
        report = self._report(MEASURED_ANTENNA_REPORT, "precheck_antenna.json")
        reason = GP._delegate_reason(report, "antenna_report_check",
                                     MEASURED_ANTENNA_TAIL)
        self.assertIn("Antenna violations present: 4", reason,
                      "the count the delegate measured never reached the reader")
        self.assertIn("ANTENNA_VIOLATIONS_ZERO", reason)
        self.assertNotIn('"is_file"', reason,
                         "the published reason is still a JSON fragment")
        self.assertNotIn('"sha256"', reason)

    def test_the_drc_rung_publishes_the_violation_count_not_a_wrapper_note(self):
        report = self._report(MEASURED_DRC_REPORT, "precheck_magic_drc.json")
        reason = GP._delegate_reason(report, "drc_report_check",
                                     MEASURED_DRC_TAIL)
        self.assertIn("10 real DRC violation(s)", reason)
        self.assertNotIn("re-emitted", reason,
                         "a note about the wrapper is not a reason about the "
                         "layout")

    def test_every_finding_is_named_not_just_the_first(self):
        """A refusal names its WHOLE set -- the repo's own doctrine."""
        report = self._report(MEASURED_ANTENNA_REPORT, "precheck_antenna.json")
        reason = GP._delegate_reason(report, "antenna_report_check", "")
        for f in MEASURED_ANTENNA_REPORT["findings"]:
            self.assertIn(f["rule"], reason)

    def test_findings_beyond_the_budget_are_counted_and_the_report_named(self):
        doc = {"findings": [{"rule": f"R{i}", "message": f"m{i}"}
                            for i in range(GP._DELEGATE_REASON_MAX_PARTS + 3)]}
        report = self._report(doc, "precheck_many.json")
        reason = GP._delegate_reason(report, "some_check", "")
        self.assertIn("+3 more finding(s) not quoted here", reason)
        self.assertIn("precheck_many.json", reason,
                      "the reader is not told where the rest are")

    # ---- the other direction -------------------------------------------- #
    def test_negative_control_no_readable_verdict_falls_back_and_SAYS_SO(self):
        """"Could not read it" is not "read it and it was empty"."""
        missing = self.tmp / "never_written.json"
        reason = GP._delegate_reason(missing, "drc_report_check",
                                     MEASURED_DRC_TAIL)
        self.assertIn("no verdict readable in never_written.json", reason)
        self.assertIn("console output ended", reason)
        self.assertIn("re-emitted", reason,
                      "the tail is the only evidence left and must survive")

    def test_negative_control_an_empty_report_and_no_output_names_both_gaps(self):
        empty = self._report({}, "empty.json")
        reason = GP._delegate_reason(empty, "some_check", "")
        self.assertIn("empty.json", reason)
        self.assertIn("no reason could be read", reason)

    # ---- the whole rung, through `_step_delegate`, both rc arms ---------- #
    def _rung(self, rc, report_doc, chatter_stdout="", chatter_stderr=""):
        """Drive the real `_step_delegate` with a delegate that behaves as
        `antenna_report_check` did on run15: it WRITES its report and ALSO
        echoes it, so the ladder has both a verdict and chatter to choose
        between."""
        report_rel = "reports/phase3/general_precheck/precheck_x.json"
        project = self.tmp / "proj"
        (project / "reports/phase3/general_precheck").mkdir(parents=True)
        pg = self.tmp / "pg"
        pg.mkdir()
        (pg / "antenna_report_check.py").write_text("")
        step = GP.Step(step_id="Checker.X", label="X", order=99,
                       source="DELEGATED", refuses_on="violations",
                       delegate=GP.Delegate(program="antenna_report_check",
                                            argv_tail=(),
                                            report_rel=report_rel))

        def runner(cmd, timeout):
            if report_doc is not None:
                (project / report_rel).write_text(json.dumps(report_doc))
            return rc, chatter_stdout, chatter_stderr

        ev = GP.StepEvidence(step_id=step.step_id, label=step.label,
                             order=step.order, source=step.source,
                             verdict=GP.NOT_DETERMINED,
                             refuses_on=step.refuses_on)
        GP._step_delegate(ev, step, project, runner, pg, None)
        return ev

    def test_negative_control_a_genuine_refusal_still_refuses(self):
        """The reader changed; the VERDICT did not. rc=1 is still FAIL, and it
        now carries the delegate's own count."""
        ev = self._rung(1, MEASURED_ANTENNA_REPORT,
                        chatter_stdout=MEASURED_ANTENNA_TAIL)
        self.assertEqual(ev.verdict, GP.FAIL)
        self.assertIn("Antenna violations present: 4", ev.evidence)
        self.assertNotIn('"is_file"', ev.evidence)
        self.assertEqual(ev.evidence.count("antenna_report_check refused"), 1)

    def test_negative_control_a_clean_delegate_still_passes(self):
        """rc=0 is untouched: a passing rung says so and names no violation."""
        ev = self._rung(0, {"program": "eda_report_audit:antenna",
                            "passed": True, "findings": [],
                            "summary": {"violations": 0, "clean": True}},
                        chatter_stdout="antenna_report_check: 0 violation(s)")
        self.assertEqual(ev.verdict, GP.PASS)
        self.assertIn("exited 0", ev.evidence)
        self.assertEqual(ev.evidence.count("antenna_report_check"), 1,
                         "the pass line names the program twice")

    def test_negative_control_rc2_is_still_neither_a_pass_nor_a_refusal(self):
        ev = self._rung(2, None, chatter_stderr="antenna_report_check: boom")
        self.assertIn("neither a pass", ev.evidence)
        self.assertNotEqual(ev.verdict, GP.PASS)
        self.assertEqual(ev.evidence.count("antenna_report_check"), 1)


# --------------------------------------------------------------------------- #
# B — a program names itself once
# --------------------------------------------------------------------------- #
class ProgramNamesItselfOnce(unittest.TestCase):

    def test_the_doubled_prefix_is_removed(self):
        self.assertEqual(
            GP._undouble("drc_report_check", MEASURED_DRC_TAIL),
            "audit re-emitted to reports/phase3/general_precheck/"
            "precheck_magic_drc.json by the wrapper (eda_report_audit left it "
            "absent).")

    def test_negative_control_text_that_does_not_self_name_is_byte_identical(self):
        for s in ("", "audit re-emitted", "other_check: something",
                  "the drc_report_check: not at the head"):
            self.assertEqual(GP._undouble("drc_report_check", s), s.lstrip())

    def test_negative_control_only_one_prefix_is_removed(self):
        """Two really are two. The ladder adds exactly one back."""
        doubled = "p: p: body"
        self.assertEqual(GP._undouble("p", doubled), "p: body")


if __name__ == "__main__":
    unittest.main()
