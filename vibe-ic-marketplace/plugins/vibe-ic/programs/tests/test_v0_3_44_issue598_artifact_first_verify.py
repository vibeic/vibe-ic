"""ORGANIC #598 — field-agent-loop must codify ARTIFACT-FIRST
verification: audit a closed checker/classifier/verdict-message fix
against the PERSISTED phase3 artifacts (seconds), never re-run a full
~40-minute phase3 unless the fix changed the route/geometry itself.

A whole verify campaign re-ran a full phase3 for checker/message-only
fixes (DRC off-grid classifier, LVS cross-ref string, pin-count
disclosure, cache-decision line) where feeding the prior run's artifacts
to the new program would have sufficed in seconds.

This pins the doctrine into field-agent-loop SKILL.md so it is enforced,
not session memory.
"""
import re
from pathlib import Path

SKILL = (Path(__file__).resolve().parents[2] / "skills"
         / "field-agent-loop" / "SKILL.md")


def _text() -> str:
    return SKILL.read_text(errors="replace")


def test_skill_has_artifact_first_section():
    t = _text()
    assert "ARTIFACT-FIRST" in t
    assert "Verify discipline" in t


def test_skill_classifies_consumer_vs_producer():
    t = _text()
    assert "consumer-only" in t
    assert "producer" in t
    # consumer-only must drive new program against persisted artifacts
    assert re.search(r"persisted artifacts", t, re.IGNORECASE)
    assert "lvs_verdict.json" in t


def test_skill_forbids_rerun_for_consumer_fix():
    """The doctrine must say a checker/message fix takes SECONDS via the
    persisted artifacts and must NOT re-run the ~40-min phase3."""
    t = _text()
    assert "~40" in t or "40-minute" in t or "40 min" in t
    assert "SECONDS" in t or "seconds" in t
    # the read-only "check status" rule
    assert "check status" in t.lower()
    assert "READ-ONLY" in t or "read-only" in t.lower()


def test_skill_producer_fix_still_allows_rerun():
    """A producer (route/geometry) fix still justifies a full re-run —
    the discipline narrows WHEN, it doesn't forbid re-runs."""
    t = _text()
    assert "producer fix only" in t or "producer → a full phase3 re-run" in t
    # examples naming the producer class (route/geometry/streamout)
    assert ("streamout" in t and "floorplan" in t)


def test_skill_doctrine_is_in_step4_audit():
    """The discipline lands in Step 4 (audit), before the audit
    execution block."""
    t = _text()
    s4 = t.index("### Step 4")
    disc = t.index("Verify discipline")
    execu = t.index("Audit execution")
    assert s4 < disc < execu
