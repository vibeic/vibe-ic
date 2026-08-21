#!/usr/bin/env python3
"""Bidirectional control for the `required_inputs` PRE-FLIGHT WIRING.

The capability (`step_required_inputs_check`) already had its own control. What
had NO control — and no caller — was the BEHAVIOUR: a runner that refuses to
dispatch a step whose declared inputs are absent.

FORWARD  a synthetic run missing exactly ONE declared input has that step
         REFUSED: the step function is never entered, the row is BLOCKED, and
         the refusal names the absent artefact AND the step that owed it.

REVERSE  the SAME synthetic run with that one input restored — nothing else
         changed — dispatches the step normally. This is the half that stops
         the forward control from being satisfied by a check that refuses
         everything.

Plus the controls that stop this from becoming a falsely-clean gate:
  * every site's declared flow-step ids exist in the shipped flow;
  * every declared site is ACTUALLY wired at a call site in its runner (a fix
    that never reaches the code that runs is not a fix);
  * BLOCKED is non-green in BOTH runners' `_aggregate_verdict`;
  * a producer-disclosed skip does NOT refuse (legitimate skips must not break);
  * an UNDECLARED span runs but SAYS it was not checked;
  * an unreadable flow yields UNAVAILABLE, never READY.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import step_preflight as SP                                   # noqa: E402

FLOW = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"


# --------------------------------------------------------------------------- #
# A synthetic run whose ONLY question is the one declared input of canonical
# step 31 (Physical Verification): step 21's `phase3/stage3/pnr/routed.def`.
# --------------------------------------------------------------------------- #
ROUTED_DEF = "phase3/stage3/pnr/routed.def"


def _synthetic_run(root: Path, with_routed_def: bool) -> Path:
    p = root / "run"
    (p / "phase2/stage1/rtl").mkdir(parents=True, exist_ok=True)
    (p / "phase2/stage2/synth").mkdir(parents=True, exist_ok=True)
    (p / "phase3/stage3/pnr").mkdir(parents=True, exist_ok=True)
    (p / "phase2/stage1/rtl/top.sv").write_text(
        "module top(input clk); endmodule\n")
    (p / "phase2/stage2/synth/netlist.v").write_text("module top(); endmodule\n")
    if with_routed_def:
        (p / ROUTED_DEF).write_text("DESIGN top ;\nEND DESIGN\n")
    return p


class _Spy:
    """Stands in for `step_drc`. Records whether it was ever entered."""

    def __init__(self):
        self.calls = 0

    def __call__(self, *a, **kw):
        self.calls += 1

        class R:
            name = "drc"
            status = "PASS"
            detail = "spy ran"
        return R()


def _refusal_factory(name):
    def _mk(detail, extras):
        class R:
            pass
        r = R()
        r.name = name
        r.status = SP.REFUSAL_STATUS
        r.detail = detail
        r.extras = extras
        return r
    return _mk


def _ledger(project: Path) -> dict:
    return json.loads(SP.ledger_path(project).read_text())


# --------------------------------------------------------------------------- #
# FORWARD
# --------------------------------------------------------------------------- #
def test_forward_missing_declared_input_refuses_before_the_step_runs(tmp_path):
    p = _synthetic_run(tmp_path, with_routed_def=False)
    spy = _Spy()

    result = SP.gate(p, "phase3_one_shot_runner", "drc",
                     _refusal_factory("drc"), spy, p, "top", None, "")

    assert spy.calls == 0, "the step was DISPATCHED despite its input being absent"
    assert result.status == SP.REFUSAL_STATUS
    assert result.extras["finding"] == SP.REFUSAL_FINDING
    # names the artefact AND the step that owed it
    assert ROUTED_DEF in result.detail
    assert "owed by step 21" in result.detail
    assert [i["path"] for i in result.extras["absent_inputs"]] == [ROUTED_DEF]

    led = _ledger(p)
    assert led["counts"]["REFUSED"] == 1
    assert led["refused"][0]["site"] == "drc"
    assert led["refused"][0]["absent"][0]["from"] == "21"
    # "refused for want of input" must be readable as such, not as "ran and
    # produced nothing".
    assert led["decisions"][0]["verdict"] == "REFUSED"
    assert led["decisions"][0]["allow"] is False


# --------------------------------------------------------------------------- #
# REVERSE — same run, one input restored, nothing else changed
# --------------------------------------------------------------------------- #
def test_reverse_same_run_with_the_input_present_runs_the_step(tmp_path):
    p = _synthetic_run(tmp_path, with_routed_def=True)
    spy = _Spy()

    result = SP.gate(p, "phase3_one_shot_runner", "drc",
                     _refusal_factory("drc"), spy, p, "top", None, "")

    assert spy.calls == 1, "the step was refused even though its input is present"
    assert result.status == "PASS"

    led = _ledger(p)
    assert led["counts"].get("REFUSED") is None
    assert led["decisions"][0]["verdict"] == "READY"
    assert led["decisions"][0]["allow"] is True
    assert any(i["path"] == ROUTED_DEF and i["present"]
               for i in led["decisions"][0]["inputs"])


def test_forward_and_reverse_differ_only_in_that_one_file(tmp_path):
    """The pair above is a CONTROL only if the two trees differ by one path."""
    a = _synthetic_run(tmp_path / "a", with_routed_def=False)
    b = _synthetic_run(tmp_path / "b", with_routed_def=True)
    ra = {str(f.relative_to(a)) for f in a.rglob("*") if f.is_file()}
    rb = {str(f.relative_to(b)) for f in b.rglob("*") if f.is_file()}
    assert rb - ra == {ROUTED_DEF}
    assert ra - rb == set()


# --------------------------------------------------------------------------- #
# A run that LEGITIMATELY skips a step must not be broken
# --------------------------------------------------------------------------- #
def test_producer_disclosed_skip_is_not_an_absence(tmp_path):
    """Step 15 declares it reads step 12's post_dft_netlist.v. A design with no
    scan chain never has one — step 12 writes an owning, capability-flagged
    skip marker instead, and `flow_compliance_check` already promotes that to
    SKIPPED-CONDITION. The pre-flight must agree, via the SAME function."""
    p = _synthetic_run(tmp_path, with_routed_def=True)
    (p / "phase2/stage2/synth/post_dft_not_run.json").write_text(json.dumps({
        "verdict": "SKIPPED-CONDITION",
        "capability_flag": "cap:post_dft_scan_optimization",
        "skips_required_output": "phase2/stage2/synth/post_dft_netlist.v",
        "reason": "no scan_netlist.v (DFT was disclosed-skipped)",
    }))
    d = SP.decide(p, "phase3_one_shot_runner", "pnr")
    assert d.allow is True
    assert d.verdict != "REFUSED"
    states = {i["path"]: i["state"] for i in d.inputs}
    assert states["phase2/stage2/synth/post_dft_netlist.v"] == "producer-skipped"

    # ...and WITHOUT the marker the same absence DOES refuse, so the clause
    # above is a disclosure rule, not a hole.
    (p / "phase2/stage2/synth/post_dft_not_run.json").unlink()
    d2 = SP.decide(p, "phase3_one_shot_runner", "pnr")
    assert d2.verdict == "REFUSED" and d2.allow is False


# --------------------------------------------------------------------------- #
# UNDECLARED must not block, and must not pass silently either
# --------------------------------------------------------------------------- #
def test_undeclared_span_runs_but_says_it_was_not_checked(tmp_path, monkeypatch):
    """7 of the flow's 63 steps declare no required_inputs. An UNKNOWN
    dependency is not an ABSENT one — but it may not read as READY."""
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    undeclared = [str(s["id"]) for s in doc["steps"]
                  if not s.get("required_inputs")]
    assert undeclared, "the flow no longer has an undeclared step to test with"
    sid = undeclared[0]

    monkeypatch.setitem(
        SP.RUNNER_PLANS, "unit_test_runner",
        SP.RunnerPlan(name="unit_test_runner", inherited_steps=(),
                      inherits=None, sites=(("only", (sid,)),)))
    p = _synthetic_run(tmp_path, with_routed_def=True)
    d = SP.decide(p, "unit_test_runner", "only")
    assert d.verdict in ("UNDECLARED", "NOT-JUDGED")
    if d.verdict == "UNDECLARED":
        assert d.allow is True
        assert "UNKNOWN, not empty" in d.detail
        assert "nothing passed" in d.detail


# --------------------------------------------------------------------------- #
# "I could not look" must never read as "I looked and it was fine"
# --------------------------------------------------------------------------- #
def test_unreadable_flow_is_unavailable_not_ready(tmp_path):
    p = _synthetic_run(tmp_path, with_routed_def=True)
    d = SP.decide(p, "phase3_one_shot_runner", "drc",
                  flow_def=tmp_path / "does_not_exist.yaml")
    assert d.verdict == "UNAVAILABLE"
    assert d.verdict != "READY"
    assert "UNVERIFIED" in d.detail
    assert d.allow is True          # a broken flow must not brick a run …


def test_strict_env_escalates_unavailable_to_a_refusal(tmp_path, monkeypatch):
    """… but the escalation path exists, and only ever TIGHTENS."""
    monkeypatch.setenv(SP.STRICT_ENV, "1")
    p = _synthetic_run(tmp_path, with_routed_def=True)
    d = SP.decide(p, "phase3_one_shot_runner", "drc",
                  flow_def=tmp_path / "does_not_exist.yaml")
    assert d.verdict == "UNAVAILABLE"
    assert d.allow is False


def test_a_stale_site_to_flow_map_is_unavailable_not_silently_skipped(
        tmp_path, monkeypatch):
    monkeypatch.setitem(
        SP.RUNNER_PLANS, "unit_test_runner",
        SP.RunnerPlan(name="unit_test_runner", inherited_steps=(),
                      inherits=None, sites=(("only", ("NO_SUCH_STEP",)),)))
    p = _synthetic_run(tmp_path, with_routed_def=True)
    d = SP.decide(p, "unit_test_runner", "only")
    assert d.verdict == "UNAVAILABLE"
    assert "the runner-to-flow map is stale" in d.detail


# --------------------------------------------------------------------------- #
# The map itself
# --------------------------------------------------------------------------- #
def test_every_declared_site_names_real_flow_steps():
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    ids = {str(s["id"]) for s in doc["steps"]}
    for rname, plan in SP.RUNNER_PLANS.items():
        for site, span in plan.sites:
            assert span, f"{rname}/{site} declares an empty span"
            unknown = [i for i in span if i not in ids]
            assert not unknown, f"{rname}/{site} names non-existent {unknown}"


def test_due_set_grows_monotonically_along_the_dispatch_order():
    for rname, plan in SP.RUNNER_PLANS.items():
        prev = None
        for site, _span in plan.sites:
            due, err = SP.due_steps(rname, site)
            assert err is None, err
            if prev is not None:
                assert prev <= due, (
                    f"{rname}/{site}: the due set shrank — dispatch order is "
                    f"not being accumulated")
            prev = due


# --------------------------------------------------------------------------- #
# Did the fix reach the code that actually runs?
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("runner", sorted(SP.RUNNER_PLANS))
def test_every_declared_site_is_wired_at_a_real_call_site(runner):
    src = (PROGRAMS / f"{runner}.py").read_text(encoding="utf-8")
    assert "import step_preflight as _spf" in src
    for site, _span in SP.RUNNER_PLANS[runner].sites:
        pat = re.compile(r"_spf\.gate\(\s*project,\s*[\"']"
                         + re.escape(runner) + r"[\"'],\s*[\"']"
                         + re.escape(site) + r"[\"']")
        assert pat.search(src), (
            f"{runner} declares site {site!r} but no `_spf.gate(project, "
            f"'{runner}', '{site}', …)` call site exists — the pre-flight "
            f"would be available but never enforced, which is the exact state "
            f"this change exists to leave behind")


def test_blocked_is_never_green_in_either_runner():
    import design_one_shot_runner as D
    import phase3_one_shot_runner as P3
    for mod in (D, P3):
        row = mod.StepResult("x", SP.REFUSAL_STATUS, 0.0, "refused")
        assert mod._aggregate_verdict([row]) == "FAIL", (
            f"{mod.__name__}._aggregate_verdict lets a pre-flight refusal "
            f"reach a green verdict")
        ok = mod.StepResult("y", "PASS", 0.0, "ran")
        assert mod._aggregate_verdict([ok, row]) == "FAIL"


def test_gate_returns_exactly_one_object_so_plan_minus_one_still_works(tmp_path):
    """phase3 reads `plan[-1]` immediately after several of these appends."""
    p = _synthetic_run(tmp_path, with_routed_def=False)
    r = SP.gate(p, "phase3_one_shot_runner", "drc", _refusal_factory("drc"),
                _Spy(), p)
    assert not isinstance(r, (list, tuple))
    assert hasattr(r, "status")


def test_ledger_accumulates_across_dispatches_and_survives_a_corrupt_file(
        tmp_path):
    p = _synthetic_run(tmp_path, with_routed_def=True)
    SP.record(p, SP.decide(p, "phase3_one_shot_runner", "synth"))
    SP.ledger_path(p).write_text("{not json")
    SP.record(p, SP.decide(p, "phase3_one_shot_runner", "drc"))
    led = _ledger(p)
    assert len(led["decisions"]) == 1        # corrupt file replaced, not fatal
    SP.record(p, SP.decide(p, "phase3_one_shot_runner", "lvs"))
    assert len(_ledger(p)["decisions"]) == 2


def test_there_is_no_switch_that_turns_a_refusal_into_a_pass():
    """`VIBE_IC_PREFLIGHT_STRICT` must be the ONLY env knob, and it must only
    ever tighten. A weakening switch would make the refusal decorative."""
    src = (PROGRAMS / "step_preflight.py").read_text(encoding="utf-8")
    envs = set(re.findall(r"os\.environ\.get\(\s*([A-Za-z_]+|\"[^\"]+\")",
                          src))
    assert envs <= {"STRICT_ENV"}, f"unexpected env knob(s): {envs}"


# --------------------------------------------------------------------------- #
# A run that legitimately skips a step, from the CALLER's own authority
# --------------------------------------------------------------------------- #
def test_caller_declared_not_applicable_dispatches_and_is_recorded(tmp_path):
    """A pure-analog IC has no digital RTL track: canonical step 1 produces no
    `phase2/stage1/rtl/*` BY DESIGN and `step_yosys_synth` answers SKIP. The
    pre-flight must defer to that, dispatch anyway, and SAY it did — turning a
    legitimate SKIP into BLOCKED would break a legitimately-skipping run."""
    p = _synthetic_run(tmp_path, with_routed_def=True)
    for f in (p / "phase2/stage1/rtl").glob("*"):
        f.unlink()
    spy = _Spy()

    # without the deferral the same tree refuses …
    refused = SP.gate(p, "design_one_shot_runner", "yosys_synth",
                      _refusal_factory("yosys_synth"), spy, p)
    assert refused.status == SP.REFUSAL_STATUS and spy.calls == 0

    # … and with the caller's own reason it dispatches, recorded, not silenced.
    ok = SP.gate(p, "design_one_shot_runner", "yosys_synth",
                 _refusal_factory("yosys_synth"), spy, p,
                 _preflight_not_applicable="pure-analog registry class")
    assert ok.status == "PASS" and spy.calls == 1
    last = _ledger(p)["decisions"][-1]
    assert last["verdict"] == "NOT-APPLICABLE"
    assert "pure-analog registry class" in last["detail"]


def test_not_applicable_needs_a_REASON_not_a_bare_flag(tmp_path):
    """An empty/None reason must NOT open the gate — otherwise the deferral is
    a bare bypass switch."""
    p = _synthetic_run(tmp_path, with_routed_def=False)
    spy = _Spy()
    r = SP.gate(p, "phase3_one_shot_runner", "drc", _refusal_factory("drc"),
                spy, p, _preflight_not_applicable="")
    assert r.status == SP.REFUSAL_STATUS and spy.calls == 0


def test_phase3_pure_analog_waiver_still_precedes_every_gate():
    """MEASURED on the real `u_hawaii_adc` Phase-1 tree (class `data_converter`,
    all-analog top interface, empty rtl/): the phase-3 runner WAIVEs the whole
    digital backend and writes NO pre-flight ledger, because the waiver branch
    is upstream of every `_spf.gate` call. Without that ordering, a pure-analog
    cell's five WAIVED rows would become five BLOCKED rows — a legitimately
    skipping run broken by the pre-flight. Cheap structural guard for an
    invariant whose real proof takes a whole phase-3 run."""
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text().splitlines()
    waive = next(i for i, l in enumerate(src) if "elif is_pure_analog:" in l)
    first_gate = next(i for i, l in enumerate(src) if "_spf.gate(" in l)
    assert waive < first_gate, (
        "a `_spf.gate` call now precedes the pure-analog waiver — a pure-analog "
        "cell would be REFUSED instead of WAIVED")
