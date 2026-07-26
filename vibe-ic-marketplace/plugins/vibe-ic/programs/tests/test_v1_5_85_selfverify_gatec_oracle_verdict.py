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

import harness_exact_selfverify as hes  # noqa: E402


_MISMATCH_LINE = ("ORACLE_MISMATCH: no single serial framing reassembles the "
                  "DUT stream to the golden for all vectors (possible "
                  "functional defect)")


# ── NEGATIVE — the defect must FAIL ────────────────────────────────────────
@pytest.mark.parametrize("npass,ntotal", [(16, 28), (8, 28), (26, 28), (0, 28)])
def test_failing_oracle_run_is_a_FAIL_not_inconclusive(npass, ntotal):
    """A broken DUT must not reach INCONCLUSIVE — that is what let it pass."""
    out = f"ORACLE_TB_DONE pass={npass}/{ntotal}\n{_MISMATCH_LINE}\n"
    ok, reason = hes._tb_verdict(out)
    assert ok is False, (
        f"pass={npass}/{ntotal} with ORACLE_MISMATCH must be FAIL, got "
        f"{ok!r} ({reason}). INCONCLUSIVE here is the measured defect: it "
        f"does not block, so the overall gate reports PASS for broken RTL.")
    assert f"{npass}/{ntotal}" in reason


def test_mismatch_without_summary_is_a_FAIL():
    """ORACLE_MISMATCH alone carries no FAIL/ERROR token — still a failure."""
    ok, reason = hes._tb_verdict(_MISMATCH_LINE + "\n")
    assert ok is False, f"bare ORACLE_MISMATCH must FAIL, got {ok!r} ({reason})"


def test_gate_c_blocks_on_a_failing_oracle_run(tmp_path):
    """End-to-end: gate C's verdict field must not be INCONCLUSIVE."""
    g = {"gate": "C_functional_tb"}
    ok, reason = hes._tb_verdict(
        f"ORACLE_TB_DONE pass=16/28\n{_MISMATCH_LINE}\n")
    g["verdict"] = ("PASS" if ok else
                    "BLOCK" if ok is False else "INCONCLUSIVE")
    assert g["verdict"] == "BLOCK", (
        "a functionally-broken DUT must BLOCK the sole-emit-path gate")


# ── POSITIVE — the fixed case must PASS ────────────────────────────────────
def test_passing_oracle_run_is_a_PASS():
    ok, reason = hes._tb_verdict("ORACLE_TB_DONE pass=28/28\n")
    assert ok is True, f"28/28 must PASS, got {ok!r} ({reason})"
    assert "28/28" in reason


def test_zero_vector_oracle_run_is_not_a_silent_pass():
    """`pass=0/0` proves nothing — it must never read as PASS."""
    ok, _ = hes._tb_verdict("ORACLE_TB_DONE pass=0/0\n")
    assert ok is not True


# ── REGRESSION — pre-existing conventions must be untouched ────────────────
@pytest.mark.parametrize("blob,expected", [
    ("Mismatches: 0 in 100\n", True),
    ("Mismatches: 7 in 100\n", False),
    ("ALL_TESTS_PASSED\n", True),
    ("TEST FAILED\n", False),
    ("checks=10016 errors=0\n", True),
    ("simulation finished\n", None),          # genuinely inconclusive
])
def test_existing_conventions_unchanged(blob, expected):
    ok, _ = hes._tb_verdict(blob)
    assert ok is expected


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
    ours = hes._TB_ORACLE_RE.search(sample)
    theirs = runner_re.search(sample)
    assert ours and theirs, "both patterns must match the canonical summary"
    assert ours.groups() == theirs.groups() == ("13", "28")
