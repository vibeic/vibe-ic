#!/usr/bin/env python3
"""vibe-ic#925 — a DRC wall-clock timeout must not be EXCUSED.

WHAT WAS WRONG. `_try_svrf_native_drc` bounds the commercial sign-off DRC at a
wall-clock budget. When the engine was killed at that budget the step returned
the word `SKIPPED-CONDITION`. The prose beside it was already honest — it
refuses to call a timeout a violation and refuses to sign off from a partial
report. The WORD was not:

  * `SKIPPED-CONDITION` is `flow_compliance_check`'s vocabulary, not this
    runner's (`_VERDICT_TIERS`), and `_aggregate_verdict` enumerates its own
    vocabulary and lets anything else fall through to the catch-all
    `return "PASS"`.  MEASURED on the unfixed tree: a plan whose only non-PASS
    step was a timed-out sign-off DRC aggregated to a plain green `"PASS"` —
    not even PASS_WITH_WAIVERS.
  * `verdict.is_excused("NOT_APPLICABLE")` is True, so wherever
    the word IS adjudicated the step is subtracted from `total_required`: a DRC
    that ran out of time stopped being owed an answer at all.

The tests below ASK THE PROGRAMS — the real `_try_svrf_native_drc`, the real
`_aggregate_verdict`, the real `verdict` — and never recompute a
rule locally.

TWO ARMS, both required by the issue's acceptance criteria:

  ARM 1 (`test_timeout_*`)  a DRC that timed out must stay owed and must keep
        the run from being green.  These FAIL on the unfixed program.
  ARM 2 (`test_guard_*`)    a DRC that genuinely does not apply to a design,
        or whose tool is genuinely absent, must STILL be excusable, and the
        shared tier vocabulary must be untouched.  These PASS on BOTH arms —
        they exist so a future fix cannot satisfy ARM 1 by breaking the
        legitimate skip, or by relabelling the vocabulary so the finding
        disappears.
"""
from __future__ import annotations

import sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import verdict as T      # noqa: E402












# ── ARM 1 — the timeout must remain outstanding and must hold the run back ──






# ── ARM 2 — PAIRED GUARDS: these must NOT change ───────────────────────────
def test_guard_shared_tier_vocabulary_is_untouched():
    """The fix must NOT be achieved by relabelling the shared vocabulary.

    `SKIPPED-CONDITION` means "this design legitimately has none", and the
    whole analog track resolves to it on a pure-digital design. Moving that
    word out of EXCUSED would make every such run non-green — laundering the
    #925 finding away by breaking the tier it was introduced for."""
    assert T.is_excused("NOT_APPLICABLE") is True
    assert T.is_non_green("NOT_APPLICABLE") is False
    assert T.scoped_into_verdict(
        {"status": "NOT_APPLICABLE", "stage": T.ANALOG_STAGE}) is False
    # R-0915-85 — the word is `NOT_APPLICABLE` and `EXCUSED` holds it alone.
    # `SKIPPED-CONDITION` is refused at `parse`, which is a STRONGER guard than
    # the membership this line used to assert: the word cannot re-enter the
    # register by being written somewhere, because it cannot be written.
    assert T.EXCUSED == frozenset({"NOT_APPLICABLE"}), T.EXCUSED
    with pytest.raises(T.UnknownVerdictWord):
        T.parse("SKIPPED-CONDITION")
