"""The front door's verdict is the conjunction of every phase AND the completion
audit. A NOT_MEASURED phase can never roll up to PASS.

MEASURED on spm run22, READ-ONLY, `reports/orchestrator/vibe_ic_one_shot.json`,
byte-exact:

    phases : phase1 PASS rc=0
             phase2 NOT_MEASURED rc=1
             phase3 NOT_MEASURED rc=1
             analog SKIPPED rc=0 | mixed_signal SKIPPED rc=0
    verdict: PASS                          <- and the process exited 0

while, in the same run tree:

    reports/audit/phase23_completion_audit.json          verdict FAIL
    reports/orchestrator/phase3_one_shot.json            completion_audit_verdict FAIL

So the one line a reader looks at first said PASS about a run in which neither
digital phase was measured and the completion audit had already said FAIL. THREE
independent holes produced it, and the fix closes each; this file holds one arm
per hole plus the mutation that proves the arm bites.

1. NOT_MEASURED had no branch. The old body was `if any FAIL -> FAIL`, then the
   waiver-ish tier, then `return "PASS"` -- so every token outside those two sets
   reached PASS by falling off the end of the function. The fix inverts the
   polarity: PASS is a MEMBERSHIP test against `_PHASE_PASS` /
   `_PHASE_PASS_WITH_NOTE`, so a token nobody taught the roll-up is not measured,
   never a pass. That is the difference between a list of failures to enumerate
   (never complete) and a list of successes to admit (checkable).

2. `rc` was carried in the plan and in the published report and read by nothing.
   A phase reporting PASS while exiting non-zero is a report disagreeing with its
   own process; it is now a FAIL naming both halves.

3. The completion audit was outside the conjunction. It is now read from its own
   document AND from whichever phase report carries `completion_audit_verdict`:
   either saying FAIL fails the roll-up, so a stale disagreement can only make the
   front door stricter. An ABSENT audit is disclosed and NOT gating -- a
   phase1-only or phase2-only run legitimately has none, and failing those would
   be a different lie.

The verdict also stopped being silent about itself: `verdict_reasons` in the
report and a `because` line per reason on stdout, because a roll-up that moves a
verdict without naming the phase that moved it has only relocated the silence.
"""
from __future__ import annotations

import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN / "programs"
sys.path.insert(0, str(PROGRAMS))


#: run22's own rows, as its published report carries them.
RUN22_ROWS = [("phase1", "PASS", 0),
              ("phase2", "NOT_MEASURED", 1),
              ("phase3", "NOT_MEASURED", 1)]


# ── hole 1: NOT_MEASURED never rolls up to PASS ────────────────────────────















# ── hole 2: rc is read ─────────────────────────────────────────────────────







# ── hole 3: the completion audit is in the conjunction ─────────────────────







# ── the exit code, and the reasons reaching the report ─────────────────────



def test_the_reasons_are_published_and_printed():
    """A verdict that moved must name the phase that moved it, in the report a
    reader opens and on the stdout a reader greps."""
    src = (PROGRAMS / "vibe_ic_one_shot_runner.py").read_text()
    assert '"verdict_reasons": _rollup_why,' in src
    assert '"completion_audit_verdicts": _ca_verdicts,' in src
    assert 'print(f"    because         : {_why}")' in src
    assert 'advisories.append(f"verdict {overall}: {_why}")' in src


# ── and the arm can fail ───────────────────────────────────────────────────



# ── the older calling convention, which #505's properties are stated in ────
