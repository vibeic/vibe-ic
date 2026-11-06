"""The declared step gates must reject a producer's damaged bytes."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from programs import flow_compliance_check as compliance
from _declared_design_inputs import consumes_declaration, declare_no_reuse

FLOW = Path(__file__).resolve().parents[2] / "flow/phase1_phase2_phase3.yaml"


def _write(root: Path, rel: str, value: str | dict) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, dict) else value)
    return path


def _steps() -> dict[str, dict]:
    doc = yaml.safe_load(FLOW.read_text())
    return {str(step["id"]): step for step in doc["steps"] if "id" in step}


CASES = {
    "1": ("phase2/stage1/rtl/top.v", "module top(); endmodule\n", ""),
    "14": ("phase2/stage2/synth/netlist.v", "module top(); endmodule\n", ""),
    "18": ("phase3/stage3/pnr/spare_cells.json", {
        "count": 2, "placed_cells_est": 50, "actual_density": 0.04,
        "tied_off": True,
        # the per-pin enumeration the insertion step prints (U6)
        "tie_off": {"tied_off": True, "inputs": [
            {"inst": "s0", "pin": "A", "use": "SIGNAL", "net": "t0"},
            {"inst": "s1", "pin": "CLK", "use": "CLOCK", "net": "t1"}]},
        "instances": [{"name": "s0", "cell": "INV", "llx": 0, "lly": 0, "keep": True},
                      {"name": "s1", "cell": "INV", "llx": 10, "lly": 10, "keep": True}]}, ""),
    "27": ("reports/phase3/si_crosstalk.json", {
        "max_crosstalk_noise": 0.02, "violations_count": 0}, ""),
    "32": ("phase3/stage3/postroute_timing_repair/postroute_timing_repair_decision.json",
           {"repair_needed": False}, ""),
    # U14: a screen whose density half resolved Step 34's verdict.
    "35": ("reports/phase3/dfm_screen.json",
           {"verdict": "PASS", "findings": [],
            "density_ref": {"source": "reports/phase2/gates/metal_fill_density.json",
                            "step34_pass": True, "errors": 0}}, ""),
    "P0": ("phase2/stage1/rtl/top.v", "module top(); endmodule\n", ""),
}


def _current_si_inputs(root: Path) -> None:
    """Author neutral content/identity fixtures, not native OpenSTA evidence.

    Keep the real current-input writer and both CLI readers. The script/log
    below are explicitly substituted transport, as in the existing current-SI
    source controls; no simulator, image identity or final verdict is mocked.
    """
    import _opensta_current as current
    from test_default_current_power import NETLIST, SPEF

    _write(root, "phase3/stage3/pnr/neutral_pnr.v", NETLIST)
    spef = _write(root, "phase3/stage3/extracted/neutral.spef", SPEF)
    _write(root, "phase3/stage3/pnr/constraint.sdc",
           "create_clock -name c -period 10\n")
    lib = _write(root, "input/pdk/neutral.lib", "library(neutral) {}\n")
    timing = _write(root, "phase3/stage3/extracted/neutral_si_timing.json",
                    {"pins": {"u0:Z": {"arr_rise_min": 1.0,
                                          "arr_rise_max": 1.2}}})
    script = root / "reports/phase3/si_source_fixture.tcl"
    log = script.with_suffix(".log")
    receipt = current.new_execution(
        current.basis(root, "neutral", [lib], coupling=True), "27", script, log,
        ["SOURCE_FIXTURE_ONLY", str(script)])
    marker = current.marker(receipt)
    _write(root, str(script.relative_to(root)),
           f"# SOURCE_FIXTURE_ONLY; no native execution\nputs {{{marker}}}\n")
    _write(root, str(log.relative_to(root)),
           f"SOURCE_FIXTURE_ONLY; substituted transport\n{marker}\n")
    current.finish(receipt, 0, [("timing_windows", timing)],
                   timing.with_suffix(".current.json"))
    receipt["inputs"] += [current.file_record(timing, "timing_windows", root),
        current.file_record(timing.with_suffix(".current.json"), "timing_receipt", root)]
    result = root / "reports/phase3/si_crosstalk.json"
    data = json.loads(result.read_text())
    data.update(spef=str(spef), timing_aware_advisory={
        "spef": str(spef), "timing_json": str(timing)})
    _write(root, str(result.relative_to(root)), data)
    report = _write(root, "reports/phase3/si_crosstalk.rpt",
                    "SOURCE_FIXTURE_ONLY content report\n")
    current.finish(receipt, 0, [("si_report", report), ("si_result", result)],
                   report.with_suffix(".current.json"))


def _declare_inputs(root: Path, step_id: str) -> None:
    """A step that declares D1's declaration as its input gets it (F27).

    Step 1 takes D1's outputs whole, and its catalog synth-safe gate (F9)
    reads its applicability from them and refuses a tree that has none. The
    case carries the no-reuse declaration a real run past D1 holds. The
    content clause is still the subject: the declaration is never the file
    that is damaged.
    """
    if consumes_declaration(_steps()[step_id]):
        declare_no_reuse(root)
    if step_id == "18":
        # Match the original two-cell/two-pin plan against the real DEF reader.
        _write(root, "phase3/stage3/pnr/post_spare.def", "\n".join([
            "VERSION 5.8 ;", "DESIGN neutral ;", "COMPONENTS 2 ;",
            "- s0 INV + FIXED ( 0 0 ) N ;", "- s1 INV + FIXED ( 10000 10000 ) N ;",
            "END COMPONENTS", "NETS 2 ;", "- t0 ( s0 A ) ;",
            "- t1 ( s1 CLK ) ;", "END NETS", "END DESIGN", ""]))
    elif step_id == "27":
        _current_si_inputs(root)


@pytest.mark.parametrize("step_id", CASES)
def test_real_gate_accepts_good_bytes_and_rejects_blank_output(tmp_path, step_id):
    rel, good, damaged = CASES[step_id]
    path = _write(tmp_path, rel, good)
    _declare_inputs(tmp_path, step_id)
    if step_id == "27":
        _write(tmp_path, "reports/phase3/si_mcf_sta.json", {
            "nominal": {"worst_setup_slack_ns": 1.0},
            "corners": {"setup": {"worst_slack_after_ns": 0.9}}})
    if step_id == "32":
        _write(tmp_path, "phase3/stage3/postroute_timing_repair/no_repair_needed.flag",
               "no repair required\n")
    gate = _steps()[step_id].get("gate")
    assert gate is not None, f"step {step_id} has no declared content gate"
    # Step 27 also runs an older optional MCF checker whose independent
    # SPEF inputs are absent from this content-only fixture. Exercise the new
    # blocking clauses themselves; its full flow path is covered separately.
    subject_gate = gate
    if step_id == "27":
        subject_gate = {"all_of": gate["all_of"][:2]}
    good_ok, good_reasons = compliance._evaluate_gate(tmp_path, subject_gate)
    assert good_ok, (step_id, good_reasons)
    path.write_text(damaged)
    bad_ok, bad_reasons = compliance._evaluate_gate(tmp_path, subject_gate)
    assert not bad_ok, (step_id, bad_reasons)


def test_step14_blocks_corrupt_declared_analog_report(tmp_path):
    _write(tmp_path, "phase1/analog/analog_block_list.json", {"blocks": []})
    report = _write(tmp_path, "reports/analog/stage_analog_compliance.json",
                    {"overall": "PASS"})
    gate = _steps()["14"]["gate"]
    clause = next(x for x in gate["all_of"] if x.get("program_exit_zero", "").endswith("--mode stage_analog"))
    assert compliance._evaluate_gate(tmp_path, clause)[0]
    report.write_text("{damaged")
    assert not compliance._evaluate_gate(tmp_path, clause)[0]
    report.unlink()
    assert not compliance._evaluate_gate(tmp_path, clause)[0]


@pytest.mark.parametrize("step_id", CASES)
def test_content_refusal_denies_the_owning_step_pass_tier(tmp_path, step_id):
    """Exercise the actual step judge with its canonical content clause.

    Keep corrupt files nonempty: a files_exist precondition must not be able
    to rescue this test when the content clause is removed.
    """
    rel, good, _ = CASES[step_id]
    path = _write(tmp_path, rel, good)
    _declare_inputs(tmp_path, step_id)
    step = _steps()[step_id]
    gate = step["gate"]
    if step_id == "27":
        # The SI content clause has independent SPEF/MCF siblings. Supply its
        # own real-shaped report and judge that clause at the owning step.
        _write(tmp_path, "reports/phase3/si_mcf_sta.json", {
            "nominal": {"worst_setup_slack_ns": 1.0},
            "corners": {"setup": {"worst_slack_after_ns": 0.9}}})
        gate = {"all_of": gate["all_of"][:2]}
    elif step_id == "32":
        _write(tmp_path,
               "phase3/stage3/postroute_timing_repair/no_repair_needed.flag",
               "no repair required\n")
    elif step_id == "14":
        gate = {"program_exit_zero": next(
            clause["program_exit_zero"] for clause in gate["all_of"]
            if clause.get("program_exit_zero", "").endswith("--mode netlist"))}
    subject = {"id": step_id, "name": step["name"],
               "stage": step["stage"], "required_outputs": [rel],
               "gate": gate}
    healthy = compliance.check_step(tmp_path, subject, {})
    assert healthy.status == "PASS", (step_id, healthy.reasons)
    path.write_text("module top(\n" if step_id in {"1", "14", "P0"}
                    else "{}")
    broken = compliance.check_step(tmp_path, subject, {})
    assert broken.status == "FAIL", (step_id, broken.reasons)
    path.unlink()
    absent = compliance.check_step(tmp_path, subject, {})
    assert absent.status in {"FAIL", "NOT_MEASURED"}, (step_id, absent.reasons)


def test_step1_case_is_judged_on_its_declaration(tmp_path):
    """F27: the step-1 case reaches PASS through the catalog gate's reading of
    the seeded declaration (no reuse -> DESIGN_DECLARED_NA), not around it.
    Without the declaration the same tree is refused, never N/A."""
    rel, good, _ = CASES["1"]
    _write(tmp_path, rel, good)
    step = _steps()["1"]
    assert consumes_declaration(step)
    declared = declare_no_reuse(tmp_path)
    report = tmp_path / "reports/phase2/gates/catalog_synth_safe_params.json"
    seeded = compliance.check_step(tmp_path, step, {})
    gate = json.loads(report.read_text())
    assert (gate["verdict"], gate.get("reason_class")) == (
        "NOT_APPLICABLE", "DESIGN_DECLARED_NA"), gate
    assert gate["declaration"]["declared_catalog_reuse"] == []
    assert seeded.status == "PASS", seeded.reasons
    assert any("stated_class=DESIGN_DECLARED_NA" in r
               for r in seeded.reasons), seeded.reasons
    # The second run's receipt is redirected (the report already exists), so
    # its verdict is read from the step's own reasons, not the stale file.
    declared.unlink()
    unread = compliance.check_step(tmp_path, step, {})
    assert unread.status == "FAIL", unread.reasons
    assert any("[NOT_MEASURED] catalog_synth_safe_params_check: declaration "
               "missing" in r for r in unread.reasons), unread.reasons




@pytest.mark.parametrize("step_id,commands", [
    ("1", ("flow_step_output_content_check . --mode rtl",)),
    ("14", ("flow_step_output_content_check . --mode netlist",
            "flow_step_output_content_check . --mode stage_analog")),
    ("18", ("spare_cell_coverage_check . --post-spare-def --json reports/phase2/gates/spare_cell_coverage.json",)),
    ("27", ("flow_step_output_content_check . --mode si",)),
    ("32", ("flow_step_output_content_check . --mode repair",)),
    ("35", ("flow_step_output_content_check . --mode dfm",)),
    ("P0", ("flow_step_output_content_check . --mode rtl",)),
])
def test_each_content_clause_is_required_by_its_own_step(step_id, commands):
    gate = _steps()[step_id]["gate"]
    clauses = gate.get("all_of", [gate])
    required = {spec.get("command") if isinstance(spec, dict) else spec
                for clause in clauses
                if (spec := clause.get("program_exit_zero")) is not None}
    assert set(commands) <= required, (step_id, required)


@pytest.mark.parametrize("step_id", ("1", "14", "18", "27", "32", "35", "P0"))
def test_each_listed_step_declares_a_blocking_content_program(step_id):
    step = _steps()[step_id]
    def commands(gate):
        if isinstance(gate, dict):
            if "program_exit_zero" in gate:
                yield gate["program_exit_zero"]
            for key in ("all_of", "any_of"):
                for sub in gate.get(key, []) if isinstance(gate.get(key), list) else []:
                    yield from commands(sub)
    assert list(commands(step.get("gate"))), step_id


@pytest.mark.parametrize("step_id", (
    "40", "41", "42", "43", "44", "A1", "A2", "A3", "A4", "A5",
    "A6", "A7", "A8", "A9", "DT1", "FS1", "M1", "M2", "M3", "M4"))
def test_each_existing_condition_has_a_reviewed_kind(step_id):
    expected = "setup_required" if step_id == "FS1" else "design_dependent"
    step = _steps()[step_id]
    assert step.get("condition")
    assert step.get("condition_kind") == expected
