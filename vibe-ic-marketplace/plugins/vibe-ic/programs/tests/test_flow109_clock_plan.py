import json

import flow109
import flow109_clock_plan as clock


def _profile():
    return next(item["features"] for item in flow109.load_registry()["reference_profiles"]
                if item["name"] == "Small digital IC without DFT")


def test_missing_sdc_refuses_before_clock_native_launch(tmp_path):
    floorplan = tmp_path / "phase3/stage3/pnr/floorplan.def"
    floorplan.parent.mkdir(parents=True)
    floorplan.write_text("VERSION 5.8 ;\nDESIGN chip_top ;\nEND DESIGN\n")
    pdk = tmp_path / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
    pdk.parent.mkdir(parents=True)
    pdk.write_text(json.dumps({"fields": {"pdk_target": "gf180mcuD"}}))
    plan = flow109.resolve_plan(_profile())
    context = flow109.execution_context(plan, "D34", "D34")

    result = clock.execute(tmp_path, context)

    assert result["component_status"] == "NOT_MEASURED"
    assert result["reason"] == "D34_SDC_ABSENT"
    assert result["native_started"] is False
    assert result["flow109_acceptance"] == "NOT_MEASURED"
    assert not (tmp_path / clock.OUTPUT).exists()


# --- D34 metric binding: sink inventory reconciliation and planning targets ---

import hashlib
import uuid

import pytest

import _physical_current as current
import flow109_admission

LIBERTY = """
library (demo) {
  cell (DFF) { pin (CLK) { clock : true; } ff (IQ, IQN) { clocked_on : "CLK"; next_state : "D"; } }
  cell (DFFN) { ff (IQ, IQN) { clocked_on : "!CLKN"; next_state : "D"; } }
  cell (LAT) { latch (IQ, IQN) { enable : "E"; data_in : "D"; } }
  cell (INV) { pin (A) { direction : input; } }
}
"""
DEF = """VERSION 5.8 ;
DESIGN chip_top ;
COMPONENTS 4 ;
    - u_core/r\\[0\\] DFF + PLACED ( 0 0 ) N ;
    - u_core/r\\[1\\] DFFN + PLACED ( 0 0 ) N ;
    - u_core/l0 LAT + PLACED ( 0 0 ) N ;
    - u_core/i0 INV + PLACED ( 0 0 ) N ;
END COMPONENTS
END DESIGN
"""
SINKS = ["u_core/l0/E", "u_core/r[0]/CLK", "u_core/r[1]/CLKN"]


def _write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if isinstance(body, str) else json.dumps(body, sort_keys=True))
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _rel(project, path):
    return {"path": str(path.relative_to(project)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _log(sinks):
    lines = [f"CLOCK_PLAN_SINK clk|{pin}" for pin in sinks]
    return "\n".join(["CLOCK_PLAN_NATIVE clk|24.0|clk", *lines,
                      f"CLOCK_PLAN_SINK_COUNT clk|{len(sinks)}", "CLOCK_PLAN_DONE", ""])


def _approved(project, relative, schema, payload, source):
    body = {"schema": schema, **payload, "approval": {
        "authority": "requirements_owner", "status": "APPROVED",
        "source_reference": _rel(project, project / source)}}
    _write(project / relative, body)


def _d34_case(tmp_path, monkeypatch, *, reference=SINKS, skew=2.4, approval=True):
    project = tmp_path
    log = project / "phase3/stage3/cts/clock_plan.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(_log(SINKS))
    plan = {"tool": "openroad", "primary_clock": "clk",
            "clocks": [{"name": "clk", "period_ns": 24.0, "source": "clk"}],
            "current": {"schema": current.SCHEMA, "step": "16", "stage": "stage3",
                        "design": "chip_top", "pdk": "demo", "tool": "openroad",
                        "inputs": {"floorplan": {"path": "phase3/stage3/pnr/floorplan.def",
                                                 "sha256": "0" * 64, "bytes": 1}},
                        "outputs": {"log": _rel(project, log)},
                        "execution": {"rc": 0, "argv": ["openroad", "-exit", "clock_plan.tcl"]}},
            "sinks": {"clk": SINKS},
            "sink_census": {"method": current.CLOCK_SINK_METHOD, "counts": {"clk": len(SINKS)}}}
    plan_path = project / clock.OUTPUT
    _write(plan_path, plan)
    targets = project / clock.PLANNING_TARGETS
    _write(targets, {"schema": "vibeic.flow109.clock-planning-targets.v1",
                     "targets": {"clock_skew_ns": skew, "insertion_delay_ns": 12.0},
                     "units": {"clock_skew_ns": "ns", "insertion_delay_ns": "ns"}})
    _write(project / "input/flow109/D34/requirement_source.json", {"basis": "owner-approved planning bound"})
    _approved(project, clock.TARGET_BOUNDS, "vibeic.flow109.requirement-authority.v1",
              {"limits": {"clock_skew_ns": {"max": 2.4}, "insertion_delay_ns": {"max": 12.0}},
               "units": {"clock_skew_ns": "ns", "insertion_delay_ns": "ns"}},
              "input/flow109/D34/requirement_source.json")
    identity = {"producer": {"name": "structural"}, "checker": {"m": "x"},
                "tool_execution": {"program": "propose"}, "consumed_inputs": {"def": "1" * 64},
                "requirements": {"obligation": "base_22.clock_sink_inventory"},
                "configuration": {"sinks": len(reference)}}
    payload = {"reference": reference, "reference_identity": identity}
    _write(project / clock.SINK_SOURCE, {"clock_sink_inventory": payload})
    if approval:
        _approved(project, clock.SINK_REFERENCE, "vibeic.flow109.adopted-reference.v1",
                  payload, clock.SINK_SOURCE)
    for step in ("D20", "D32"):
        _write(project / f"reports/flow109/default_rows/{step}.json",
               {"step_id": step, "default_row_status": "PASS", "completed": True})
    config = project / "reports/flow109/qualification/D34.json"
    _write(config, {"purpose": clock.D34_PURPOSE, "model_sources": clock.d34_model_sources()})
    context = flow109.execution_context(flow109.resolve_plan(_profile()), "D34", "D34")
    context = {**context, "runtime_tool_uses": [{"use_id": "flow109.D34.default.openroad",
                                                 "config": {"path": str(config.relative_to(project))}}]}
    monkeypatch.setattr(flow109, "validate_execution_context", lambda ctx: ctx)
    monkeypatch.setattr(flow109_admission, "require_admission", lambda p, c: {"status": "PASS"})
    monkeypatch.setattr(current, "validate", lambda *a, **k: "")
    record = {"schema": clock.SCHEMA, "step_id": "D34", "component_status": "PASS",
              "context_sha256": context["context_sha256"],
              "outputs": {clock.OUTPUT: hashlib.sha256(plan_path.read_bytes()).hexdigest()},
              "planning_targets": _rel(project, targets)}
    component = project / "reports/flow109/D34" / uuid.uuid4().hex / "component.json"
    _write(component, record)
    return project, context, {**record, "component_record": _rel(project, component)}


def test_clock_plan_sinks_closes_the_census_or_refuses():
    assert current.clock_plan_sinks(_log(SINKS), ["clk"]) == {"clk": SINKS}
    with pytest.raises(ValueError, match="CLOCK_PLAN_SINK_CENSUS_INCOMPLETE"):
        current.clock_plan_sinks(_log(SINKS).replace("SINK_COUNT clk|3", "SINK_COUNT clk|4"), ["clk"])
    with pytest.raises(ValueError, match="CLOCK_PLAN_SINK_CENSUS_INCOMPLETE"):
        current.clock_plan_sinks("CLOCK_PLAN_SINK clk|a/CLK\n", ["clk"])


def test_structural_census_reads_liberty_groups_not_cell_names():
    pins = clock.liberty_clock_pins(LIBERTY)
    assert pins == {"DFF": "CLK", "DFFN": "CLKN", "LAT": "E"}
    assert clock.structural_sinks(DEF, pins) == SINKS
    with pytest.raises(ValueError, match="D34_LIBERTY_CLOCK_EXPRESSION_UNSUPPORTED"):
        clock.liberty_clock_pins('cell (G) { ff (Q, QN) { clocked_on : "CLK & EN"; } }')
    with pytest.raises(ValueError, match="D34_LIBERTY_BANK_UNSUPPORTED"):
        clock.liberty_clock_pins('cell (B) { ff_bank (Q, QN, 2) { clocked_on : "CLK"; } }')


def test_d34_passes_when_both_methods_and_targets_agree(tmp_path, monkeypatch):
    project, context, component = _d34_case(tmp_path, monkeypatch)
    result = clock.consume_default_row_completion(project, context, component)
    assert result["default_row_status"] == "PASS" and result["completed"] is True
    assert [o["status"] for o in result["metric_acceptance"]["obligations"]] == ["PASS", "PASS"]


def test_d34_fails_on_a_register_the_clock_does_not_reach(tmp_path, monkeypatch):
    project, context, component = _d34_case(tmp_path, monkeypatch,
                                            reference=[*SINKS, "u_core/r[2]/CLK"])
    result = clock.consume_default_row_completion(project, context, component)
    sinks = result["metric_acceptance"]["obligations"][0]
    assert result["default_row_status"] == "FAIL"
    assert sinks["status"] == "FAIL" and sinks["unreached_sinks"] == ["u_core/r[2]/CLK"]


def test_d34_fails_on_a_planning_target_beyond_its_bound(tmp_path, monkeypatch):
    project, context, component = _d34_case(tmp_path, monkeypatch, skew=2.5)
    result = clock.consume_default_row_completion(project, context, component)
    assert result["default_row_status"] == "FAIL"
    assert result["metric_acceptance"]["obligations"][1]["checks"]["clock_skew_ns"]["status"] == "FAIL"


def test_d34_unapproved_reference_is_not_measured(tmp_path, monkeypatch):
    project, context, component = _d34_case(tmp_path, monkeypatch, approval=False)
    result = clock.consume_default_row_completion(project, context, component)
    assert result["default_row_status"] == "NOT_MEASURED"
    assert result["metric_acceptance"]["reason"] == "METRIC_AUTHORITY_ABSENT"


def test_d34_refuses_a_plan_changed_after_the_component(tmp_path, monkeypatch):
    project, context, component = _d34_case(tmp_path, monkeypatch)
    plan = project / clock.OUTPUT
    plan.write_text(plan.read_text().replace('"period_ns": 24.0', '"period_ns": 25.0'))
    result = clock.consume_default_row_completion(project, context, component)
    assert result["default_row_status"] == "NOT_MEASURED"
    assert result["metric_acceptance"]["reason"] == "D34_PLAN_STALE"


def test_d34_measurement_is_the_native_log_not_the_json_summary(tmp_path, monkeypatch):
    project, context, component = _d34_case(tmp_path, monkeypatch)
    log = project / "phase3/stage3/cts/clock_plan.log"
    log.write_text(_log(SINKS[:2]))
    result = clock.consume_default_row_completion(project, context, component)
    assert result["default_row_status"] == "NOT_MEASURED"
    assert result["metric_acceptance"]["reason"] == "D34_SINK_CENSUS_DIFFERS_FROM_LOG"
