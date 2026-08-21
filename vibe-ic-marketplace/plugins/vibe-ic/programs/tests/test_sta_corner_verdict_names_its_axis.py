"""A PASS verdict line must name the corner scope it actually swept.

`post_route_signoff_corner_check` reads the multicorner SPEF report, whose
corners are RC/parasitic corners (`corners_available: max,min,nom`). It rendered
a clean sweep as:

    all analyzed sign-off corners MET (governing worst-slack +0.070 ns)

The scope was captured into the JSON as `corners_available` and then dropped on
the way to the reason string. So a PASS produced by an RC-axis-only sweep is
textually indistinguishable from a PASS covering every declared sign-off axis —
including the process axis (SS/TT/FF), which this gate never reads.

Measured on a real run: this gate returned PASS with
`setup_worst_slack_ns: 6.77` while a sibling gate reading the process axis
reported SS setup `-2.850 ns` on the same design in the same run. The word
"analyzed" was carrying the entire disclosure, silently.

This is a DISCLOSURE fix. No verdict changes: a design that passed still passes
and a design that failed still fails. What changes is that the PASS line now
states which corners it is a statement about.

§4.05 no-leak: the fix reads only the report the gate already parses. It
introduces no new input, no design-specific string, and no oracle; the scope
text comes from the report's own `corners_available` declaration.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import post_route_signoff_corner_check as G  # noqa: E402

_CLEAN_RC_ONLY = """# Multi-corner SPEF STA (TAPEOUT-SIGNOFF P1)
# SETUP corner: max-RC   HOLD corner: min-RC
# corners_available: max,min,nom
=== SETUP (max-RC corner, SPEF=max) ===
worst slack max 6.77
tns max 0.00
=== HOLD (min-RC corner, SPEF=min) ===
worst slack min 0.07
tns max 0.00
"""

_CLEAN_NO_SCOPE_DECLARED = """# Multi-corner SPEF STA (TAPEOUT-SIGNOFF P1)
=== SETUP (max-RC corner, SPEF=max) ===
worst slack max 0.42
tns max 0.00
=== HOLD (min-RC corner, SPEF=min) ===
worst slack min 0.54
tns max 0.00
"""

_VIOLATED = """# Multi-corner SPEF STA (TAPEOUT-SIGNOFF P1)
# corners_available: max,min,nom
=== SETUP (max-RC corner, SPEF=max) ===
worst slack max -1.71
tns max -10.91
=== HOLD (min-RC corner, SPEF=min) ===
worst slack min 0.54
tns max -1.82
"""


def test_pass_verdict_line_names_the_corners_it_swept():
    """The reason string itself must carry the scope, not only the JSON."""
    res = G.evaluate(_CLEAN_RC_ONLY)
    assert res["verdict"] == "PASS"
    reason = "; ".join(str(r) for r in res["reasons"])
    # The scope reaches the human-readable verdict line.
    assert "max,min,nom" in reason, (
        "a PASS line that does not name its analyzed corners is "
        "indistinguishable from a full-axis sign-off PASS; got: " + reason)


def test_undeclared_scope_is_stated_not_omitted():
    """A report that declares no scope must say so — silence is the defect."""
    res = G.evaluate(_CLEAN_NO_SCOPE_DECLARED)
    assert res["verdict"] == "PASS"
    reason = "; ".join(str(r) for r in res["reasons"])
    assert "UNDECLARED" in reason, (
        "an unstated scope must be rendered as UNDECLARED rather than dropped; "
        "got: " + reason)


def test_negative_control_the_assertion_can_fail():
    """Prove the check above is capable of failing.

    The pre-fix reason string is reconstructed verbatim. If the assertion in
    `test_pass_verdict_line_names_the_corners_it_swept` could not fail against
    it, that test would be proving nothing.
    """
    pre_fix_reason = "all analyzed sign-off corners MET (governing worst-slack +0.070 ns)"
    assert "max,min,nom" not in pre_fix_reason
    assert "UNDECLARED" not in pre_fix_reason


def test_verdicts_are_unchanged_by_the_disclosure_fix():
    """No behavioural regression: this fix changes wording, never a verdict."""
    assert G.evaluate(_CLEAN_RC_ONLY)["verdict"] == "PASS"
    assert G.evaluate(_CLEAN_NO_SCOPE_DECLARED)["verdict"] == "PASS"
    assert G.evaluate(_VIOLATED)["verdict"] == "FAIL"
    # A FAIL already names its axis inline ("max-RC" / "min-RC"); unchanged.
    fail_reason = "; ".join(str(r) for r in G.evaluate(_VIOLATED)["reasons"])
    assert "max-RC" in fail_reason


def test_scope_is_still_available_structurally():
    """The JSON field that existed before must keep working for machine readers."""
    assert G.evaluate(_CLEAN_RC_ONLY)["corners_available"] == "max,min,nom"
    assert G.evaluate(_CLEAN_NO_SCOPE_DECLARED)["corners_available"] is None
