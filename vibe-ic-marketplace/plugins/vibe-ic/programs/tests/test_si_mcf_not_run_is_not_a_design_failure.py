#!/usr/bin/env python3
"""One artefact, one answer: "could not run" is not "ran and found a violation".

THE DEFECT (#506), on origin/main at v1.7.73. `si_mcf_sta_check` emitted, for
the SAME run, ``"verdict": "FAIL"`` beside ``"vacuous": true`` and a
``not_applicable_reason`` ending *"Read this as NOT CHECKED."* A reader keying
on `verdict` learned the design failed SI sign-off; a reader keying on
`vacuous` learned nothing had been checked. Both statements shipped in one JSON
and they disagree.

The cause was the precedence in `build_report`: any ERROR-severity finding
outranked vacuity, and the gate had three verdict tokens for four states. The
fourth — THE GATE COULD NOT OBTAIN ITS INPUT — had nowhere to go, so it
rendered as the design carrying a crosstalk violation. On a published tracked
report whose `spef` field is an absolute path from the authoring machine, that
means the verdict is a function of WHICH HOST reads the file.

THE TWO GROUPS OF ERROR ARE NOT ONE KIND OF THING.

    NO_REPORT  BAD_JSON  NO_SPEF  NO_CORNER  NO_BOUNDED_SPEF
        -> the gate never got to look                          (NOT_RUN)
    SPEF_NO_NET_RECORDS  COUPLING_LOST_SINCE_EMIT
    FOLD_WITHOUT_SOURCE  FOLD_NOT_APPLIED  SLACK_BETTER_THAN_BOUND
        -> the gate looked at a real artefact and it was wrong  (FAIL)

WHAT THIS FILE PINS, IN ORDER OF LOAD.

  1. THE LOUD HALF MUST NOT GET QUIETER. Every category in the second group
     keeps rc 1 AND verdict "FAIL", pinned one test per category plus a table
     sweep, so a future relaxation of the split cannot silently demote a real
     crosstalk finding into the skip tier. This is the half that guards the
     rule the gate was written for.
  2. THE FOURTH STATE EXISTS. Every category in the first group keeps rc 1 —
     the resolution deliberately does NOT change any exit code — and moves to
     the distinct verdict token "NOT_RUN", so the artefact stops claiming a
     design defect it never measured.
  3. VERDICT AND VACUOUS NEVER CONTRADICT, checked as an invariant over the
     whole category table rather than restated per case: a FAIL is never
     `vacuous`, never carries the NOT-CHECKED disclaimer, and a NOT_RUN /
     VACUOUS_PASS always carries both.
  4. THE UMBRELLA'S BUCKET IS DRIVEN, NOT REASONED ABOUT. `_evaluate_gate` is
     handed the REAL step-27 sub-gate spec read out of the shipped flow YAML,
     so the assertion cannot drift from what the flow actually wires.

WHY rc 1 AND NOT rc 2 FOR THE NOT-RUN TIER — the road not taken, pinned so it
stays a decision. rc 2 is the disclosed-skip tier and
`flow_compliance_check._check_program_exit_zero` credits it as a PASS
unconditionally. `NO_BOUNDED_SPEF` fires when the emitter's own report names a
bounded SPEF that is not there: a sign-off whose artefacts are incomplete. Under
rc 2 that step would render as a vacuous pass and the incomplete sign-off would
look skipped rather than broken. `test_the_not_run_tier_is_not_credited_as_a_
skip_by_the_flow` drives exactly that state through the umbrella.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "si_mcf_sta_check.py"
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import si_mcf_sta as M            # noqa: E402
import si_mcf_sta_check as G      # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_HEAD = """*SPEF "ieee 1481-1999"
*DESIGN "t"
*VERSION "1.0"
*DIVIDER /
*DELIMITER :
*BUS_DELIMITER []
*T_UNIT 1 NS
*C_UNIT 1 PF
*R_UNIT 1 OHM
*L_UNIT 1 HENRY

*NAME_MAP
*1 n1
*2 n2

"""

# The two fixtures differ by exactly this 4-token (2-node) *CAP line.
_COUPLING_LINE = "3 ub:A ua:B 0.1\n"
# Same line, same nodes, VALUE ZERO. Every re-derived expectation is then 0.0,
# so the fold axis proves nothing (`examined == 0`) while rule 3 — the bounded
# SPEF must retain no 2-node cap — is untouched and can still FAIL. That is how
# a DROPPED FOLD and a ZERO DENOMINATOR occur in the same run.
_ZERO_VALUE_COUPLING_LINE = "3 ub:A ua:B 0.0\n"

_BODY = """*D_NET *1 0.3
*CONN
*I ua:Z O *D BUF
*I ua:B I *D DFF
*CAP
1 ua:Z 0.1
2 ua:B 0.1
{coupling}*RES
1 ua:Z ua:B 10
*END

*D_NET *2 0.2
*CONN
*I ub:Z O *D BUF
*I ub:A I *D DFF
*CAP
1 ub:Z 0.1
2 ub:A 0.1
*RES
1 ub:Z ub:A 10
*END
"""

_SPEF_COUPLED = _HEAD + _BODY.format(coupling=_COUPLING_LINE)
_SPEF_GROUNDED_ONLY = _HEAD + _BODY.format(coupling="")
_SPEF_ZERO_VALUE_COUPLING = _HEAD + _BODY.format(
    coupling=_ZERO_VALUE_COUPLING_LINE)

_NOT_CHECKED = "Read this as NOT CHECKED"


# ---------------------------------------------------------------------------
# fixtures — bounded SPEFs come from the REAL emitter, never hand-written
# ---------------------------------------------------------------------------
def _bounded_from_emitter(spef_text: str):
    pairs = M.coupling_pairs(spef_text)
    setup_fold = {k: v * 2 for k, v in M.floor_folded_caps(pairs,
                                                           "setup").items()}
    hold_fold = M.floor_folded_caps(pairs, "hold")
    s, _ = M.rewrite_spef_folded(spef_text, setup_fold, "setup")
    h, _ = M.rewrite_spef_folded(spef_text, hold_fold, "hold")
    return s, h


def _project(root: Path, *, spef_text: str = _SPEF_COUPLED,
             setup_bounded: str | None = None, hold_bounded: str | None = None,
             extra_report: dict | None = None,
             setup_after: float = 7.36, hold_after: float = 0.39) -> Path:
    """A complete, PASSing project, then mutated by the callers below."""
    proj = root
    (proj / "reports" / "phase3").mkdir(parents=True, exist_ok=True)
    gs, gh = _bounded_from_emitter(spef_text)
    spef = proj / "design.spef"
    spef.write_text(spef_text)
    sb = proj / "design.mcf_setup.spef"
    sb.write_text(setup_bounded if setup_bounded is not None else gs)
    hb = proj / "design.mcf_hold.spef"
    hb.write_text(hold_bounded if hold_bounded is not None else gh)
    report = {
        "program": "si_mcf_sta", "spef": str(spef),
        "overlap_guard_ns": 0.0,
        "nominal": {"worst_setup_slack_ns": 7.37, "worst_hold_slack_ns": 0.39},
        "corners": {
            "setup": {"bounded_spef": str(sb),
                      "worst_slack_before_ns": 7.37,
                      "worst_slack_after_ns": setup_after},
            "hold": {"bounded_spef": str(hb),
                     "worst_slack_before_ns": 0.39,
                     "worst_slack_after_ns": hold_after},
        },
    }
    report.update(extra_report or {})
    (proj / "reports" / "phase3" / "si_mcf_sta.json").write_text(
        json.dumps(report))
    return proj


def _run(proj: Path):
    """Drive the real CLI. rc is read off the BARE invocation — never a pipe."""
    out = proj / "gate_out.json"
    r = _pr.run([sys.executable, str(_PROG), str(proj),
                        "--json", str(out)],
                       capture_output=True, text=True)
    return r, json.loads(out.read_text())


def _categories(doc):
    return [f["category"] for f in doc["findings"]]


def _reason(doc):
    return doc["summary"]["denominator"]["not_applicable_reason"]


# ===========================================================================
# THE CATEGORY TABLE — one builder per ERROR the gate can raise.
# Kept as data so the invariant sweeps below cover every category by
# construction instead of by a hand-maintained list of asserts.
# ===========================================================================
def _b_no_report(root: Path) -> Path:
    proj = _project(root)
    (proj / "reports" / "phase3" / "si_mcf_sta.json").unlink()
    return proj


def _b_bad_json(root: Path) -> Path:
    proj = _project(root)
    (proj / "reports" / "phase3" / "si_mcf_sta.json").write_text("{not json")
    return proj


def _b_no_spef(root: Path) -> Path:
    """THE REPRODUCER OF #506's HEADLINE: a published report naming a SPEF path
    that does not exist on the reading host."""
    proj = _project(root)
    (proj / "design.spef").unlink()
    return proj


def _b_no_corner(root: Path) -> Path:
    proj = _project(root)
    rp = proj / "reports" / "phase3" / "si_mcf_sta.json"
    doc = json.loads(rp.read_text())
    doc["corners"] = {}
    rp.write_text(json.dumps(doc))
    return proj


def _b_no_bounded_spef(root: Path) -> Path:
    proj = _project(root)
    (proj / "design.mcf_setup.spef").unlink()
    (proj / "design.mcf_hold.spef").unlink()
    return proj


def _b_spef_no_net_records(root: Path) -> Path:
    proj = _project(root)
    (proj / "design.spef").write_text(_HEAD)      # header only, no net record
    return proj


def _b_coupling_lost_since_emit(root: Path) -> Path:
    return _project(root, spef_text=_SPEF_GROUNDED_ONLY,
                    extra_report={"coupling_pairs": 7})


def _b_fold_without_source(root: Path) -> Path:
    gs, gh = _bounded_from_emitter(_SPEF_GROUNDED_ONLY)
    inflated = gs.replace("1 ua:Z 0.1", "1 ua:Z 0.9")
    assert inflated != gs, "fixture did not inflate anything"
    return _project(root, spef_text=_SPEF_GROUNDED_ONLY,
                    setup_bounded=inflated, hold_bounded=gh)


def _b_fold_not_applied(root: Path) -> Path:
    """The rule the gate was WRITTEN for: the bounded SPEF never folded."""
    _, gh = _bounded_from_emitter(_SPEF_COUPLED)
    dropped, _ = M.rewrite_spef_folded(_SPEF_COUPLED, {"*1": 0.0, "*2": 0.0},
                                       "setup")
    return _project(root, setup_bounded=dropped, hold_bounded=gh)


def _b_slack_better_than_bound(root: Path) -> Path:
    return _project(root, setup_after=7.50)       # 7.50 > 7.37 nominal


def _b_dropped_fold_at_a_zero_denominator(root: Path) -> Path:
    """FOLD_NOT_APPLIED **and** `examined == 0` in the same run.

    THE SHARPEST FORM OF #506, found by mutating `NOT_RUN_CATEGORIES` to
    swallow FOLD_NOT_APPLIED and watching the per-category pin stay green: the
    `_b_fold_not_applied` fixture proves folds on the setup corner, so it takes
    the partial-run branch and survives a mis-tiering. This one does not. The
    coupling caps are zero-VALUED, so every re-derived expectation is 0.0 and
    the fold axis proves nothing; the bounded SPEF is the ORIGINAL, so it still
    carries the 2-node caps and rule 3 fails on residual coupling regardless.

    Pre-fix this emitted `verdict FAIL`, `vacuous true` and "Read this as NOT
    CHECKED" together — the contradiction at its most expensive, because the
    run had caught a genuine dropped fold and told the reader nothing had been
    checked in the same breath."""
    return _project(root, spef_text=_SPEF_ZERO_VALUE_COUPLING,
                    setup_bounded=_SPEF_ZERO_VALUE_COUPLING,
                    hold_bounded=_SPEF_ZERO_VALUE_COUPLING)


#: category -> builder, for the categories that mean NOTHING WAS EXAMINED.
NOT_RUN_CASES = {
    "NO_REPORT": _b_no_report,
    "BAD_JSON": _b_bad_json,
    "NO_SPEF": _b_no_spef,
    "NO_CORNER": _b_no_corner,
    "NO_BOUNDED_SPEF": _b_no_bounded_spef,
}

#: category -> builder, for the categories that mean SOMETHING WAS EXAMINED
#: AND FOUND WRONG. Every one of these is a real verdict about a real
#: artefact and MUST keep failing exactly as loudly as it does today.
EXAMINED_AND_WRONG_CASES = {
    "SPEF_NO_NET_RECORDS": _b_spef_no_net_records,
    "COUPLING_LOST_SINCE_EMIT": _b_coupling_lost_since_emit,
    "FOLD_WITHOUT_SOURCE": _b_fold_without_source,
    "FOLD_NOT_APPLIED": _b_fold_not_applied,
    "SLACK_BETTER_THAN_BOUND": _b_slack_better_than_bound,
}

#: The same five categories, in the ZERO-DENOMINATOR shapes they are reachable
#: in. Kept separate because these are the ones a denominator-driven re-tiering
#: sweeps into the skip tier, and because `FOLD_NOT_APPLIED` needs a DIFFERENT
#: fixture to reach `examined == 0` than the one above.
EXAMINED_AND_WRONG_AT_ZERO_DENOMINATOR = {
    "SPEF_NO_NET_RECORDS": _b_spef_no_net_records,
    "COUPLING_LOST_SINCE_EMIT": _b_coupling_lost_since_emit,
    "FOLD_WITHOUT_SOURCE": _b_fold_without_source,
    "FOLD_NOT_APPLIED": _b_dropped_fold_at_a_zero_denominator,
}


# ===========================================================================
# (1) THE LOAD-BEARING HALF — nothing that examined something gets quieter
# ===========================================================================
def test_every_examined_and_wrong_category_keeps_rc_1_and_verdict_fail(
        tmp_path):
    """THE GUARD ON THE WHOLE CHANGE. Split the ERROR set the wrong way and
    one of these five silently becomes a skip the flow credits as a pass.
    Asserted per category, on the real CLI, reading rc off the bare call."""
    for cat, build in EXAMINED_AND_WRONG_CASES.items():
        proj = build(tmp_path / f"loud_{cat.lower()}")
        r, doc = _run(proj)
        assert cat in _categories(doc), (cat, doc["findings"])
        assert doc["verdict"] == "FAIL", (cat, doc["verdict"])
        assert r.returncode == G.RC_FAIL, (cat, r.returncode)
        assert doc["summary"]["pass"] is False, cat
        assert doc["summary"]["errors_count"] >= 1, cat


def test_a_dropped_fold_is_still_the_loudest_thing_this_gate_says(tmp_path):
    """FOLD_NOT_APPLIED singled out: it is the false-clean the gate exists to
    catch, and no re-tiering may touch it."""
    proj = _b_fold_not_applied(tmp_path / "dropped")
    r, doc = _run(proj)
    assert (r.returncode, doc["verdict"]) == (G.RC_FAIL, "FAIL")
    assert "FOLD_NOT_APPLIED" in _categories(doc)
    assert doc["summary"]["vacuous"] is False, doc["summary"]


def test_a_dishonest_slack_is_still_a_fail(tmp_path):
    proj = _b_slack_better_than_bound(tmp_path / "slack")
    r, doc = _run(proj)
    assert (r.returncode, doc["verdict"]) == (G.RC_FAIL, "FAIL")
    assert "SLACK_BETTER_THAN_BOUND" in _categories(doc)


def test_every_zero_denominator_defect_is_still_an_error_not_a_skip(tmp_path):
    """THE SHAPE A DENOMINATOR-DRIVEN RE-TIERING WOULD SWALLOW. All four of
    these fire with examined == 0 — a decided verdict about a real file, not an
    absent one — so `examined == 0` may never on its own mean "skip"."""
    for cat, build in EXAMINED_AND_WRONG_AT_ZERO_DENOMINATOR.items():
        proj = build(tmp_path / f"zero_{cat.lower()}")
        r, doc = _run(proj)
        assert cat in _categories(doc), (cat, doc["findings"])
        assert doc["summary"]["denominator"]["examined"] == 0, cat
        assert (r.returncode, doc["verdict"]) == (G.RC_FAIL, "FAIL"), cat
        assert doc["summary"]["vacuous"] is False, cat


def test_a_dropped_fold_that_proved_nothing_is_a_fail_not_a_not_run(tmp_path):
    """#506 AT ITS MOST EXPENSIVE, and the case that a per-category pin alone
    does NOT cover — found by mutating `NOT_RUN_CATEGORIES` to swallow
    FOLD_NOT_APPLIED and watching `test_a_dropped_fold_is_still_the_loudest...`
    stay green (that fixture proves setup folds, so it takes the partial-run
    branch). Here the coupling caps are zero-valued: the fold axis proves
    nothing, yet the bounded SPEF retains the 2-node caps and rule 3 fails.

    The gate has caught a genuine dropped fold on a run whose denominator is
    zero. Pre-fix it reported that as FAIL + vacuous + "Read this as NOT
    CHECKED" simultaneously; mis-tiered it would report a caught false-clean as
    "the gate could not run"."""
    proj = _b_dropped_fold_at_a_zero_denominator(tmp_path / "zero_dropped")
    r, doc = _run(proj)
    den = doc["summary"]["denominator"]
    assert "FOLD_NOT_APPLIED" in _categories(doc), doc["findings"]
    assert (den["examined"], den["considered"] > 0) == (0, True), den
    assert doc["verdict"] == "FAIL", doc["verdict"]
    assert r.returncode == G.RC_FAIL
    assert doc["summary"]["vacuous"] is False
    assert _NOT_CHECKED not in _reason(doc), _reason(doc)


def test_a_genuine_fold_still_signs_off(tmp_path):
    """CONTROL on the other arm: the clean run must not move either."""
    proj = _project(tmp_path / "clean")
    r, doc = _run(proj)
    assert (r.returncode, doc["verdict"]) == (G.RC_PASS, "PASS"), doc["findings"]
    assert doc["summary"]["pass"] is True
    assert doc["summary"]["vacuous"] is False
    assert doc["summary"]["denominator"]["examined"] > 0


def test_a_grounded_only_run_still_takes_the_disclosed_skip(tmp_path):
    """CONTROL on the third arm: the VACUOUS_PASS tier is untouched."""
    proj = _project(tmp_path / "grounded", spef_text=_SPEF_GROUNDED_ONLY)
    r, doc = _run(proj)
    assert (r.returncode, doc["verdict"]) == (G.RC_VACUOUS, "VACUOUS_PASS")
    assert doc["summary"]["vacuous"] is True
    assert _NOT_CHECKED in _reason(doc)


# ===========================================================================
# (2) THE FOURTH STATE — "could not obtain the input" has its own token
# ===========================================================================
def test_every_could_not_run_category_reports_not_run_at_the_same_rc(tmp_path):
    """THE FIX. The verdict token changes; the exit code deliberately does
    NOT, because rc 2 is the tier the flow credits as a pass (see the module
    docstring). A reader gets ONE answer and it is the true one."""
    for cat, build in NOT_RUN_CASES.items():
        proj = build(tmp_path / f"notrun_{cat.lower()}")
        r, doc = _run(proj)
        assert cat in _categories(doc), (cat, doc["findings"])
        assert doc["verdict"] == "NOT_RUN", (cat, doc["verdict"])
        assert r.returncode == G.RC_FAIL, (cat, r.returncode)
        assert doc["summary"]["pass"] is False, cat


def test_the_reproducer_from_the_issue_no_longer_says_two_things(tmp_path):
    """#506's headline artefact: a report whose `spef` field names a path that
    does not exist on the reading host. Pre-fix this emitted verdict FAIL
    beside vacuous true and "Read this as NOT CHECKED"."""
    proj = _b_no_spef(tmp_path / "issue506")
    r, doc = _run(proj)
    assert "NO_SPEF" in _categories(doc), doc["findings"]
    assert doc["verdict"] == "NOT_RUN", doc["verdict"]
    assert doc["summary"]["vacuous"] is True, doc["summary"]
    assert _NOT_CHECKED in _reason(doc), _reason(doc)
    assert r.returncode == G.RC_FAIL, r.returncode
    # ... and the one thing a reader must NOT be told:
    assert doc["verdict"] != "FAIL", (
        "a run that could not read its input reported the design as failing "
        "SI sign-off")


def test_the_not_run_tier_is_announced_on_stderr_without_the_vacuous_token(
        tmp_path):
    """A second, rc-independent channel — and it must NOT be the VACUOUS_PASS
    token, which `flow_compliance_check._stdout_signals_vacuous` matches at
    line start and would promote the step to the pass tier."""
    proj = _b_no_spef(tmp_path / "stderr")
    r, _ = _run(proj)
    assert any(ln.lstrip().startswith("NOT_RUN:")
               for ln in r.stderr.splitlines()), r.stderr
    assert not any(ln.lstrip().startswith("VACUOUS_PASS")
                   for ln in r.stderr.splitlines()), r.stderr
    json.loads(r.stdout)          # stdout stays the report and nothing else


# ===========================================================================
# (3) THE INVARIANT — verdict and vacuous never contradict, over EVERY case
# ===========================================================================
def test_verdict_and_vacuous_never_contradict_across_every_category(tmp_path):
    """The defect stated as a property, swept over all ten ERROR categories
    plus the two clean arms. A verdict of FAIL asserts a conclusion; the
    NOT-CHECKED disclaimer denies one. No artefact may carry both."""
    cases = dict(NOT_RUN_CASES)
    cases.update(EXAMINED_AND_WRONG_CASES)
    cases.update({f"zero_{k}": v
                  for k, v in EXAMINED_AND_WRONG_AT_ZERO_DENOMINATOR.items()})
    cases["_clean"] = lambda p: _project(p)
    cases["_grounded"] = lambda p: _project(p, spef_text=_SPEF_GROUNDED_ONLY)

    for name, build in cases.items():
        proj = build(tmp_path / f"inv_{name.lower()}")
        _, doc = _run(proj)
        verdict, vacuous, reason = (
            doc["verdict"], doc["summary"]["vacuous"], _reason(doc))
        if verdict in ("NOT_RUN", "VACUOUS_PASS"):
            assert vacuous is True, (name, verdict, vacuous)
            assert _NOT_CHECKED in reason, (name, reason)
        else:
            assert verdict in ("PASS", "FAIL"), (name, verdict)
            assert vacuous is False, (name, verdict, vacuous)
            assert _NOT_CHECKED not in reason, (
                f"{name}: verdict {verdict} ships the NOT-CHECKED disclaimer "
                f"-- the #506 contradiction: {reason}")


def test_a_rejected_artefact_still_says_why_no_fold_was_re_derived(tmp_path):
    """The disclosure contract survives the split. A FAIL with examined == 0
    still owes a written reason (`_gate_denominator` REQUIRES one) — it just
    must be the reason a REJECTED artefact gets, not a skip's."""
    import _gate_denominator as gd
    for cat, build in EXAMINED_AND_WRONG_AT_ZERO_DENOMINATOR.items():
        proj = build(tmp_path / f"rej_{cat.lower()}")
        _, doc = _run(proj)
        assert gd.disclosure_violations(doc["summary"]) == [], cat
        reason = _reason(doc)
        assert reason.strip(), cat
        assert cat in reason, (cat, reason)
        assert _NOT_CHECKED not in reason, (cat, reason)


def test_a_defect_outranks_a_missing_input_in_the_same_run(tmp_path):
    """PRECEDENCE, both errors present at once. The hold corner's bounded SPEF
    is gone (could-not-run) AND the setup corner's fold was dropped
    (examined-and-wrong). The loud answer must win — a NOT_RUN here would hide
    a proven false-clean behind a missing file."""
    _, gh = _bounded_from_emitter(_SPEF_COUPLED)
    dropped, _ = M.rewrite_spef_folded(_SPEF_COUPLED, {"*1": 0.0, "*2": 0.0},
                                       "setup")
    proj = _project(tmp_path / "mixed", setup_bounded=dropped,
                    hold_bounded=gh)
    (proj / "design.mcf_hold.spef").unlink()
    r, doc = _run(proj)
    cats = _categories(doc)
    assert "NO_BOUNDED_SPEF" in cats and "FOLD_NOT_APPLIED" in cats, cats
    assert doc["verdict"] == "FAIL", doc["verdict"]
    assert r.returncode == G.RC_FAIL


def test_a_partial_run_that_proved_something_is_not_called_not_run(tmp_path):
    """THE OTHER DIRECTION OF THE SAME LIE. The setup corner proved real folds
    and only the hold corner's input is missing. Calling that "NOT_RUN" would
    deny work the gate demonstrably did, so it stays a FAIL — with a non-zero
    denominator and no NOT-CHECKED disclaimer, so there is still exactly one
    answer in the file."""
    proj = _project(tmp_path / "partial")
    (proj / "design.mcf_hold.spef").unlink()
    r, doc = _run(proj)
    assert "NO_BOUNDED_SPEF" in _categories(doc), doc["findings"]
    assert doc["summary"]["denominator"]["examined"] > 0, doc["summary"]
    assert doc["verdict"] == "FAIL", doc["verdict"]
    assert doc["summary"]["vacuous"] is False
    assert r.returncode == G.RC_FAIL


# ===========================================================================
# (4) THE UMBRELLA — driven through the REAL step-27 spec, not reasoned about
# ===========================================================================
def _step27_si_gate_spec():
    """The `optional_program_exit_zero` sub-gate the shipped flow wires for
    this program, read out of the YAML so the test cannot drift from it."""
    import yaml
    import flow_compliance_check as F
    flow = yaml.safe_load(Path(F.DEFAULT_FLOW_DEF).read_text())
    for step in flow.get("steps", []):
        for sub in (step.get("gate", {}) or {}).get("all_of", []) or []:
            spec = (sub or {}).get("optional_program_exit_zero")
            if isinstance(spec, dict) and "si_mcf_sta_check" in str(
                    spec.get("command", "")):
                return spec
    raise AssertionError("step 27 no longer wires si_mcf_sta_check")


def test_the_flow_still_wires_this_gate_the_way_the_test_drives_it():
    spec = _step27_si_gate_spec()
    assert spec["command"].startswith("si_mcf_sta_check ")
    assert spec["condition_files_exist"] == ["reports/phase3/si_mcf_sta.json"]


def test_the_not_run_tier_is_not_credited_as_a_skip_by_the_flow(tmp_path):
    """REQUIREMENT 3, DRIVEN. Whatever rc the fix chose, the umbrella must put
    a could-not-run gate in the FAILING bucket — never the vacuous-pass one.

    NO_BOUNDED_SPEF is the case that decides the rc: the emitter's own report
    names a bounded SPEF that is absent, i.e. an INCOMPLETE SIGN-OFF. Had the
    fix moved the not-run tier to rc 2, `_check_program_exit_zero` would credit
    it as a pass and this incomplete sign-off would render as a skipped step."""
    import flow_compliance_check as F
    spec = _step27_si_gate_spec()
    gate = {"optional_program_exit_zero": spec}

    for cat, build in NOT_RUN_CASES.items():
        proj = build(tmp_path / f"flow_{cat.lower()}")
        if cat == "NO_REPORT":
            # The flow's own `condition_files_exist` skips the gate entirely
            # when the emitter produced no report; that N/A is the flow's
            # decision, not this gate's, and is asserted separately below.
            continue
        passed, reasons = F._evaluate_gate(proj, gate)
        assert passed is False, (cat, reasons)
        assert not any(str(x).startswith(F._VACUOUS_HINT_PREFIX)
                       for x in reasons), (cat, reasons)


def test_the_examined_and_wrong_tier_still_fails_the_step(tmp_path):
    """The half that must not get quieter, at the umbrella."""
    import flow_compliance_check as F
    gate = {"optional_program_exit_zero": _step27_si_gate_spec()}
    cases = dict(EXAMINED_AND_WRONG_CASES)
    cases.update({f"zero_{k}": v
                  for k, v in EXAMINED_AND_WRONG_AT_ZERO_DENOMINATOR.items()})
    for cat, build in cases.items():
        proj = build(tmp_path / f"flowloud_{cat.lower()}")
        passed, reasons = F._evaluate_gate(proj, gate)
        assert passed is False, (cat, reasons)
        assert not any(str(x).startswith(F._VACUOUS_HINT_PREFIX)
                       for x in reasons), (cat, reasons)


def test_the_clean_and_vacuous_buckets_are_unchanged_at_the_umbrella(tmp_path):
    import flow_compliance_check as F
    gate = {"optional_program_exit_zero": _step27_si_gate_spec()}

    clean = _project(tmp_path / "flow_clean")
    passed, reasons = F._evaluate_gate(clean, gate)
    assert passed is True, reasons
    assert not any(str(x).startswith(F._VACUOUS_HINT_PREFIX) for x in reasons)

    grounded = _project(tmp_path / "flow_grounded",
                        spef_text=_SPEF_GROUNDED_ONLY)
    passed, reasons = F._evaluate_gate(grounded, gate)
    assert passed is True, reasons
    assert any(str(x).startswith(F._VACUOUS_HINT_PREFIX)
               for x in reasons), reasons


def test_no_report_is_the_flows_own_n_a_and_not_this_gates_verdict(tmp_path):
    """`condition_files_exist` means the flow never runs the gate when the
    emitter produced nothing — so NO_REPORT reaches the umbrella only via a
    direct invocation. Pinned so the split above is not credited with a
    behaviour the flow already had."""
    import flow_compliance_check as F
    gate = {"optional_program_exit_zero": _step27_si_gate_spec()}
    proj = _b_no_report(tmp_path / "flow_noreport")
    passed, reasons = F._evaluate_gate(proj, gate)
    assert passed is True, reasons
    # THE PROPERTY THIS TEST IS ABOUT is that the flow never RAN the gate, and
    # that is asserted directly rather than through the absence of any reason
    # at all. W4 stopped that absence from being the evidence: an unmet
    # condition now leaves a record naming what was not looked at and the
    # reason the clause declares for why that is a genuine not-applicable. The
    # gate still does not run, which is what "the split is not credited with a
    # behaviour the flow already had" needs.
    assert not any(r.startswith(F._RAN_HINT_PREFIX) for r in reasons), reasons
    na = [r for r in reasons if r.startswith(F._NOT_APPLICABLE_HINT_PREFIX)]
    assert len(na) == 1 and "si_mcf_sta.json" in na[0], reasons
    assert not [r for r in reasons
                if not r.startswith(F._NOT_APPLICABLE_HINT_PREFIX)], reasons
    # ... and invoked directly it is a NOT_RUN, not a design failure.
    r, doc = _run(proj)
    assert (r.returncode, doc["verdict"]) == (G.RC_FAIL, "NOT_RUN")


# ===========================================================================
# CHIP-AGNOSTIC — the split keys on the gate's own categories only
# ===========================================================================
def test_the_tiering_names_no_design_pdk_or_vendor():
    """The classification is a frozenset of this gate's OWN finding
    categories. Nothing about a design, a PDK or a vendor may enter it."""
    assert G.NOT_RUN_CATEGORIES == frozenset(NOT_RUN_CASES)
    for cat in G.NOT_RUN_CATEGORIES:
        assert cat.replace("_", "").isalpha(), cat
    # the complement is not enumerated in the source: anything NOT listed as a
    # could-not-run cause is treated as a substantive defect, so a future
    # category defaults to the LOUD tier.
    for cat in EXAMINED_AND_WRONG_CASES:
        assert cat not in G.NOT_RUN_CATEGORIES, cat


def test_the_split_covers_every_error_category_the_gate_can_raise():
    """COMPLETENESS: no ERROR category may exist that neither table exercises.
    Read off the source so a category added later without a test is caught
    here rather than by nobody."""
    import re
    src = (_PROGRAMS / "si_mcf_sta_check.py").read_text()
    raised = set(re.findall(r'Finding\(\s*"ERROR",\s*"([A-Z_]+)"', src))
    covered = set(NOT_RUN_CASES) | set(EXAMINED_AND_WRONG_CASES)
    assert raised, "the ERROR-category scrape found nothing — regex is stale"
    assert raised - covered == set(), (
        f"ERROR categories raised by the gate but not exercised by this "
        f"file's tables: {sorted(raised - covered)}")
