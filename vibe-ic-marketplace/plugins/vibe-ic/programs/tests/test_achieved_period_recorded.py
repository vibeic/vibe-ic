""""Asked" and "reached" must both be on disk. vibe-ic#1097 S8.

WHAT THIS FILE PINS, AND WHY EACH HALF IS NEEDED
================================================
Two things had to be true for the achieved period to stop being invisible, and
they fail in opposite directions, so both are asserted here:

1. **The runner emits it on a PASS too.** It already emitted on a FAIL. The
   `setup_wns < 0` guard meant the measurement was kept for exactly the runs
   nobody needs convincing about — MEASURED at `f9c13443`, 13 published roots
   reached post-route STA and 2 carried the artefact.
2. **The gate can tell "nothing to record" from "not recorded".** A run whose
   STA produced no slack must be VACUOUS (rc 2), not red; a run whose STA DID
   produce one and recorded nothing must be rc 1. Collapsing those two is how a
   gate becomes either a nag or a ban.

THE DOMAIN TRAP THIS FILE EXISTS TO KEEP CLOSED
===============================================
`wns max` and `worst slack max` are NOT two spellings of one number, and the
first draft of the checker treated them as such. WNS is the worst NEGATIVE
slack and is clamped at 0 when nothing violates. The published spm cell carries
both in one report:

    wns max          0.00
    worst slack max  5.24

Reading `wns` would compute `achieved = asked - 0 = asked` on EVERY passing
design: an artefact that exists, is internally consistent, and states that every
design reaches exactly what it asked for. That is worse than the silence this
work removes, because it is a false measurement rather than a missing one, so
`test_wns_is_not_read_as_the_worst_slack` pins it with a report carrying both.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PLUGIN = Path(__file__).resolve().parents[2]
REPO = PLUGIN.parents[2]




_GOOD = {"spec_period_ns": 10.0, "achievable_period_ns": 4.76,
         "worst_setup_slack_ns": 5.24, "relaxation_applied": False}


# ---------------------------------------------------------------------------
# the implication the gate asserts
# ---------------------------------------------------------------------------












# ---------------------------------------------------------------------------
# the domain trap
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# the runner is actually wired — a program without a caller is the #725 shape
# ---------------------------------------------------------------------------
def test_the_runner_emits_on_a_pass_and_not_only_on_a_failure():
    """THE two-arm subject. `phase3_one_shot_runner` guarded the emit with
    `setup_wns < 0`, so the measurement existed only for failing runs."""
    src = (PLUGIN / "programs" / "phase3_one_shot_runner.py").read_text()
    assert "if mc_ocv_ok and setup_wns is not None:" in src, (
        "the achievable-Fmax emit is no longer unconditional on a measured "
        "setup number — if the `setup_wns < 0` guard came back, the achieved "
        "period is again recorded only for runs that failed (vibe-ic#1097 S8)")
    assert "if mc_ocv_ok and setup_wns is not None and setup_wns < 0:" not in src


def test_the_gate_is_wired_into_the_flow():
    """`step_required_inputs_check` is the standing warning: the capability
    landed, no runner called it, and the BEHAVIOUR did not exist for a release.
    A declared clause is what makes this a behaviour."""
    yaml_text = (PLUGIN / "flow" / "phase1_phase2_phase3.yaml").read_text()
    assert "achieved_period_recorded_check" in yaml_text, (
        "the gate exists but no flow step declares it — that is the #725 shape "
        "this issue explicitly warns about")


# ---------------------------------------------------------------------------
# the corpus this was measured on
# ---------------------------------------------------------------------------
