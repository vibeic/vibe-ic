#!/usr/bin/env python3
"""FX_ADC_PHASE_ORDER (1, 2) — phase 2 books as FAIL only what it measured
as failing.

MEASURED on u_hawaii_adc (IC_STATUS_0928, front door on main 7fac744e1, a
`data_converter` with no digital datapath). Phase 2 was FAIL on two rows that
measured nothing:

  analog_acceptance_tb_run   "0 pass, 0 fail, 15 NOT_MEASURED" -> FAIL. Every
                             clause said "no A4 corner-sweep record … it is not
                             a pass and it is not a failure": A4 is written by
                             the analog A-track, which the front door runs
                             AFTER phase 2 (and re-evaluates these checks then,
                             #2064). The step's status formula made any
                             NOT_MEASURED a FAIL.
  fmeda_fault_injection      "--rtl-dir 'phase2/stage1/rtl' does not exist"
                             -> FAIL, while the audit's own FS1 row for the
                             same run said NOT_APPLICABLE ("N/A for analog IC
                             (no digital datapath)"). `main` hands the runner's
                             analog N/A to `dft_lec_chain` and `yosys_synth`
                             but not to this step.

Driven through the real runner steps and the real acceptance producer; only
the A4 record (in the shape `analog_real_corner_sweep` writes) and, for FS1,
the producer subprocess are planted. chip-AGNOSTIC: generic block names.
"""
from __future__ import annotations

import ast
import inspect
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import design_one_shot_runner as D   # noqa: E402

_ROW = "dc_point_for_block_a"
_METHOD = "DC operating point (Vout) for the block"
_BOUNDED_VOUT = {"name": "Vout", "target_raw": "1.2", "range_raw": "1.1-1.3",
                 "unit": "V", "target": 1.2, "min": 1.1, "max": 1.3}
_IN = [("mos_tt", -40, 1.192), ("mos_tt", 27, 1.191), ("mos_tt", 125, 1.190),
       ("mos_ss", -40, 1.192), ("mos_ss", 27, 1.191), ("mos_ss", 125, 1.189),
       ("mos_ff", -40, 1.193), ("mos_ff", 27, 1.192), ("mos_ff", 125, 1.191)]
_OUT = _IN[:5] + [("mos_ss", 125, 1.401)] + _IN[6:]


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False))


def _project(tmp_path: Path, values=None) -> Path:
    """A declared analog verification plan; with `values`, the A4 record the
    analog track would have written."""
    p = tmp_path / "proj"
    _write(p / "phase1/generated_docs/L10_TEST_CASES.json", {"test_cases": [
        {"name": _ROW, "kind": "verification_intent", "stimulus": _METHOD,
         "expected": "verification intent satisfied",
         "evidence": "input/docs/spec.md (Verification intent section)"}]})
    _write(p / "phase1/generated_docs/L22_VERIFICATION_PLAN.json",
           {"fields": {"verification_plan": {
               "schema_version": 1, "track": "analog_mixed_signal",
               "analog": [{"block": "block_a", "block_type": "regulator",
                           "specifications": [_BOUNDED_VOUT],
                           "verification_intent": [
                               {"phase": _ROW, "method": _METHOD,
                                "evidence": "input/docs/spec.md"}]}],
               "unscoped_intent": []}}})
    if values is not None:
        corners = [{"name": f"{pr}_{t}c", "process": pr, "temp_c": t,
                    "simulator_run": True, "vout_v": v} for pr, t, v in values]
        _write(p / "phase3/analog/block_a/corner_results.json", {
            "block": "block_a", "_provenance": "real_ngspice",
            "total_corners": len(corners), "corners_executed": len(corners),
            "corners": corners,
            "spec_results": [{"name": "vout", "status": "PASS",
                              "value": corners[0]["vout_v"]}]})
    return p


def _acceptance(project: Path):
    gen = D.step_analog_acceptance_tb_gen(project)
    assert gen.status == "PASS", (gen.status, gen.detail)
    return D.step_analog_acceptance_tb_run(project)


def _rc(row) -> str:
    return str(getattr(row.reason_class, "value", row.reason_class) or "")


# ---- (1) the acceptance run in phase 2 ------------------------------------
def test_clauses_the_analog_track_has_not_measured_yet_are_not_a_fail(
        tmp_path):
    """THE MEASURED CASE: no A4 record exists at this point in phase 2."""
    row = _acceptance(_project(tmp_path))
    assert row.extras["not_measured"] >= 1 and row.extras["failed"] == 0
    assert row.status == "NOT_MEASURED", (row.status, row.detail)
    assert _rc(row) == "input_absent", row.reason_class
    assert "no analog A-track record" in row.detail
    assert "writes AFTER" not in row.detail


def test_an_a4_record_with_no_measured_clause_is_no_population(tmp_path):
    project = _project(tmp_path, values=_IN)
    rec = project / "phase3/analog/block_a/corner_results.json"
    data = json.loads(rec.read_text())
    for corner in data["corners"]:
        corner.pop("vout_v", None)
    data.pop("spec_results", None)
    _write(rec, data)
    _write(D._pl.report_path(project, "analog_one_shot.json"),
           {"verdict": "PASS"})
    gen = D.step_analog_acceptance_tb_gen(project)
    assert gen.status == "PASS", (gen.status, gen.detail)
    row = D.step_analog_acceptance_tb_run(project)
    assert row.status == "NOT_MEASURED", (row.status, row.detail)
    assert _rc(row) == "no_population", row.reason_class
    assert "record exists" in row.detail
    assert "writes AFTER" not in row.detail


def test_a_refused_clause_is_still_a_fail(tmp_path):
    project = _project(tmp_path)
    plan = project / "phase1/generated_docs/L22_VERIFICATION_PLAN.json"
    doc = json.loads(plan.read_text())
    spec = doc["fields"]["verification_plan"]["analog"][0]["specifications"][0]
    for key in ("target_raw", "range_raw", "target", "min", "max"):
        spec.pop(key, None)
    _write(plan, doc)
    gen = D.step_analog_acceptance_tb_gen(project)
    assert gen.status == "NOT_MEASURED", (gen.status, gen.detail)
    row = D.step_analog_acceptance_tb_run(project)
    assert row.status == "FAIL", (row.status, row.detail)
    assert row.extras["refused"] >= 1


def test_a_measured_value_outside_its_bound_is_still_a_fail(tmp_path):
    """TEETH: the one thing that is red stays red."""
    row = _acceptance(_project(tmp_path, values=_OUT))
    assert row.extras["failed"] >= 1
    assert row.status == "FAIL", (row.status, row.detail)


def test_a_measured_value_inside_its_bound_is_a_pass(tmp_path):
    """CONTROL: green on both trees."""
    row = _acceptance(_project(tmp_path, values=_IN))
    assert row.status == "PASS", (row.status, row.detail)


# ---- (2) FS1 on a design with no digital RTL by design ---------------------
REASON = ("class 'data_converter' is analog-applicable and has no digital "
          "datapath to author")


def _fs1(project: Path, reason, monkeypatch):
    """Call FS1 the way `main` does. Only a tree that ACCEPTS the reason is
    handed it (`inspect.signature`), so the old tree answers rather than
    raising TypeError. The producer subprocess is planted: it records the call
    and writes the FAIL the real producer writes on an absent rtl/."""
    ran = []

    def _run(argv, **kw):
        ran.append(argv)
        out = project / argv[list(argv).index("--json") + 1]
        _write(out, {"verdict": "FAIL"})
        import subprocess
        return subprocess.CompletedProcess(argv, 1, "FAIL — --rtl-dir "
                                           "'phase2/stage1/rtl' does not "
                                           "exist", "")

    monkeypatch.setattr(D._pr, "run", _run)
    kw = ({"not_applicable": reason}
          if "not_applicable" in inspect.signature(
              D.step_fmeda_fault_injection).parameters else {})
    return D.step_fmeda_fault_injection(project, **kw), ran


def test_fs1_is_not_applicable_for_a_design_with_no_digital_rtl(
        tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    row, ran = _fs1(project, REASON, monkeypatch)
    assert row.status == "NOT_APPLICABLE", (row.status, row.detail)
    assert row.declared_by == REASON
    assert ran == [], "the producer ran against the by-design-absent rtl/"


def test_fs1_still_runs_its_producer_for_a_digital_design(tmp_path,
                                                          monkeypatch):
    """CONTROL: no reason (a digital design) -> the producer runs and its
    verdict stands, exactly as before."""
    project = tmp_path / "proj"
    project.mkdir()
    row, ran = _fs1(project, None, monkeypatch)
    # The current FS1 contract runs the flow-declared injection producer and
    # then the independent coverage checker before the canonical consumer.
    # Pin both calls and their order; counting only one was the old API shape.
    assert [Path(argv[1]).name for argv in ran] == [
        "fmeda_fault_injection_coverage.py",
        "fmeda_coverage_check.py",
    ]
    assert row.status == "FAIL", (row.status, row.detail)


def test_main_hands_fs1_the_same_analog_reason_it_hands_dft_lec_chain():
    """Wiring, read off the AST: the FS1 call in `main` passes the runner's own
    `_analog_rtl_track_absent` reason, the one `dft_lec_chain` receives."""
    src = (PROGRAMS / "design_one_shot_runner.py").read_text()
    main = next(n for n in ast.parse(src).body
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    calls = [n for n in ast.walk(main) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name)
             and n.func.id == "step_fmeda_fault_injection"]
    assert calls, "main no longer calls step_fmeda_fault_injection"
    kws = {k.arg: ast.unparse(k.value) for k in calls[0].keywords}
    assert "not_applicable" in kws, kws
    assert "_analog_reason" in kws["not_applicable"]
    assert "_analog_absent" in kws["not_applicable"]
