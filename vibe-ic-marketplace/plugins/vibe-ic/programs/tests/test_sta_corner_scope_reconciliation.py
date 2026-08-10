"""A one-axis sweep may not be rendered as an all-axis sign-off. vibe-ic#913.

`post_route_signoff_corner_check` reads `sta_spef_multicorner.rpt`, whose
corners are RC/parasitic corners. The run's other declared sign-off axis — the
process axis, in `per_corner/sta_<CORNER>.rpt` and the OCV report — is not in
that file, so a violation living only there is invisible to this gate BY
CONSTRUCTION.

MEASURED, the run that filed the issue: this gate said

    PASS — all analyzed sign-off corners MET (governing worst-slack +0.070 ns)

with `setup_worst_slack_ns 6.77`, while `per_corner/sta_SS.rpt` in the SAME run
directory carried setup `-2.850 ns` and the sibling gate reported FAIL on it.
Two gates, opposite verdicts, one design.

WHAT THESE TESTS ASK THE PROGRAM
--------------------------------
Every assertion below reads the program's OWN output — the exit code from
`main()`, the JSON `main()` wrote, and the banner it printed. None of them
recomputes the rule locally: a test that re-derives the verdict passes against
the unfixed program because it never asks the program anything.

TWO ARMS, AND WHICH TEST IS IN WHICH
------------------------------------
ARM 1 (7 tests, none named `guard_`) FAIL against the pre-fix program, which
returns an unqualified PASS with rc 0 on every fixture below. Verified against
`git checkout origin/main -- post_route_signoff_corner_check.py`, md5 matched
on both sides: 7 failed / 6 passed there, 13 passed here.

ARM 2 (the 6 `test_guard_*`) pass against BOTH programs — 6 passed, 7
deselected under `-k guard` on the pre-fix program. They pin what this
disclosure may NOT be bought with: an RC-axis violation must still FAIL, a run
with no other axis must still PASS unqualified, an absent report must still be
NOT_APPLICABLE, the pure text evaluator must keep its contract for callers
holding no project directory, the measured slacks must survive the verdict
change unrelabelled, and a pre-layout miss must never become this gate's FAIL.
A future fix that satisfies arm 1 by breaking any of these has traded one wrong
answer for another.

A test that pins a symbol the fix introduces cannot pass against the pre-fix
program and is therefore in arm 1, however guard-like its purpose — so
`test_swept_axis_is_the_siblings_constant_not_a_copy` is filed there, not
mislabelled as a guard.

§4.05 no-leak: fixtures are synthetic, carry generic process-corner labels
(SS/TT/FF, the vocabulary the sibling gate already classifies) and name no
design, PDK, foundry or process. The gate reads only artefacts the run already
emits.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import post_route_signoff_corner_check as G  # noqa: E402
import sta_corner_record_completeness_check as REC  # noqa: E402

# An RC-axis sweep with every corner MET — the shape that produced the PASS.
_RC_CLEAN = """# Multi-corner SPEF STA (TAPEOUT-SIGNOFF P1)
# STA_BASIS: POST_ROUTE_SPEF
# SETUP corner: max-RC   HOLD corner: min-RC
# corners_available: max,min,nom
=== SETUP (max-RC corner, SPEF=max) ===
worst slack max 6.77
tns max 0.00
=== HOLD (min-RC corner, SPEF=min) ===
worst slack min 0.07
tns max 0.00
"""

# The same sweep with its own axis violated — this gate already FAILed here.
_RC_VIOLATED = _RC_CLEAN.replace("worst slack max 6.77", "worst slack max -1.71")


def _per_corner(setup_ns: float, corner: str, basis: str = "POST_ROUTE_SPEF"
                ) -> str:
    return (f"# STA_BASIS: {basis}\n"
            f"=== SETUP corner: process={corner} liberty=lib_{corner}.lib, "
            f"SPEF=max ===\n"
            f"worst slack max {setup_ns}\n"
            f"tns max 0.00\n")


def _project(tmp_path: Path, multicorner: str,
             process: dict | None = None,
             basis: str = "POST_ROUTE_SPEF") -> Path:
    """A run directory: one RC-axis report, optionally a process-axis sweep."""
    sta = tmp_path / "phase3" / "stage3" / "sta"
    sta.mkdir(parents=True, exist_ok=True)
    (sta / "sta_spef_multicorner.rpt").write_text(multicorner)
    for corner, setup_ns in (process or {}).items():
        pc = sta / "per_corner"
        pc.mkdir(exist_ok=True)
        (pc / f"sta_{corner}.rpt").write_text(
            _per_corner(setup_ns, corner, basis))
    return tmp_path


def _run(project: Path, tmp_path: Path):
    """Invoke the program the way the flow does; return (rc, verdict_json)."""
    out = tmp_path / "verdict.json"
    rc = G.main([str(project), "--json", str(out)])
    return rc, json.loads(out.read_text())


# ---------------------------------------------------------------------------
# ARM 1 — these FAIL against the unfixed program.
# ---------------------------------------------------------------------------

def test_violation_on_an_unswept_axis_is_not_rendered_as_pass(tmp_path):
    """The reported run: RC axis clean, process axis violated, on one disk."""
    proj = _project(tmp_path / "p", _RC_CLEAN,
                    {"SS": -2.850, "TT": 1.20, "FF": 3.40})
    rc, doc = _run(proj, tmp_path)
    assert doc["verdict"] == "FAIL", (
        "a sign-off corner violated in this very run must not be signed off as "
        "MET by a gate that did not read it; got: " + json.dumps(doc)[:400])
    assert rc == 1, f"a FAIL verdict must exit 1, got {rc}"


def test_the_failing_corner_its_slack_and_its_artifact_are_named(tmp_path):
    """A finding a reader cannot follow to a file is not checkable."""
    proj = _project(tmp_path / "p", _RC_CLEAN, {"SS": -2.850, "FF": 3.40})
    _rc, doc = _run(proj, tmp_path)
    reason = "; ".join(str(r) for r in doc["reasons"])
    assert "SS" in reason and "-2.850" in reason, reason
    assert "per_corner/sta_SS.rpt" in reason, (
        "the artefact that carries the violation must be cited: " + reason)
    assert REC.AXIS_PROCESS in reason, (
        "the axis the violation lives on must be named: " + reason)


def test_a_met_unswept_axis_still_bars_an_unqualified_pass(tmp_path):
    """Scope, not slack, is the finding: one axis is not the sign-off.

    Nothing is violated here, so the run stays green (rc 0) — but the verdict
    word may not be the bare "PASS" a downstream summary would quote as
    all-axis closure.
    """
    proj = _project(tmp_path / "p", _RC_CLEAN, {"SS": 4.56, "FF": 0.38})
    rc, doc = _run(proj, tmp_path)
    assert rc == 0, "nothing is violated, so this must not turn red"
    assert doc["verdict"] != "PASS", (
        "a verdict covering one of two axes present in the run must not be an "
        "unqualified PASS; got: " + json.dumps(doc)[:400])
    reason = "; ".join(str(r) for r in doc["reasons"])
    assert REC.AXIS_PROCESS in reason and G.SWEPT_AXIS in reason, (
        "both the axis analyzed and the axis excluded must be named: " + reason)


def test_the_limitation_reaches_the_printed_banner(tmp_path, capsys):
    """The banner is the part of the line a reader scans.

    A limitation recorded only in JSON is the #913 defect one field over.
    """
    proj = _project(tmp_path / "p", _RC_CLEAN, {"SS": 4.56})
    _rc, _doc = _run(proj, tmp_path)
    printed = capsys.readouterr().out.splitlines()[0]
    assert not printed.startswith("[PASS]"), (
        "a scope-limited result printed under a PASS banner has not been "
        "disclosed: " + printed)
    assert G.SINGLE_AXIS_ONLY in printed, printed


def test_unassessable_scope_is_not_reported_as_a_clean_one(tmp_path,
                                                           monkeypatch):
    """"I could not look" and "there is nothing there" are different facts."""
    monkeypatch.setattr(G, "_rec", None)
    proj = _project(tmp_path / "p", _RC_CLEAN, {"SS": 4.56})
    rc, doc = _run(proj, tmp_path)
    assert rc == 0
    assert doc["verdict"] != "PASS", (
        "with the other axes unreadable the gate must not assert a complete "
        "scope; got: " + json.dumps(doc)[:400])
    assert doc["scope_other_axis_evidence"]["assessed"] is False


def test_swept_axis_is_the_siblings_constant_not_a_copy(tmp_path):
    """One axis vocabulary, one owner.

    The #913 contradiction was two gates disagreeing about the same corners. A
    hand-typed second copy of the axis name here would let them disagree again
    the next time the sibling renames one. In arm 1, not arm 2: it pins a
    symbol the fix introduces, so it cannot pass against the pre-fix program.
    """
    assert G.SWEPT_AXIS == REC.AXIS_RC
    assert G.SWEPT_AXIS != REC.AXIS_PROCESS


def test_a_pre_layout_miss_is_still_surfaced(tmp_path):
    """A miss the gate declines to escalate must not vanish instead.

    The non-escalation half of this behaviour is pinned separately, in arm 2,
    where it holds against both programs.
    """
    proj = _project(tmp_path / "p", _RC_CLEAN, {"SS": -2.850},
                    basis="PRE_LAYOUT")
    _rc, doc = _run(proj, tmp_path)
    reason = "; ".join(str(r) for r in doc["reasons"])
    assert "PRE_LAYOUT" in reason and "-2.850" in reason, (
        "a pre-layout miss must still be surfaced, just not as a FAIL: "
        + reason)


# ---------------------------------------------------------------------------
# ARM 2 — paired guards. These pass against BOTH programs and pin what this
# disclosure may NOT be bought with. A future fix that satisfies arm 1 by
# breaking any of these has traded one wrong answer for another.
# ---------------------------------------------------------------------------

def test_guard_run_with_no_other_axis_still_passes_unqualified(tmp_path):
    """The fix must not turn every run into a caveat.

    With no evidence outside this gate's axis, the PASS is a complete statement
    about the run and stays exactly the word it was.
    """
    proj = _project(tmp_path / "p", _RC_CLEAN)
    rc, doc = _run(proj, tmp_path)
    assert doc["verdict"] == "PASS", json.dumps(doc)[:400]
    assert rc == 0


def test_guard_violation_on_this_gates_own_axis_still_fails(tmp_path):
    """The predicate this gate already enforced is not relaxed by the fix."""
    proj = _project(tmp_path / "p", _RC_VIOLATED)
    rc, doc = _run(proj, tmp_path)
    assert doc["verdict"] == "FAIL"
    assert rc == 1
    assert "max-RC" in "; ".join(str(r) for r in doc["reasons"])


def test_guard_absent_report_is_still_not_applicable(tmp_path):
    """A gate with nothing to read judges nothing — unchanged, and rc 0."""
    (tmp_path / "p").mkdir()
    rc, doc = _run(tmp_path / "p", tmp_path)
    assert doc["verdict"] == "NOT_APPLICABLE"
    assert rc == 0


def test_guard_pure_text_evaluator_keeps_its_contract(tmp_path):
    """`evaluate` holds no project directory and must stay a text function."""
    assert G.evaluate(_RC_CLEAN)["verdict"] == "PASS"
    assert G.evaluate(_RC_VIOLATED)["verdict"] == "FAIL"
    assert G.evaluate(_RC_CLEAN)["corners_available"] == "max,min,nom"
    assert "max,min,nom" in "; ".join(
        str(r) for r in G.evaluate(_RC_CLEAN)["reasons"])


def test_guard_measured_slacks_are_reported_unchanged(tmp_path):
    """Nothing is relabelled or suppressed: the numbers survive the verdict.

    A fix that made a finding disappear by rewriting the data would show up
    here, because the RC-axis figures this gate measured are asserted against
    the report body regardless of what the verdict became.
    """
    proj = _project(tmp_path / "p", _RC_CLEAN, {"SS": -2.850})
    _rc, doc = _run(proj, tmp_path)
    assert doc["setup_worst_slack_ns"] == 6.77
    assert doc["hold_worst_slack_ns"] == 0.07
    assert doc["corners_available"] == "max,min,nom"


def test_guard_a_pre_layout_miss_never_becomes_this_gates_fail(tmp_path):
    """A pre-layout estimate is not a sign-off measurement.

    Escalating one to FAIL would be this gate inventing a sign-off number — the
    mirror image of the defect being fixed. True on both programs, and it must
    stay true: it is the bound on how far the new FAIL arm may reach.
    """
    proj = _project(tmp_path / "p", _RC_CLEAN, {"SS": -2.850},
                    basis="PRE_LAYOUT")
    rc, doc = _run(proj, tmp_path)
    assert doc["verdict"] != "FAIL", json.dumps(doc)[:400]
    assert rc == 0
