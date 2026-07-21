#!/usr/bin/env python3
"""v1467 — `_read_lvs_report_flushed` must not return pre-flush content.

Measured defect (spm @ v1.4.67, reproduced 3/3, and independently on
subservient): a netgen run that exited 0 and wrote
`Final result: Circuits match uniquely.` to lvs.rpt was stamped
INCOMPLETE / LVS_NO_TERMINAL_VERDICT, because

  (a) the retry loop read, checked the marker, then checked the deadline and
      broke — returning the content read BEFORE the budget expired; and
  (b) the 6 s budget did not cover the overlayfs flush.

Evidence on disk: lvs.rpt mtime 11:04:37.811 (complete, carries the verdict),
lvs_verdict.json stamped INCOMPLETE at 11:04:37.869 — 58 ms later.

The NEGATIVE cases are the load-bearing half: a genuinely truncated report must
still come back without a terminal verdict so it classifies INCOMPLETE. Nothing
in this fix may upgrade an incomplete run to MATCH.
"""
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import phase3_one_shot_runner as _p3       # noqa: E402

MATCH_REPORT = (
    "Contents of circuit 1:  Circuit: 'spm'\n"
    "Contents of circuit 2:  Circuit: 'spm'\n"
    "Circuits match uniquely.\n"
    "Cell pin lists are equivalent.\n"
    "Final result: Circuits match uniquely.\n")

TRUNCATED_REPORT = (
    "Contents of circuit 1:  Circuit: 'spm'\n"
    "Flattening unmatched subcell spm_sub in circuit 1\n")


class ReadFlushedRaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(__file__).resolve().parent / "_tmp_v1467"
        self.tmp.mkdir(exist_ok=True)
        self.rpt = self.tmp / "lvs.rpt"
        if self.rpt.exists():
            self.rpt.unlink()

    def tearDown(self):
        if self.rpt.exists():
            self.rpt.unlink()
        try:
            self.tmp.rmdir()
        except OSError:
            pass

    # ── the defect ────────────────────────────────────────────────────────
    def test_report_landing_just_after_the_budget_is_still_read(self):
        """(a) The post-deadline read catches a marker that lands at the wire.

        Deliberately uses ONLY the pre-v1467 signature (no `netgen_rc`) so this
        is a genuine BEHAVIOURAL control: against the unpatched function it
        fails with an empty read, not with a TypeError about a new kwarg. A
        negative control that only proves the signature changed proves nothing.
        """
        def land_late():
            time.sleep(0.6)                     # after the 0.4 s budget below
            self.rpt.write_text(MATCH_REPORT)

        t = threading.Thread(target=land_late)
        t.start()
        try:
            txt = _p3._read_lvs_report_flushed(
                self.rpt, attempts=1, base_delay=0.05, max_wait=0.4)
        finally:
            t.join()
        self.assertIn("Final result: Circuits match uniquely.", txt,
                      "the marker landed before the final read and must be seen")

    def test_clean_exit_extends_the_budget(self):
        """(b) netgen_rc == 0 waits long enough for a slow overlayfs flush."""
        def land_slow():
            time.sleep(1.0)                     # well past max_wait=0.2
            self.rpt.write_text(MATCH_REPORT)

        t = threading.Thread(target=land_slow)
        t.start()
        try:
            txt = _p3._read_lvs_report_flushed(
                self.rpt, attempts=2, base_delay=0.05,
                max_wait=0.2, netgen_rc=0, clean_exit_wait=5.0)
        finally:
            t.join()
        self.assertIn("Final result:", txt)

    def test_clean_exit_returns_as_soon_as_the_marker_appears(self):
        """The longer budget must not become a fixed sleep."""
        self.rpt.write_text(MATCH_REPORT)
        t0 = time.time()
        txt = _p3._read_lvs_report_flushed(
            self.rpt, netgen_rc=0, clean_exit_wait=60.0)
        self.assertIn("Final result:", txt)
        self.assertLess(time.time() - t0, 2.0,
                        "an already-flushed report must return immediately")

    # ── the negative half: no incomplete run may be upgraded ───────────────
    def test_truncated_report_stays_without_a_terminal_verdict(self):
        self.rpt.write_text(TRUNCATED_REPORT)
        txt = _p3._read_lvs_report_flushed(
            self.rpt, attempts=1, base_delay=0.01, max_wait=0.05)
        self.assertNotIn("Final result:", txt)
        self.assertEqual(_p3._lvt.classify(txt), "INCOMPLETE")

    def test_truncated_report_stays_incomplete_even_on_a_clean_exit(self):
        """rc == 0 buys patience, never a verdict."""
        self.rpt.write_text(TRUNCATED_REPORT)
        txt = _p3._read_lvs_report_flushed(
            self.rpt, attempts=1, base_delay=0.01,
            max_wait=0.05, netgen_rc=0, clean_exit_wait=0.3)
        self.assertEqual(_p3._lvt.classify(txt), "INCOMPLETE")

    def test_absent_report_returns_empty(self):
        txt = _p3._read_lvs_report_flushed(
            self.rpt, attempts=1, base_delay=0.01, max_wait=0.05)
        self.assertEqual(txt, "")

    def test_a_real_mismatch_is_never_softened(self):
        self.rpt.write_text(
            "Netlists do not match.\n"
            "Final result: Top level cell failed pin matching.\n")
        txt = _p3._read_lvs_report_flushed(self.rpt, netgen_rc=0,
                                           clean_exit_wait=1.0)
        self.assertEqual(_p3._lvt.classify(txt), "MISMATCH")


if __name__ == "__main__":
    unittest.main(verbosity=2)
