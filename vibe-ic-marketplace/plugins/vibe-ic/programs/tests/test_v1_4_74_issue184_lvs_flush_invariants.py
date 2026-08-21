#!/usr/bin/env python3
"""v1.4.74 — #184 companion invariants for `_read_lvs_report_flushed`.

The #184 flush-read fix landed in v1.4.73 (commit ddb202782) with
`tests/test_v1_4_73_issue184_lvs_flush_reread.py`, which drives the function
through ABSTRACT mock report objects (`_CountLaggingReport` / `_TimedLaggingReport`)
to prove the final re-read + `rc == 0` budget scaling.

This module is the REAL-FILESYSTEM companion, grafted from the independent
reproduction contributed in PR #188 (`fix/lvs-flush-read-race`) and adjusted to
the landed v1.4.73 API (`rc=` / `clean_exit_max_wait=` / `clean_exit_attempts=`).
It exercises the actual `rpt_path.is_file()` / `read_text()` path with real temp
files and threads, and locks in three invariants the abstract-mock suite does
NOT assert:

  * a genuinely-late REAL flush is caught on a clean exit — and the negative
    control (a non-clean `rc` keeps the tight budget) proves the scaling is
    load-bearing, not incidental;
  * the scaled budget must never become a fixed sleep — an already-flushed
    report returns immediately;
  * a CONCLUSIVE MISMATCH is NEVER softened, even with `rc == 0` + a scaled
    budget (the landed suite only covers the TRUNCATED → INCOMPLETE fail-safe,
    never a conclusive non-match).

chip-AGNOSTIC: pure file-I/O timing, no design/PDK literal.
"""
import sys
import threading
import time
import unittest
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as _p3       # noqa: E402
import lvs_verdict_tokens as _lvt          # noqa: E402

MATCH_REPORT = (
    "Contents of circuit 1:  Circuit: 'x'\n"
    "Circuits match uniquely.\n"
    "Final result: Circuits match uniquely.\n")
MISMATCH_REPORT = (
    "Netlists do not match.\n"
    "Final result: Top level cell failed pin matching.\n")
TRUNCATED_REPORT = "Contents of circuit 1:  Circuit: 'x'\nFlattening ...\n"


class ReadFlushedRealFsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(__file__).resolve().parent / "_tmp_v1_4_74"
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

    # ── the fix: a real late flush is caught on a clean exit ──────────────
    def test_real_late_flush_caught_on_clean_exit(self):
        """`rc == 0` scales the budget so a REAL file that flushes well past the
        tight `max_wait` is still polled and read."""
        def land_slow():
            time.sleep(1.0)                     # well past max_wait=0.2
            self.rpt.write_text(MATCH_REPORT)

        t = threading.Thread(target=land_slow)
        t.start()
        try:
            txt = _p3._read_lvs_report_flushed(
                self.rpt, attempts=2, base_delay=0.05, max_wait=0.2,
                rc=0, clean_exit_max_wait=5.0, clean_exit_attempts=60)
        finally:
            t.join()
        self.assertIn("Final result:", txt)

    def test_non_clean_exit_keeps_tight_budget(self):
        """Negative control — the SAME late flush with a non-clean `rc` keeps
        the tight budget and gives up before the flush lands, so the clean-exit
        scaling above is proven load-bearing, not incidental."""
        def land_slow():
            time.sleep(1.0)
            self.rpt.write_text(MATCH_REPORT)

        t = threading.Thread(target=land_slow)
        t.start()
        try:
            txt = _p3._read_lvs_report_flushed(
                self.rpt, attempts=2, base_delay=0.05, max_wait=0.2,
                rc=1, clean_exit_max_wait=5.0, clean_exit_attempts=60)
        finally:
            t.join()
        self.assertNotIn("Final result:", txt)

    # ── the scaled budget must not become a fixed sleep ──────────────────
    def test_clean_exit_returns_as_soon_as_the_marker_present(self):
        self.rpt.write_text(MATCH_REPORT)
        t0 = time.time()
        txt = _p3._read_lvs_report_flushed(
            self.rpt, rc=0, clean_exit_max_wait=60.0, clean_exit_attempts=400)
        self.assertIn("Final result:", txt)
        self.assertLess(time.time() - t0, 2.0,
                        "an already-flushed report must return immediately")

    # ── the negative half: no non-MATCH may ever be softened ─────────────
    def test_real_mismatch_never_softened_even_on_clean_exit(self):
        self.rpt.write_text(MISMATCH_REPORT)
        txt = _p3._read_lvs_report_flushed(
            self.rpt, rc=0, clean_exit_max_wait=1.0, clean_exit_attempts=8)
        self.assertEqual(_lvt.classify(txt), "MISMATCH")

    def test_truncated_stays_incomplete_even_on_clean_exit(self):
        self.rpt.write_text(TRUNCATED_REPORT)
        txt = _p3._read_lvs_report_flushed(
            self.rpt, attempts=1, base_delay=0.01, max_wait=0.05,
            rc=0, clean_exit_max_wait=0.3, clean_exit_attempts=4)
        self.assertEqual(_lvt.classify(txt), "INCOMPLETE")

    def test_absent_report_returns_empty(self):
        txt = _p3._read_lvs_report_flushed(
            self.rpt, attempts=1, base_delay=0.01, max_wait=0.05)
        self.assertEqual(txt, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
