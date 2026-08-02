"""#654 — the router aborted and only one step noticed.

MEASURED on a real sky130A run:

    x  Step 26  Antenna check                     FAIL
    v  Step 31  Physical Verification (DRC+LVS)   PASS
    v  Step 37  GDSII output                      PASS
    v  Step 38  Foundry Handoff                   PASS

A 24 MB GDS was streamed and declared handoff-ready for a layout the router
never finished. Step 37's own NAME states the contract — "only if Step 31 PV
fully clean" — and Step 31 passed vacuously, so the guard let it through.

DRC and LVS on an unrouted layout are not WRONG, they are VACUOUS: there is
little routing to violate a spacing rule, and a netlist with no realized
interconnect can still match uniquely. True statements about a question nobody
asked, published under the names of the questions that were.

Nothing had to be inferred. The antenna step already writes

    { "clean": false, "routing_incomplete": true,
      "verdict": "FAIL", "net_violations": 0 }

and that pair on one line IS the trap: a clean antenna count on a design with no
realized signal routing. `grep -c routing_incomplete` over
`foundry_handoff_pack_gen.py` returned 0. `flow_compliance_check` catches it at
the audit layer, so the FLOW knows; the steps each certify independently and
never ask.

THE NEGATIVE CONTROL THE ISSUE ASKED FOR, run end to end:

    antenna.json                  reader   step_drc       handoff rc
    routing_incomplete: true      True     VACUOUS_PASS   2
    routing_incomplete: false     False    not blocked    0
    key ABSENT                    None     not blocked    0

"A gate that only fires in one direction is the defect this issue is about."
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

_spec = importlib.util.spec_from_file_location(
    "phase3_one_shot_runner", _PROGRAMS / "phase3_one_shot_runner.py")
P = importlib.util.module_from_spec(_spec)
sys.modules["phase3_one_shot_runner"] = P
try:
    _spec.loader.exec_module(P)
except SystemExit:
    pass


def _project(tmp_path, routing_incomplete):
    """A run whose antenna step recorded (or did not record) the fact."""
    r = P._pl.reports_phase3_dir(tmp_path)
    r.mkdir(parents=True, exist_ok=True)
    payload = {
        "tool": "openroad",
        "mode": "antenna_check_in_session_post_repair",
        # 0 violations beside an unrouted design — the trap, verbatim
        "net_violations": 0,
        "pin_violations": 0,
        "clean": True,
        "verdict": "FAIL" if routing_incomplete is True else "PASS",
    }
    if routing_incomplete is not None:
        payload["routing_incomplete"] = routing_incomplete
    (r / "antenna.json").write_text(json.dumps(payload, indent=2))
    return tmp_path


# ── the recorded fact, read rather than re-derived ────────────────────────
def test_it_reads_the_fact_the_antenna_step_recorded(tmp_path):
    assert P.routing_is_incomplete(_project(tmp_path, True)) is True


def test_a_routed_run_reads_false(tmp_path):
    assert P.routing_is_incomplete(_project(tmp_path, False)) is False


def test_a_missing_key_is_none_and_not_false(tmp_path):
    """LOAD-BEARING. A run whose antenna step never reached the in-session
    post-repair path records no such key. Returning False there would say
    "routing is fine" about a run that never measured it — the same defect one
    level up, inside its own fix."""
    assert P.routing_is_incomplete(_project(tmp_path, None)) is None


def test_no_artefact_at_all_is_none(tmp_path):
    assert P.routing_is_incomplete(tmp_path) is None


def test_a_corrupt_artefact_is_none_not_a_crash(tmp_path):
    r = P._pl.reports_phase3_dir(tmp_path)
    r.mkdir(parents=True, exist_ok=True)
    (r / "antenna.json").write_text("{not json")
    assert P.routing_is_incomplete(tmp_path) is None


# ── what the sign-off steps do with it ────────────────────────────────────
def test_an_unrouted_run_makes_a_signoff_step_vacuous(tmp_path):
    v = P._vacuous_on_unrouted(_project(tmp_path, True), "drc", 0.0)
    assert v is not None and v.status == "VACUOUS_PASS"
    assert "INCOMPLETE" in v.detail


def test_a_vacuous_signoff_makes_the_RUN_fail(tmp_path):
    """THE ASSERTION THAT FOUND A DEFECT IN THIS FIX. `_aggregate_verdict`
    matched VACUOUS_PASS against neither its FAIL/BLOCKED test nor its
    WAIVED/SKIP/ENV_UNAVAILABLE test, so the run returned "PASS" — the unrouted
    sign-off steps would have produced a GREEN run, which is exactly #654,
    inside its own fix."""
    R = P.StepResult
    assert P._aggregate_verdict([R("a", "PASS")]) == "PASS"
    assert P._aggregate_verdict([R("a", "PASS"),
                                 R("b", "VACUOUS_PASS")]) == "FAIL"


def test_the_established_waiver_states_are_untouched(tmp_path):
    """LOAD-BEARING, and the second defect the first attempt had. Deriving the
    answer from `_flow_verdict_tiers` marks bare SKIP and ENV_UNAVAILABLE as
    qualified done-claims too — both long-established PASS_WITH_WAIVERS states
    HERE. StepResult.status is a different vocabulary from the flow-compliance
    producer's, and borrowing a classifier across two vocabularies is how a fix
    acquires a second defect."""
    R = P.StepResult
    for w in ("SKIP", "WAIVED", "ENV_UNAVAILABLE"):
        assert P._aggregate_verdict([R("a", "PASS"),
                                     R("b", w)]) == "PASS_WITH_WAIVERS", w


def test_a_routed_run_is_untouched(tmp_path):
    """THE ACCEPT CASE, and the one that decides whether this can ship: the
    corpus is mostly healthy runs and every one must proceed exactly as before."""
    assert P._vacuous_on_unrouted(_project(tmp_path, False), "drc", 0.0) is None


def test_an_unrecorded_run_is_untouched(tmp_path):
    """Refusing on None would fail every run whose antenna step took a different
    path — a gate that fires on absence of evidence, which is the mirror of the
    bug and just as wrong."""
    assert P._vacuous_on_unrouted(_project(tmp_path, None), "drc", 0.0) is None


# ── the three steps are actually wired, not merely wire-able ──────────────
def test_the_three_signoff_steps_consult_it():
    """WIRING. A helper nothing calls leaves the certification exactly as it
    was — which is the whole finding."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    for fn, name in (("def step_drc(", "drc"), ("def step_lvs(", "lvs"),
                     ("def step_gds(", "gds")):
        i = body.index(fn)
        window = body[i:i + 1400]
        assert f'_vacuous_on_unrouted(project, "{name}", t0)' in window, fn


# ── step 38, the most expensive form ──────────────────────────────────────
def _handoff(project):
    return subprocess.run(
        [sys.executable, str(_PROGRAMS / "foundry_handoff_pack_gen.py"),
         str(project)],
        # 30s: `ci_harness_timeout_ceiling_check` caps an inner bound at 60,
        # because the harness dies at 180 and a longer bound kills the SESSION
        # rather than the call. MEASURED at 0.04s per invocation. This test
        # tripped that ceiling on its first landing — the third time in this one
        # batch, which is why the ceiling is a gate and not a convention.
        capture_output=True, text=True, timeout=30)


def test_the_handoff_pack_refuses_on_an_unrouted_layout(tmp_path):
    r = _handoff(_project(tmp_path, True))
    assert r.returncode == 2, r.stdout[-400:] + r.stderr[-400:]
    assert "INCOMPLETE" in r.stderr


def test_the_handoff_pack_does_not_refuse_a_routed_one(tmp_path):
    """The other direction, run for real. If this refused too, the fix would be
    "never hand off", which is not a fix."""
    r = _handoff(_project(tmp_path, False))
    assert r.returncode != 2 or "INCOMPLETE" not in r.stderr


def test_the_handoff_pack_does_not_refuse_an_unrecorded_run(tmp_path):
    r = _handoff(_project(tmp_path, None))
    assert r.returncode != 2 or "INCOMPLETE" not in r.stderr


def test_the_generator_names_the_fact_at_all():
    """`grep -c 'antenna.json\\|routing_incomplete'` over this file returned 0
    when the issue was filed. That count is the finding."""
    src = (_PROGRAMS / "foundry_handoff_pack_gen.py").read_text(encoding="utf-8")
    assert "routing_incomplete" in src and "antenna.json" in src
