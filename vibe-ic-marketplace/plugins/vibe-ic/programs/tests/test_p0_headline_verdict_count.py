#!/usr/bin/env python3
"""vibe-ic — the P0 headline counted checkers that never ran (vibe-ic#559).

`name=f"… {len(_STRUCTURAL_RTL_GATES)} checkers"` is the number REGISTERED. 33 of
the 243 reject the argv the umbrella builds — argparse exits 2 before the check
runs — so they return `NOT_INVOCABLE` and what they audit is unaudited. The
per-gate disclosure underneath has always been complete; the headline is the part
a reader takes at face value.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import flow_compliance_check as F  # noqa: E402


def test_not_invocable_is_not_a_verdict():
    """THE defect. A gate that never ran said nothing about the design, so it
    cannot be counted among the checks that did."""
    recs = [{"verdict": "PASS"}, {"verdict": "NOT_INVOCABLE"},
            {"verdict": "SKIP"}, {"verdict": "FAIL"}]
    assert F._p0_verdict_count(recs) == 3


def test_skip_and_waived_ARE_verdicts():
    """`SKIP` means the input was absent and `WAIVED` means it was excused — both
    are statements about what was audited. Only NOT_INVOCABLE is the absence of
    one, which is why `_gate_invocation` made it a first-class outcome instead of
    folding it into SKIP (#492)."""
    recs = [{"verdict": "SKIP"}, {"verdict": "WAIVED"}]
    assert F._p0_verdict_count(recs) == 2


def test_no_records_is_zero_not_the_registry_size():
    """A project with no RTL dispatches nothing. Reporting the registry size here
    is the shape this fix exists to remove."""
    assert F._p0_verdict_count([]) == 0


def test_a_record_with_no_verdict_key_still_counts_as_one():
    """Fail-safe direction: an unfamiliar record shape must not silently shrink
    the count, because a smaller headline reads as MORE honesty than is due."""
    assert F._p0_verdict_count([{"gate": "x"}]) == 1


def test_the_headline_states_both_numbers():
    """Both, always — not `N checkers` when they agree and something longer when
    they do not. A line that changes shape only in the bad case is a line nobody
    has read in the good case, so nobody recognises the bad one either."""
    import inspect
    src = inspect.getsource(F)
    i = src.index('name=(f"Structural-RTL gates')
    line = src[i:i + 200]
    assert "_n_verdict" in line and "_n_registered" in line, line
    assert "returned a verdict" in line, line


# NO AUTOMATED "nothing parses the headline" TEST, deliberately.
#
# Two attempts, both false-positive:
#   1. any named-group regex in a file that also contains the word `checkers` —
#      flagged a hex-literal parser and a `-name` parser;
#   2. the literal `P0 umbrella` / `Structural-RTL gates` anywhere in a file —
#      flagged six files that mention the umbrella in PROSE (docstrings and
#      comments), including this fix's own drift checker.
#
# Text matching cannot separate "code parses this string" from "a comment names
# the concept", and a test that reports a finding which is not one gets worked
# around rather than obeyed. The check was done by READING the candidates
# instead, and the result is recorded where the reword lives:
# `final_report_generate` writes its own P0 heading and never reads this one;
# `checker_execution_wiring_audit`'s `checkers` field is its own JSON. Both were
# opened, not grepped.

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
