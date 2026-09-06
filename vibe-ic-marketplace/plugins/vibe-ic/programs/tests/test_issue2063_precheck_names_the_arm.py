"""RB2-08 (#2063) — `tapeout_precheck` FAILed with six lines rendered as

    ?: the arm reported NOT_DETERMINED with no evidence line

MEASURED on the subservient cell (lane rbsub2, 8HD-8, 2026-09-06). Two separate
omissions produced that line: the finding carried no `rule` key, which is the
field every generic report reader in this repo renders (`f.get('rule','?')`),
and the fallback message said "the arm" about a report that knows which arm it
read.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import tapeout_precheck as T  # noqa: E402


def _doc(steps):
    return {"steps": steps}


def test_finding_carries_a_rule_key_that_names_the_step():
    fs = T._findings_from_arm(
        _doc([{"step_id": "drc.density", "verdict": "NOT_DETERMINED"}]),
        authority="sh1/precheck", is_ours=False)
    assert len(fs) == 1
    d = fs[0].as_dict()
    assert d["rule"] == "UNDETERMINED/drc.density"
    assert "?" not in d["rule"]


def test_a_step_without_an_id_names_the_AUTHORITY_instead_of_a_question_mark():
    fs = T._findings_from_arm(
        _doc([{"verdict": "NOT_DETERMINED"}]),
        authority="sh1/precheck", is_ours=False)
    d = fs[0].as_dict()
    assert d["rule"] == "UNDETERMINED/sh1/precheck"
    assert "sh1/precheck" in d["message"]
    assert "the arm reported" not in d["message"]
    # and it says, rather than hides, that the arm's own report had no step id
    assert "names no step_id" in d["message"]


def test_the_arms_own_evidence_is_still_carried_verbatim():
    """The gate's rule that nothing here re-judges or paraphrases an arm."""
    fs = T._findings_from_arm(
        _doc([{"step_id": "s1", "verdict": "FAIL",
               "evidence": "min width violated at (1,2)"}]),
        authority="sh1/precheck", is_ours=False)
    assert fs[0].message == "min width violated at (1,2)"
    assert fs[0].as_dict()["rule"] == "REFUSAL/s1"


def test_a_passing_step_produces_no_finding():
    assert T._findings_from_arm(
        _doc([{"step_id": "s1", "verdict": T.PASS}]),
        authority="a/b", is_ours=True) == []
