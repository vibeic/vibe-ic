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
import achieved_period_recorded_check as APR  # noqa: E402

PLUGIN = Path(__file__).resolve().parents[2]
REPO = PLUGIN.parents[2]


def _mk(project: Path, *, slack_line: str = None, achieved: dict = None,
        rel: str = "reports/phase3/sta_spef_based.rpt"):
    if slack_line is not None:
        p = project / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("Startpoint: a\nEndpoint: b\n" + slack_line + "\n")
    if achieved is not None:
        a = project / APR.ACHIEVED_REL
        a.parent.mkdir(parents=True, exist_ok=True)
        a.write_text(json.dumps(achieved) + "\n")
    return project


_GOOD = {"spec_period_ns": 10.0, "achievable_period_ns": 4.76,
         "worst_setup_slack_ns": 5.24, "relaxation_applied": False}


# ---------------------------------------------------------------------------
# the implication the gate asserts
# ---------------------------------------------------------------------------
def test_a_measured_slack_with_no_record_is_a_finding(tmp_path):
    rep = APR.evaluate(_mk(tmp_path, slack_line="worst slack max 5.24"))
    assert rep["rc"] == APR.RC_FAIL, rep
    assert rep["setup_slack_ns"] == 5.24, rep
    assert any(f["rule"] == "ACHIEVED_PERIOD_NOT_RECORDED" for f in rep["findings"]), rep


def test_a_measured_slack_with_a_record_passes(tmp_path):
    rep = APR.evaluate(_mk(tmp_path, slack_line="worst slack max 5.24",
                           achieved=_GOOD))
    assert rep["rc"] == APR.RC_PASS, rep
    assert rep["asked_period_ns"] == 10.0 and rep["reached_period_ns"] == 4.76


def test_no_slack_is_vacuous_not_red(tmp_path):
    """The half that keeps this a check rather than a nag: a run with no STA
    has nothing to record an achieved period AGAINST."""
    rep = APR.evaluate(tmp_path)
    assert rep["rc"] == APR.RC_VACUOUS, rep
    assert rep["findings"] == [], rep


def test_an_unreadable_record_is_not_silently_accepted(tmp_path):
    p = _mk(tmp_path, slack_line="worst slack max 5.24")
    (p / APR.ACHIEVED_REL).write_text("{not json")
    rep = APR.evaluate(p)
    assert rep["rc"] == APR.RC_FAIL, rep
    assert any(f["rule"] == "ACHIEVED_PERIOD_UNREADABLE" for f in rep["findings"])


def test_a_record_missing_either_half_answers_neither(tmp_path):
    partial = dict(_GOOD)
    del partial["achievable_period_ns"]
    rep = APR.evaluate(_mk(tmp_path, slack_line="worst slack max 5.24",
                           achieved=partial))
    assert rep["rc"] == APR.RC_FAIL, rep
    assert any(f["rule"] == "ACHIEVED_PERIOD_INCOMPLETE" for f in rep["findings"])


def test_the_artefact_may_never_become_a_relaxation(tmp_path):
    """#1083 records ORFS's `update_ok`/`--failing` as explicitly NOT adopted —
    a golden that moves itself to the current run's worse value. Asserted here
    rather than trusted, so an edit that turned this into one goes red."""
    relaxed = dict(_GOOD, relaxation_applied=True)
    rep = APR.evaluate(_mk(tmp_path, slack_line="worst slack max 5.24",
                           achieved=relaxed))
    assert rep["rc"] == APR.RC_FAIL, rep
    assert any(f["rule"] == "ACHIEVED_PERIOD_IS_NOT_A_RELAXATION"
               for f in rep["findings"]), rep


# ---------------------------------------------------------------------------
# the domain trap
# ---------------------------------------------------------------------------
def test_wns_is_not_read_as_the_worst_slack(tmp_path):
    """Both headings in one report, exactly as the published spm cell ships
    them. `wns` is clamped at 0 and would report zero headroom on a design that
    has 5.24 ns of it."""
    p = tmp_path
    r = p / "reports/phase3/sta_spef_based.rpt"
    r.parent.mkdir(parents=True, exist_ok=True)
    r.write_text("wns max 0.00\nworst slack max 5.24\n")
    slack, _src = APR.measured_setup_slack(p)
    assert slack == 5.24, (
        f"read {slack} — `wns max 0.00` was taken for the worst slack. That "
        f"makes achieved == asked on every passing design: a FALSE measurement, "
        f"which is worse than the missing one this gate removes.")


def test_a_negative_wns_alone_is_still_usable(tmp_path):
    """The fallback's one legitimate case: when the design violates, WNS and
    worst slack coincide, so a report carrying only WNS is still readable."""
    p = tmp_path
    r = p / "reports/phase3/sta_spef_based.rpt"
    r.parent.mkdir(parents=True, exist_ok=True)
    r.write_text("wns max -2.64\n")
    slack, _src = APR.measured_setup_slack(p)
    assert slack == -2.64, slack


def test_a_clamped_zero_wns_alone_is_refused(tmp_path):
    """...and its illegitimate one: a lone `wns max 0.00` says only 'nothing
    violates'. Treating it as a measurement would manufacture achieved==asked,
    so the gate reports VACUOUS instead of inventing a number."""
    p = tmp_path
    r = p / "reports/phase3/sta_spef_based.rpt"
    r.parent.mkdir(parents=True, exist_ok=True)
    r.write_text("wns max 0.00\n")
    slack, _src = APR.measured_setup_slack(p)
    assert slack is None, f"a clamped WNS was accepted as a measurement: {slack}"


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
def test_the_published_corpus_still_shows_the_gap_this_repairs():
    """The evidence, re-derived rather than quoted.

    These roots were published BEFORE the runner emitted on a pass, so they
    carry a real measured slack and no achieved period. If this ever comes back
    empty the cells have been republished and the numbers in the docstrings
    above need re-measuring — which is the point of asserting it.
    """
    roots = sorted((REPO / "benchmark-data" / "ic").glob("*/*"))
    if not roots:
        pytest.skip("no published corpus in this checkout")
    with_slack = []
    for r in roots:
        slack, _src = APR.measured_setup_slack(r)
        if slack is not None:
            with_slack.append((r.name, slack, (r / APR.ACHIEVED_REL).is_file()))
    if not with_slack:
        pytest.skip("no published root carries a post-route setup slack")
    unrecorded = [t for t in with_slack if not t[2]]
    assert unrecorded, (
        "every published root with a measured slack now records an achieved "
        "period — good, and it means the corpus was republished; re-measure "
        "the counts quoted in this module and in the gate's docstring")
