"""v0.3.18 — #521: codify the FIX-ALL-INTO-THE-PLUGIN doctrine into the
user-facing skills so EVERY user inherits it (not just one session's memory).

The doctrine + the loop-until-dry convergence test must live verbatim in both
`community-backlog-submit` and `benchmark-enhancement-capture`, the Bucket-D
honesty rule must explicitly forbid "variance / design-side / not-a-plugin-gap"
as discard reasons, and the field/core-agent-loop STOP CONDITIONs must
cross-reference the clean-room convergence test.

Test name carries `skill_doctrine` so the issue's acceptance
`pytest -k "backlog or capture or skill_doctrine"` selects it.
"""
import re
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
SKILLS = PLUGIN / "skills"

_BACKLOG = SKILLS / "community-backlog-submit" / "SKILL.md"
_CAPTURE = SKILLS / "benchmark-enhancement-capture" / "SKILL.md"
_CORE = SKILLS / "core-agent-loop" / "SKILL.md"
_FIELD = SKILLS / "field-agent-loop" / "SKILL.md"

# The three literal phrases the issue's grep acceptance requires.
_DOCTRINE_PHRASES = (
    "fix-all-into-the-plugin",
    "promote it to a deterministic program",
    "fresh clean-room re-run on the newest plugin produces 0 residual",
)


def _read(p: Path) -> str:
    assert p.is_file(), f"missing skill: {p}"
    return p.read_text(errors="replace")


def _norm(text: str) -> str:
    """Collapse whitespace so a doctrine phrase matches regardless of prose
    line-wrapping (markdown wraps the same sentence across lines)."""
    return re.sub(r"\s+", " ", text)


def test_doctrine_present_in_both_user_facing_skills():
    for skill in (_BACKLOG, _CAPTURE):
        text = _norm(_read(skill))
        for phrase in _DOCTRINE_PHRASES:
            assert phrase in text, f"{skill.name} missing doctrine phrase: {phrase!r}"


def test_convergence_test_is_two_consecutive_rounds():
    # convergence is not a single zero-backlog round.
    assert "two consecutive zero-backlog clean-room rounds" in _norm(_read(_CAPTURE))
    assert "two consecutive zero-backlog clean-room rounds" in _norm(_read(_BACKLOG))


def test_bucketD_forbids_variance_and_designside_discards():
    cap = _norm(_read(_CAPTURE))
    # the tightened Bucket-D / honesty rule must name these as NON-reasons.
    for non_reason in ("clean-room variance", "design-side", "not a plugin gap"):
        assert non_reason in cap, f"Bucket-D tightening missing mention of {non_reason!r}"
    # and explicitly state they are NOT valid discard reasons.
    assert "NOT" in cap and "discard" in cap.lower()


def test_loop_stop_conditions_cross_reference_convergence():
    for loop in (_CORE, _FIELD):
        text = _norm(_read(loop))
        assert "fresh clean-room re-run on the newest plugin produces 0 residual" in text, \
            f"{loop.name} STOP CONDITION does not cross-reference the clean-room convergence test"
