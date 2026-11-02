"""R-icgate3 — "category not found" must be a fact about the REPORT, never a
claim that the rule class went unchecked.

MEASURED on spm run15 (8HD-4, `_lane_icspm5/run15`). Step 31's sign-off audit
(`reports/phase3/drc_signoff.json`) opened with

    DRC_CATEGORY_PRESENT  WARNING
    DRC category 'density' not found in reports

which reads as "density was not checked". It was:

  * `reports/phase3/drc_signoff.log` line 12 --
        Selected decks: ... cup, density, df_10, ...
  * the same log, lines 481-486 --
        Executing rule PL.8 / M1.4 / M2.4 / M3.4 / M4.4 / M5.4
  * the report (`drc_signoff.rpt`, a KLayout report-database) carries
    ZERO items for any of those six, so all six PASSED.

WHY THE REPORT CANNOT SAY SO. The open PDK's density deck emits its category
INSIDE the branch that detects the violation
(`rule_decks/density.rb`: `if (metal1.area / chip_area) * 100 < 30 then
extent.output('M1.4', ...)`), so a clean density rule leaves no trace at all.
MEASURED on the same report: 764 rule classes declared, 762 of them carrying
zero items -- the format DOES declare clean rules -- while 11 of the 774 rules
the log says executed declared no class, the six density rules among them.

The old sentence was therefore satisfiable ONLY by a die that FAILS density: it
reported the good outcome as a gap, and it was the FIRST thing a reader saw on
a row whose real defect was `DRC_REAL_VIOLATIONS_FOUND: 5`.

WHAT DID NOT CHANGE, and it is the point: this probe has never gated `passed`
(the audit's own comment says so), and the fix touches no count, no verdict and
no exit code. Re-running `drc_report_check . --mode drc --signoff --under
reports/phase3/drc_signoff.rpt` over run15's bytes before and after gives
rc=1 / passed=False / 5 findings / categories_found
['spacing','width','antenna','via','enclosure'] / real_violation_total=5 on
BOTH sides. Only the sentence differs.

chip-AGNOSTIC: no IC, vendor, SKU or process is reasoned about.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import eda_report_audit as A            # noqa: E402


#: A KLayout report-database shaped like run15's: it DECLARES clean rule
#: classes, and names no density rule because none was violated.
RDB = """<?xml version="1.0" encoding="utf-8"?>
<report-database>
 <generator>drc: script='gf180mcu.drc'</generator>
 <top-cell>chip_top</top-cell>
 <categories>
  <category><name>V1.1</name><description>Min/max via1 size</description></category>
  <category><name>M1.1</name><description>min. metal1 width</description></category>
  <category><name>M1.2</name><description>min. metal1 spacing</description></category>
  <category><name>CO.6</name><description>metal1 overlap of contact</description></category>
  <category><name>ANT.8</name><description>related gate oxide area</description></category>
 </categories>
 <items>
  <item><category>'ANT.8'</category><values/></item>
 </items>
</report-database>
"""

#: The tool's own account of the SAME invocation.
TOOL_LOG = """2026-09-21 17:27:17: Starting running Klayout DRC runset
2026-09-21 17:27:17: Selected decks: V1.1, cup, density, metal1, antenna_poly2
2026-09-21 17:32:33: Executing rule PL.8
2026-09-21 17:32:33: Executing rule M1.4
"""

#: The same log with every mention of the class removed -- the deck really did
#: not run one.
TOOL_LOG_NO_DENSITY = """2026-09-21 17:27:17: Starting running Klayout DRC runset
2026-09-21 17:27:17: Selected decks: V1.1, cup, metal1, antenna_poly2
2026-09-21 17:32:33: Executing rule M1.1
"""


class _Proj(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._t = tempfile.TemporaryDirectory()
        self.proj = Path(self._t.name)
        self.rpt_dir = self.proj / "reports" / "phase3"
        self.rpt_dir.mkdir(parents=True)

    def tearDown(self):
        self._t.cleanup()

    def _audit(self, *, log_text=None, rdb=RDB):
        (self.rpt_dir / "drc_signoff.rpt").write_text(rdb)
        if log_text is not None:
            (self.rpt_dir / "drc_signoff.log").write_text(log_text)
        out = self.proj / "out.json"
        # Driven the way the flow drives it (step 31's own gate clause), so the
        # `--signoff` policy this row measures is the one under test.
        cp = subprocess.run(
            [sys.executable, str(PROGRAMS / "drc_report_check.py"), ".",
             "--mode", "drc", "--signoff",
             "--under", "reports/phase3/drc_signoff.rpt",
             "--subject", "reports/phase3/drc_signoff.rpt",
             "--json", str(out)],
            cwd=self.proj, capture_output=True, text=True)
        self.assertTrue(out.is_file(),
                        f"no verdict JSON written; rc={cp.returncode} "
                        f"{cp.stderr[-400:]}")
        return cp.returncode, json.loads(out.read_text())

    @staticmethod
    def _density_msg(doc):
        for f in doc["findings"]:
            if f["rule"] == "DRC_CATEGORY_PRESENT" and "'density'" in f["message"]:
                return f["message"]
        return ""


class ACleanRuleClassIsNotAGap(_Proj):

    def test_the_message_names_the_scope_it_searched(self):
        _rc, doc = self._audit(log_text=TOOL_LOG)
        msg = self._density_msg(doc)
        self.assertTrue(msg, "the density category finding disappeared")
        self.assertIn("reports/phase3/drc_signoff.rpt", msg,
                      "the reader is not told what was searched")

    def test_a_log_that_names_the_class_is_quoted_and_the_absence_explained(self):
        _rc, doc = self._audit(log_text=TOOL_LOG)
        msg = self._density_msg(doc)
        self.assertIn("reports/phase3/drc_signoff.log", msg)
        self.assertIn("DOES name it", msg)
        self.assertIn("lists only VIOLATIONS", msg)
        self.assertNotIn("not found in reports", msg,
                         "the sentence a reader took as 'not checked' survives")

    # ---- the other direction --------------------------------------------- #
    def test_negative_control_a_log_that_does_NOT_name_it_claims_nothing(self):
        _rc, doc = self._audit(log_text=TOOL_LOG_NO_DENSITY)
        msg = self._density_msg(doc)
        self.assertIn("no tool log beside them names it either", msg)
        self.assertNotIn("DOES name it", msg)
        self.assertNotIn("drc_signoff.log", msg,
                         "a log was cited that does not name the class")

    def test_negative_control_no_sibling_log_at_all(self):
        _rc, doc = self._audit(log_text=None)
        msg = self._density_msg(doc)
        self.assertIn("cannot be decided from these artefacts", msg)

    def test_negative_control_a_class_the_report_DOES_name_gets_no_finding(self):
        """`spacing` is in the report's own descriptions, so nothing is said
        about it -- the probe must still be quiet where it always was."""
        _rc, doc = self._audit(log_text=TOOL_LOG)
        said = [f["message"] for f in doc["findings"]
                if f["rule"] == "DRC_CATEGORY_PRESENT"]
        self.assertFalse([m for m in said if "'spacing'" in m],
                         "a class the report names acquired a finding")
        self.assertIn("spacing", doc["summary"]["categories_found"])

    def test_negative_control_nothing_but_the_sentence_moves(self):
        """The verdict, the counts and the found-set are identical with and
        without the sibling log -- the new reader touches none of them."""
        _rc_a, with_log = self._audit(log_text=TOOL_LOG)
        self.tearDown(); self.setUp()
        _rc_b, without = self._audit(log_text=None)
        for key in ("categories_found", "real_violation_total", "has_count"):
            self.assertEqual(with_log["summary"].get(key),
                             without["summary"].get(key),
                             f"{key} moved because a log was read")
        self.assertEqual(with_log["passed"], without["passed"])
        self.assertEqual(len(with_log["findings"]), len(without["findings"]))

    def test_negative_control_a_scoped_file_is_not_read_as_its_own_sibling(self):
        """A log already IN scope contributes through the normal path; it must
        not also be cited as the outside witness."""
        (self.rpt_dir / "drc_signoff.rpt").write_text(RDB)
        log = self.rpt_dir / "drc_signoff.log"
        log.write_text(TOOL_LOG)
        self.assertEqual(
            A._category_also_named_beside(A.re.compile("density", A.re.I),
                                          [log], self.proj),
            "", "a file in scope was cited as a sibling of itself")


if __name__ == "__main__":
    unittest.main()
