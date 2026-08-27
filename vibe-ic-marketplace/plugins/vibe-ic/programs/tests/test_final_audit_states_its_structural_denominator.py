"""final_audit must state the POPULATION its verdict was computed over.

THE FINDING. `design_one_shot_runner.step_final_audit` reads exactly one thing
out of `flow_compliance_check`: the `Overall:` substring of stdout. `Overall`
is set by `structural_fail_lines`, which `_p0_structural_fail_lines` builds
from sub-gate records whose verdict is exactly `FAIL`. A registered sub-gate
that returned NO verdict at all (`NOT_INVOCABLE` — the caller's own argv
defect, #492) contributes to that list precisely what a PASS contributes:
nothing. So a verdict over the whole registered population and a verdict over
a fraction of it printed the same word, exited the same code, and were recorded
by the runner as the same step status.

MEASURED on the preserved 20-problem VerilogEval-Human run
(`benchmark_dispatch.py verilogeval-human --solve`), re-audited from a clean
checkout at origin/main 40d0e14c0:

  * 19 of 20 projects: registered=246, invoked=210, not_invocable=36. The
    un-invocable 36 are a property of the CALL, not of any project, so EVERY
    one of those verdicts was over 210 gates and said 246.
  * 5 printed `Overall: PASS_WITH_WAIVERS`, rc 0, recorded WAIVED.
  * 1 (`Prob019_m2014_q4f`) dispatched the umbrella not at all — `0 of 246
    checkers returned a verdict` — and was ALSO recorded WAIVED. Not one
    structural gate looked at that design, and the step verdict said the same
    word as the five that had 210 gates behind them.

WHAT IS NOT CHANGED, deliberately: a VACUOUS_PASS sub-gate is a VERDICT — the
gate ran, found its input inapplicable, and said so — and it stays counted in
`invoked`. Nothing here turns an unmeasured gate into a pass; the unmeasured
population is NAMED so that a pass stops implying one. `Overall`, the audit's
exit code, and every FAIL are untouched.
"""
import importlib
import sys
from pathlib import Path

P_DIR = Path(__file__).resolve().parents[1]


def _load(name):
    if name in sys.modules:
        return sys.modules[name]
    sys.path.insert(0, str(P_DIR))
    return importlib.import_module(name)


# --------------------------------------------------------------------------
# 1. The producer: four states, four DIFFERENT sentences.
# --------------------------------------------------------------------------

def test_partial_population_is_named_as_partial_and_not_clean():
    fcc = _load("flow_compliance_check")
    line = fcc.structural_measurement_line(246, 210)
    assert line.startswith(fcc.STRUCTURAL_MEASUREMENT_PREFIX)
    assert "registered=246" in line and "invoked=210" in line
    assert "no_verdict=36" in line
    assert "PARTIAL" in line
    # The whole point: the unmeasured 36 must not read as clean.
    assert "UNCHECKED" in line


def test_whole_population_reads_differently_from_a_partial_one():
    """The GREEN pole. A disclosure that says the same thing about every input
    is not a disclosure — this is the case that must NOT be flagged."""
    fcc = _load("flow_compliance_check")
    whole = fcc.structural_measurement_line(246, 246)
    partial = fcc.structural_measurement_line(246, 210)
    assert "WHOLE" in whole
    assert "no_verdict=0" in whole
    assert "UNCHECKED" not in whole
    assert "PARTIAL" not in whole
    assert whole != partial


def test_empty_population_says_none_answered():
    fcc = _load("flow_compliance_check")
    line = fcc.structural_measurement_line(246, 0)
    assert "NONE" in line
    assert "no_verdict=246" in line
    assert "EMPTY structural population" in line


def test_not_asked_is_never_rendered_as_zero():
    """`None` means the umbrella was not dispatched. Rendering that as `0`
    would make 'no measurement was requested' indistinguishable from 'a
    measurement was requested and nothing answered' — the two states this
    whole finding is about."""
    fcc = _load("flow_compliance_check")
    line = fcc.structural_measurement_line(None, None)
    assert "null" in line
    assert "NOT ASKED" in line
    assert "no_verdict=0" not in line
    assert line != fcc.structural_measurement_line(246, 0)


# --------------------------------------------------------------------------
# 2. The consumer's parser: absence is absence, not zero.
# --------------------------------------------------------------------------

def test_parser_reads_the_three_integers():
    mod = _load("design_one_shot_runner")
    got = mod.parse_structural_measurement(
        "noise\nSTRUCTURAL MEASUREMENT: registered=246 invoked=210 "
        "no_verdict=36 — PARTIAL: ...\nmore noise")
    assert got == {"disclosed": True, "registered": 246,
                   "invoked": 210, "no_verdict": 36}


def test_parser_reports_a_missing_line_as_missing_not_as_zero():
    mod = _load("design_one_shot_runner")
    got = mod.parse_structural_measurement("Overall: PASS\nno disclosure here")
    assert got["disclosed"] is False
    assert got["no_verdict"] is None, (
        "An audit that said nothing about its coverage must not be read as "
        "'0 gates unmeasured' — that manufactures the clean bill of health "
        "this test exists to stop.")


def test_parser_keeps_null_as_none():
    mod = _load("design_one_shot_runner")
    got = mod.parse_structural_measurement(
        "STRUCTURAL MEASUREMENT: registered=null invoked=null no_verdict=null "
        "— the structural-RTL umbrella was NOT ASKED to run")
    assert got["disclosed"] is True
    assert got["registered"] is None and got["no_verdict"] is None


# --------------------------------------------------------------------------
# 3. The step verdict: the two cases must not render identically.
# --------------------------------------------------------------------------

_STUB = '''#!/usr/bin/env python3
import sys
print({overall!r})
print("GATE EXECUTION LEDGER: 1 invocation(s)")
print("  GATE_RAN some_check   rc=2   VACUOUS_PASS")
{extra}
sys.exit({rc})
'''


def _run_step(tmp_path, overall, measurement=None, rc=0):
    mod = _load("design_one_shot_runner")
    progs = tmp_path / "programs"
    progs.mkdir(exist_ok=True)
    extra = f'print({measurement!r})' if measurement is not None else ""
    (progs / "flow_compliance_check.py").write_text(
        _STUB.format(overall=overall, extra=extra, rc=rc))
    project = tmp_path / "proj"
    (project / "reports").mkdir(parents=True, exist_ok=True)
    old = mod.PROGRAMS_DIR
    mod.PROGRAMS_DIR = progs
    try:
        return mod.step_final_audit(project, phase=2)
    finally:
        mod.PROGRAMS_DIR = old


_PARTIAL = ("STRUCTURAL MEASUREMENT: registered=246 invoked=210 "
            "no_verdict=36 — PARTIAL: ...")
_WHOLE = ("STRUCTURAL MEASUREMENT: registered=246 invoked=246 "
          "no_verdict=0 — WHOLE: ...")
_NONE_ANSWERED = ("STRUCTURAL MEASUREMENT: registered=246 invoked=0 "
                  "no_verdict=246 — NONE ...")


def test_a_pass_over_a_partial_population_is_not_recorded_as_a_pass(tmp_path):
    sr = _run_step(tmp_path, "Overall: PASS_WITH_WAIVERS  (strict=True)",
                   _PARTIAL)
    assert sr.status == "INCOMPLETE", (
        "210 of 246 sub-gates answered; the step recorded the same word it "
        "records when all 246 answered.")
    assert sr.extras["structural_measurement"]["no_verdict"] == 36
    assert "210 of 246" in sr.detail


def test_a_pass_over_the_whole_population_is_still_a_pass(tmp_path):
    """The GREEN pole for the step verdict. A check that fires on every input
    is as useless as one that fires on none."""
    assert _run_step(tmp_path, "Overall: PASS  (strict=True)",
                     _WHOLE).status == "PASS"
    assert _run_step(tmp_path, "Overall: PASS_WITH_WAIVERS  (strict=True)",
                     _WHOLE).status == "WAIVED"


def test_an_undisclosed_audit_keeps_its_previous_status(tmp_path):
    """No disclosure line at all (an older flow_compliance_check) must not be
    read as a partial population OR as a whole one."""
    sr = _run_step(tmp_path, "Overall: PASS_WITH_WAIVERS  (strict=True)")
    assert sr.status == "WAIVED"
    assert sr.extras["structural_measurement"]["disclosed"] is False


def test_zero_of_the_population_answering_is_not_a_pass_tier(tmp_path):
    sr = _run_step(tmp_path, "Overall: PASS_WITH_WAIVERS  (strict=True)",
                   _NONE_ANSWERED)
    assert sr.status == "INCOMPLETE"
    assert sr.extras["structural_measurement"]["invoked"] == 0


def test_a_real_finding_still_fails_over_a_partial_population(tmp_path):
    """THE NO-LEAK POLE. The new tier may never absorb a genuine FAIL, and the
    FAIL must now carry the denominator it was computed over."""
    sr = _run_step(tmp_path, "Overall: FAIL  (strict=True)", _PARTIAL, rc=1)
    assert sr.status == "FAIL"
    assert sr.extras["structural_measurement"]["no_verdict"] == 36
    assert "210 of 246" in sr.detail


def test_a_real_finding_over_a_whole_population_still_fails(tmp_path):
    sr = _run_step(tmp_path, "Overall: FAIL  (strict=True)", _WHOLE, rc=1)
    assert sr.status == "FAIL"


# --------------------------------------------------------------------------
# 4. The run-level aggregator must classify the new status.
# --------------------------------------------------------------------------

def test_incomplete_is_classified_and_is_neither_fail_nor_silently_green(capsys):
    mod = _load("design_one_shot_runner")
    plan = [mod.StepResult("final_audit", "INCOMPLETE", 0.0, "x")]
    verdict = mod._aggregate_verdict(plan)
    assert verdict != "FAIL", "a gate that never ran said nothing about the design"
    assert verdict != "PASS", "a step that judged part of its population has not certified all of it"
    assert "UNCLASSIFIED" not in capsys.readouterr().err, (
        "INCOMPLETE must be classified, not absorbed by the catch-all")
