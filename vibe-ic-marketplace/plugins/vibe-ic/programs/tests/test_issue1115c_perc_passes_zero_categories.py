""""All AUTOMATED PERC categories conclusive PASS" over ZERO of them. vibe-ic#1115.

Found by `liar_census.py --probes empty_output`. With
`reports/phase3/perc_equivalent.json` PRESENT and empty, every branch of
`audit()` is empty by construction — no conclusive FAIL, no INCOMPLETE, no
MANUAL_REVIEW, no projection contradiction — and the tail landed on:

    "verdict": "PASS",
    "reason":  "all AUTOMATED PERC categories conclusive PASS",
    "automated_total": 0

with the gate's own report field proving the population was empty. That is
LibreLane 3.0.8's `klayout.py:486-490` shape — the producer emits nothing and
the checker reads the absence as consent — on the step-28 PERC sign-off gate.

rc 2, NOT rc 0, and NOT a new convention: this gate ALREADY answers rc 2 / SKIP
when `perc_equivalent.json` is ABSENT. A file that is present and carries zero
categories is the same epistemic state — nothing to judge — so it gets the same
answer, and a project with no PERC run was already rc 2 by that branch. This
reddens nothing that was green.

THE SECOND HALF: the projection disclosures were COMPUTED AND DROPPED. "cannot
be compared with perc_equivalent.json's None" lived in the report dict and never
reached the verdict line a reader sees. It is not a detail — it is the reason
the corroboration this gate exists for did not happen — so it now rides in the
`reason` on both the vacuous and the passing path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
GATE = PROGRAMS / "perc_signoff_check.py"

sys.path.insert(0, str(PROGRAMS))
from flow_compliance_check import _stdout_signals_vacuous  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

def _run(project: Path):
    p = _pr.run([sys.executable, str(GATE), str(project)],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def _phase3(tmp_path: Path) -> Path:
    d = tmp_path / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _populated(d: Path, result: str = "PASS") -> None:
    d.joinpath("perc_equivalent.json").write_text(json.dumps({
        "verdict": result,
        "categories": [
            {"category": "ESD", "status": "AUTOMATED", "result": result},
            {"category": "LATCHUP", "status": "AUTOMATED", "result": "PASS"},
        ]}))
    for f in ("perc_equivalent.rpt", "PERC_SIGNOFF_MEMO.md"):
        d.joinpath(f).write_text(f"**Overall verdict:** `{result}`\nESD\nLATCHUP\n")


# --------------------------------------------------------------------------
# the defect
# --------------------------------------------------------------------------
def test_zero_automated_categories_is_not_all_of_them_passing(tmp_path):
    d = _phase3(tmp_path)
    d.joinpath("perc_equivalent.json").write_text("{}")
    for f in ("perc_equivalent.rpt", "PERC_SIGNOFF_MEMO.md"):
        d.joinpath(f).write_text("")
    rc, out = _run(tmp_path)
    assert rc == 2, (
        "a PERC sign-off gate certified a design over ZERO automated "
        f"categories, at rc 0:\n{out}")
    assert '"automated_total": 0' in out, out
    rep = json.loads(out[out.index("{"):out.rindex("}") + 1])
    # The AFFIRMATIVE sentence, exactly as the gate used to emit it. Checking
    # for the bare substring "conclusive PASS" was wrong in the other
    # direction: the new reason QUOTES the phrase inside its own negation
    # ("... so this is NOT 'all categories conclusive PASS'"), so that
    # assertion failed on correct output. This one names the claim itself.
    assert "all AUTOMATED PERC categories conclusive PASS" not in rep["reason"], (
        f"the reason still makes the claim:\n{rep['reason']}")
    assert rep["verdict"] == "VACUOUS_PASS", rep
    assert "nothing to judge" in rep["reason"], rep["reason"]


def test_the_refusal_reaches_the_consumer(tmp_path):
    """rc 2 alone is read by `flow_compliance_check`; the stdout channel is the
    one a reader and a passing-path consumer see."""
    d = _phase3(tmp_path)
    d.joinpath("perc_equivalent.json").write_text("{}")
    _, out = _run(tmp_path)
    assert _stdout_signals_vacuous(out), out
    assert "0 AUTOMATED PERC categor" in out, out


def test_the_projection_disclosures_are_no_longer_dropped(tmp_path):
    """They were computed, stored in the report, and never surfaced in the
    sentence that decides how a reader feels about this gate."""
    d = _phase3(tmp_path)
    d.joinpath("perc_equivalent.json").write_text("{}")
    for f in ("perc_equivalent.rpt", "PERC_SIGNOFF_MEMO.md"):
        d.joinpath(f).write_text("")
    _, out = _run(tmp_path)
    rep = json.loads(out[out.index("{"):out.rindex("}") + 1])
    assert "cannot be compared" in rep["reason"], (
        f"the disclosure is still only in the report dict:\n{rep['reason']}")


# --------------------------------------------------------------------------
# false-positive controls — a real run must be untouched
# --------------------------------------------------------------------------
def test_a_populated_pass_is_still_PASS_at_rc_0(tmp_path):
    d = _phase3(tmp_path)
    _populated(d, "PASS")
    rc, out = _run(tmp_path)
    assert rc == 0, out
    rep = json.loads(out[out.index("{"):out.rindex("}") + 1])
    assert rep["verdict"] == "PASS", rep
    assert rep["automated_total"] == 2, rep
    assert not _stdout_signals_vacuous(out), (
        f"a populated run was demoted to VACUOUS_PASS:\n{out}")


def test_the_passing_reason_now_states_its_denominator(tmp_path):
    """"all N categories" beats "all categories" for exactly the reason this
    issue exists: a reader cannot tell 2 from 0 in the second form."""
    d = _phase3(tmp_path)
    _populated(d, "PASS")
    _, out = _run(tmp_path)
    rep = json.loads(out[out.index("{"):out.rindex("}") + 1])
    assert "all 2 AUTOMATED PERC categor" in rep["reason"], rep["reason"]


# --------------------------------------------------------------------------
# PAIRED GUARD — the gate must still fail on a real reliability defect
# --------------------------------------------------------------------------
def test_a_conclusive_automated_FAIL_still_exits_1(tmp_path):
    """If this went green the gate would be a disclosure with no teeth."""
    d = _phase3(tmp_path)
    _populated(d, "FAIL")
    rc, out = _run(tmp_path)
    assert rc == 1, (
        f"a conclusive PERC reliability defect was not blocked:\n{out}")
    assert not _stdout_signals_vacuous(out), out


def test_an_absent_report_still_SKIPs_at_rc_2(tmp_path):
    """The branch this repair borrows its convention from must be unchanged."""
    _phase3(tmp_path)
    rc, out = _run(tmp_path)
    assert rc == 2, out
    assert '"verdict": "SKIP"' in out, out
