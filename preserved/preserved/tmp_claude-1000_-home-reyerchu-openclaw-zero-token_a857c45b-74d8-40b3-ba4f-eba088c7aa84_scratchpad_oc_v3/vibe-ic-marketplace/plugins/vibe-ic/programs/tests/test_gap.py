"""The two assertions the PR's own control is missing (independent verifier).

Both are RESTRAINT/OVER-CORRECTION probes driven through the public surface.
Drop them into test_current_round_is_machine_readable.py.
"""
import json
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import run_output_completeness_check as R  # noqa: E402

AMBIG = "DELIVERABLE_CURRENT_ROUND_AMBIGUOUS"
_FILLER = (
    "Shape B - runner with --skip-phase3, entry point vibe_ic_one_shot_runner.\n"
    "Tool substitution: commercial simulator -> iverilog; commercial synthesis\n"
    "-> yosys + OpenROAD. Residual triage: every remaining fail is category C.\n"
    "Reproduce: re-run the scorer against the same design directory with every\n"
    "installed check enabled, then re-read this deliverable.\n"
)


def _run(tmp_path, body, name="run"):
    d = tmp_path / name
    (d / "reports" / "orchestrator").mkdir(parents=True, exist_ok=True)
    (d / "out").mkdir(parents=True, exist_ok=True)
    (d / "RESULT.md").write_text(body + "\n" + _FILLER)
    (d / "reports" / "orchestrator" / "vibe_ic_one_shot.json").write_text(
        json.dumps({"verdict": "FAIL"}))
    (d / "out" / "design.def").write_text("VERSION 5.8 ;\nEND DESIGN\n")
    return d


def test_lowercase_prose_cannot_silence_the_guard(tmp_path):
    """GAP #1. The source says ALL-CAPS is a deliberate machine marker and
    lowercase is prose, but nothing in the suite pins it: the existing
    `test_an_adjective_in_prose_is_not_a_marker` writes CURRENT in caps, so it
    is held up by the DELIMITER rule, not by the caps rule. Dropping caps —
    adding `re.IGNORECASE` to both status vocabularies — passes all 46 tests
    while turning this genuinely ambiguous document into rc 0.

    Both status words here are lowercase PROSE and both are delimited (one
    after `(`, one after an em dash), so the delimiter rule alone does not
    save it. Nothing in the file declares anything; it must still be refused.
    """
    body = """# RESULT

Verdict: FAIL

Round A (baseline figure carried over from the vendor kit): PASS=26 FAIL=2 MISSING=1
Round B — current thinking, still unconfirmed: PASS=19 FAIL=9 MISSING=1
"""
    rep = R.check(_run(tmp_path, body))
    assert rep.state == AMBIG and rep.rc == 1
    assert all(d["status"] == "UNMARKED"
               for d in rep.evidence["round_tally_distinct"])


@pytest.mark.xfail(reason="KNOWN over-reach: the rule cannot tell two rounds "
                          "apart from two SCOPES of one round, and the "
                          "vocabulary has no truthful word for the second",
                   strict=True)
def test_a_per_scope_breakdown_of_one_round_is_not_two_rounds(tmp_path):
    """GAP #2. Two tallies here are two SCOPES of a single live round. Neither
    is withdrawn and neither is a baseline, so the only forms this gate accepts
    require the author to write something false. Marking BOTH current is
    refused as CURRENT_ROUND_MULTIPLY_DECLARED, so there is no truthful escape.
    Pinned xfail(strict) so the day the rule learns the difference, this fails
    loudly and gets promoted."""
    body = """# RESULT

Verdict: FAIL

Phase 2 gate set: PASS=12 FAIL=0 MISSING=0
Phase 3 gate set: PASS=20 FAIL=1 MISSING=2
"""
    rep = R.check(_run(tmp_path, body))
    assert rep.state == "COMPLETE" and rep.rc == 0
