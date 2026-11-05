#!/usr/bin/env python3
"""test_landing_cadence.py — the version-derived test cadence, wired into the
LANDING and into the PUSH.

Every test here is written so that it can GO RED. The asymmetry under test is
one-directional and the failure that matters is silent, so each pole is
asserted with its own opposite: a milestone that CAN be let off by a subset is
the defect, and a check that only ever sees the happy tier would not notice.

Policy (gatekeeper_review.derive_cadence, 2026-06-17):
    x.y.0 -> FULL      x.y.Z -> TARGETED      no bump -> NONE
"""
from __future__ import annotations

import re
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
_REPO = _PLUGIN.parents[2]
_LAND = _REPO / "tools" / "gatekeeper-land.sh"
_HOOK = _REPO / "tools" / "git-hooks" / "pre-push"




































# --------------------------------------------------------------------------
# a real git repo carrying a real version bump
# --------------------------------------------------------------------------
_PLUGIN_JSON = "vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json"




# ============================ POLE A — patch ==============================



# ========================== POLE B — milestone ============================





# ================== the direction of every failure ========================





# ============ describe(): the claim is earned from the selection ==========













# ==================== the landing script is actually wired ================

def _code_only(text: str) -> str:
    """Shell text with comment lines removed. Asserting a token is 'not in' a
    file that EXPLAINS why the token is forbidden matches the explanation and
    reports the prose as the defect."""
    return "\n".join(l for l in text.splitlines()
                      if not l.lstrip().startswith("#"))


def test_the_landing_derives_the_cadence_and_does_not_accept_one():
    t = _LAND.read_text()
    assert "landing_cadence.py" in t, "the landing never asks what tier it owes"
    assert re.search(r'LANDING_CADENCE="?\$\(python3 "\$PROGRAMS/landing_cadence\.py"', t)
    assert '[ -n "$LANDING_CADENCE" ] || LANDING_CADENCE=FULL' in t, \
        "an unanswerable cadence must fall back to the STRICTER tier"
    assert "--cadence" not in _code_only(t), \
        "the landing must not be able to assert its own tier"


def test_the_landing_runs_the_whole_tree_on_a_milestone():
    t = _LAND.read_text()
    assert 'if [ "$LANDING_CADENCE" = "FULL" ]; then' in t
    assert "--emit-full-selection" in t
    assert "ci_targeted_test_select.py" in t, "the patch tier must be unchanged"


def test_the_landing_tells_the_review_what_it_actually_ran():
    t = _LAND.read_text()
    assert "--pytest-cmd" in t, (
        "without this the review's cadence gate takes its 'none supplied' "
        "branch and a milestone landing is impossible")
    assert "$LANE_DIR/pytest-cmd.txt" in t, \
        "a lane subshell variable never reaches the main shell"


def test_the_stamp_records_the_cadence_it_was_earned_at():
    t = _LAND.read_text()
    assert "printf 'cadence=%s\\n' \"$LANDING_CADENCE\"" in t
    # line 1 must still be the commit and only the commit: two existing readers
    # depend on it (`head -1` here, and an older whole-file hook that fails closed)
    i = t.index("printf 'cadence=%s")
    assert "git rev-parse HEAD" in t[i - 200:i]


# ======================= the hook enforces the asymmetry ==================
# Driven by EXECUTING the shipped block, not by reading it: a text assertion
# cannot tell a guard from a guard with an inverted comparison.

_HOOK_BLOCK_START = "    STAMP_CADENCE=\"$(sed -n 's/^cadence=//p' \"$STAMP\" | tail -1)\""
_HOOK_BLOCK_END = "    STAMP_BASE="




















# ------- milestone_check(): the hook's narrower question, three answers ------
