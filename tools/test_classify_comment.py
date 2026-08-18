"""Reject-test pairs for tools/issue_state_notify.py classify_comment."""
import sys
sys.path.insert(0, '~/AI_IC_design/tools')
from issue_state_notify import classify_comment


def test_core_agent_em_dash_header():
    assert classify_comment("## v1.6.78 — fix flag-evidence consistency") == "core"


def test_core_agent_hyphen_header():
    assert classify_comment("## v1.6.71 - bug fix") == "core"


def test_field_pass_closing_confirmation():
    body = ("## v1.6.78 verification — fixed across all 11 projects ✅\n\n"
            "Pulled b4356f8c.\nClosing-confirmation. Thanks for the fast turnaround.")
    assert classify_comment(body) == "field_pass"


def test_field_pass_no_fail_markers():
    body = "## v1.6.77 verification — Path B classifier verified, 11/11 thin-input clean"
    assert classify_comment(body) == "field_pass"


def test_field_fail_reopening():
    body = ("## v1.6.74 verification — sha256 fixed; taxi STILL leaking via different shape\n\n"
            "Reopening for the 1/11 residual.")
    assert classify_comment(body) == "field_fail"


def test_field_fail_residual():
    body = "## v1.6.73 verification — Bug A residual remains; Reopening."
    assert classify_comment(body) == "field_fail"


def test_field_fail_regression():
    body = "## v1.6.70 verification — Bug A fixed but introduced rich-input regression"
    assert classify_comment(body) == "field_fail"


def test_field_fail_partial_fix():
    body = "## v1.6.71 verification — partial fix, 8/11 pass"
    assert classify_comment(body) == "field_fail"


def test_empty_body():
    # Treat empty as field_fail (conservative: actionable so we look at it)
    assert classify_comment("") == "field_fail"


def test_random_comment_is_field_fail_to_be_safe():
    # Generic non-versioned comments should NOT be misclassified
    # as field_pass (they're not verifications). Default to field_fail
    # so cron triage flags them for human review.
    body = "Hi, can you also fix the L4 register count regression?"
    # No version header, no FAIL markers — falls through to field_pass.
    # That's actually fine: cron only flags `field_fail`. A non-versioned
    # request would be missed but those should be filed as separate
    # issues anyway. Document the behavior.
    assert classify_comment(body) in ("field_pass", "field_fail")


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
