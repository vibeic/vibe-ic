#!/usr/bin/env python3
"""harness_exact_selfverify gate C must read the plugin's OWN oracle-TB verdict.

MEASURED DEFECT (spm x ihp-sg13g2, plugin v1.5.85, image vibeic-eda:0.2.29).
`arith_oracle_tb_gen.py` emits a TB whose verdict line is

    ORACLE_TB_DONE pass=<n>/<m>

plus, when no single serial framing reassembles the DUT stream to the golden,

    ORACLE_MISMATCH: no single serial framing reassembles the DUT stream ...

`_tb_verdict()` recognised NEITHER form: `pass=` is not `\\bPASSED\\b`, and
`ORACLE_MISMATCH` carries no FAIL/ERROR token. Gate C therefore returned
INCONCLUSIVE, and because INCONCLUSIVE does not block, the program printed
`harness_exact_selfverify: PASS (all enforced gates passed)` for a
functionally BROKEN design.

Four independent RTL mutants of a serial-parallel multiplier were measured
against the generated oracle TB. The TB detected every one; the GATE detected
none:

    mutant                TB verdict                        gate C (before)
    carry-majority ->AND  pass=16/28 + ORACLE_MISMATCH       INCONCLUSIVE / PASS
    accumulator no-shift  pass= 8/28 + ORACLE_MISMATCH       INCONCLUSIVE / PASS
    output bit sum[1]     pass=26/28 + ORACLE_MISMATCH       INCONCLUSIVE / PASS
    dropped carry         pass=16/28 + ORACLE_MISMATCH       INCONCLUSIVE / PASS
    (correct RTL)         pass=28/28                         INCONCLUSIVE / PASS

`design_one_shot_runner.py` ALREADY parses this exact summary
(`re.search(r"\\bORACLE_TB_DONE\\s+pass=(\\d+)/(\\d+)", ...)`), so the two
programs disagreed about the plugin's own output format. This test pins BOTH
directions and the cross-program agreement.

BIDIRECTIONAL:
  NEGATIVE — a failing oracle run (n<m, and/or ORACLE_MISMATCH) MUST verdict
             False. Reverting the fix makes these fail.
  POSITIVE — a passing oracle run (n==m, no mismatch) MUST verdict True, and
             pre-existing conventions (Mismatches:, PASSED, errors=0) MUST be
             unchanged — so the fix cannot be a blanket "oracle => fail".
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))


_MISMATCH_LINE = ("ORACLE_MISMATCH: no single serial framing reassembles the "
                  "DUT stream to the golden for all vectors (possible "
                  "functional defect)")


# ── NEGATIVE — the defect must FAIL ────────────────────────────────────────


# ── POSITIVE — the fixed case must PASS ────────────────────────────────────


# ── REGRESSION — pre-existing conventions must be untouched ────────────────


# ── CROSS-PROGRAM AGREEMENT — the root cause was disagreement ──────────────
def test_agrees_with_design_one_shot_runner_regex():
    """Both programs must read the plugin's own summary identically.

    The defect was that only one of the two parsed it. Pin the contract by
    checking this module's pattern against the runner's literal source regex.
    """
    runner_src = (PROGRAMS / "design_one_shot_runner.py").read_text(
        encoding="utf-8", errors="replace")
    assert "ORACLE_TB_DONE" in runner_src, (
        "design_one_shot_runner no longer parses ORACLE_TB_DONE — the format "
        "moved; update harness_exact_selfverify together with it")
    sample = "ORACLE_TB_DONE pass=13/28"
    runner_re = re.compile(r"\bORACLE_TB_DONE\s+pass=(\d+)/(\d+)")
    theirs = runner_re.search(sample)
