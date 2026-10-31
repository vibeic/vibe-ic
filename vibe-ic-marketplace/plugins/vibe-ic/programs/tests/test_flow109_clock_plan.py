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


# --- D34 metric binding: per-clock sink reconciliation and planning targets ---

import hashlib
import uuid

import pytest

import _physical_current as current
import flow109_admission

LIBERTY = """
library (demo) {
  cell (DFF) { pin (CLK) { direction : input; clock : true; }
               pin (D) { direction : input; } pin (Q) { direction : output; }
               ff (IQ, IQN) { clocked_on : "CLK"; next_state : "D"; } }
  cell (DFFN) { pin (CLKN) { direction : input; clock : true; }
                pin (D) { direction : input; } pin (Q) { direction : output; }
                ff (IQ, IQN) { clocked_on : "!CLKN"; next_state : "D"; } }
  cell (LAT) { pin (E) { direction : input; } pin (D) { direction : input; }
               pin (Q) { direction : output; } latch (IQ, IQN) { enable : "E"; data_in : "D"; } }
  cell (BUF) { pin (A) { direction : input; timing () { related_pin : "A"; } }
               pin (Z) { direction : output; } }
  cell (PADIN) { pin (PAD) { direction : input; is_pad : true; } pin (PU) { direction : input; }
                 pin (Y) { direction : output; } }
  cell (AND2) { pin (A) { direction : input; } pin (B) { direction : input; }
                pin (Z) { direction : output; } }
}
"""


def _def(clock_b_driver="( PIN clkb )", extra=""):
    return f"""VERSION 5.8 ;
DESIGN chip_top ;
COMPONENTS 6 ;
    - u_pad PADIN + PLACED ( 0 0 ) N ;
    - u_buf BUF + PLACED ( 0 0 ) N ;
    - u_core/r\\[0\\] DFF + PLACED ( 0 0 ) N ;
    - u_core/r\\[1\\] DFFN + PLACED ( 0 0 ) N ;
    - u_core/l0 LAT + PLACED ( 0 0 ) N ;
    - u_and AND2 + PLACED ( 0 0 ) N ;
END COMPONENTS
PINS 3 ;
    - clka + NET clka + DIRECTION INPUT + USE SIGNAL ;
    - clkb + NET clkb + DIRECTION INPUT + USE SIGNAL ;
    - en + NET en + DIRECTION INPUT + USE SIGNAL ;
END PINS
NETS 5 ;
    - clka ( PIN clka ) ( u_pad PAD ) ;
    - ca ( u_pad Y ) ( u_buf A ) ;
    - cka ( u_buf Z ) ( u_core/r\\[0\\] CLK ) ( u_core/l0 E ) ;
    - clkb {clock_b_driver} ( u_core/r\\[1\\] CLKN ) ;
    - en ( PIN en ) ( u_and B ) ;{extra}
END NETS
END DESIGN
"""


SOURCES = {"clka": "clka", "clkb": "clkb"}
DOMAINS = {"clka": ["u_core/l0/E", "u_core/r[0]/CLK"], "clkb": ["u_core/r[1]/CLKN"]}


def _trace(def_text):
    return clock.structural_clock_domains(def_text, clock.liberty_clock_pins(LIBERTY),
                                          clock.liberty_pin_roles(LIBERTY), SOURCES)


def _write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if isinstance(body, str) else json.dumps(body, sort_keys=True))


def _rel(project, path):
    return {"path": str(path.relative_to(project)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _log(domains):
    lines = ["CLOCK_PLAN_NATIVE clka|24.0|clka", "CLOCK_PLAN_NATIVE clkb|24.0|clkb"]
    for name, pins in domains.items():
        lines += [f"CLOCK_PLAN_SINK {name}|{pin}" for pin in pins]
        lines.append(f"CLOCK_PLAN_SINK_COUNT {name}|{len(pins)}")
    return "\n".join([*lines, "CLOCK_PLAN_DONE", ""])


def _approved(project, relative, schema, payload, source):
    _write(project / relative, {"schema": schema, **payload, "approval": {
        "authority": "requirements_owner", "status": "APPROVED",
        "source_reference": _rel(project, project / source)}})


def _d34_case(tmp_path, monkeypatch, *, measured=DOMAINS, reference=None, skew=2.4, approval=True):
    project = tmp_path
    log = project / "phase3/stage3/cts/clock_plan.log"
    _write(log, _log(measured))
    plan_path = project / clock.OUTPUT
    _write(plan_path, {
        "tool": "openroad", "primary_clock": "clka",
        "clocks": [{"name": n, "period_ns": 24.0, "source": n} for n in ("clka", "clkb")],
        "current": {"schema": current.SCHEMA, "step": "16", "stage": "stage3",
                    "design": "chip_top", "pdk": "demo", "tool": "openroad",
                    "inputs": {"floorplan": {"path": "phase3/stage3/pnr/floorplan.def",
                                             "sha256": "0" * 64, "bytes": 1}},
                    "outputs": {"log": _rel(project, log)},
                    "execution": {"rc": 0, "argv": ["openroad", "-exit", "clock_plan.tcl"]}},
        "sinks": measured,
        "sink_census": {"method": current.CLOCK_SINK_METHOD,
                        "counts": {n: len(p) for n, p in measured.items()}}})
    targets = project / clock.PLANNING_TARGETS
    _write(targets, {"targets": {"clock_skew_ns": skew, "insertion_delay_ns": 12.0},
                     "units": {"clock_skew_ns": "ns", "insertion_delay_ns": "ns"}})
    _write(project / "input/flow109/D34/requirement_source.json", {"basis": "owner-approved planning bound"})
    _approved(project, clock.TARGET_BOUNDS, "vibeic.flow109.requirement-authority.v1",
              {"limits": {"clock_skew_ns": {"max": 2.4}, "insertion_delay_ns": {"max": 12.0}},
               "units": {"clock_skew_ns": "ns", "insertion_delay_ns": "ns"}},
              "input/flow109/D34/requirement_source.json")
    payload = {"reference": reference or {"clocks": DOMAINS, "unclocked": []}, "reference_identity": {
        "producer": {"name": "structural"}, "checker": {"m": "x"}, "tool_execution": {"program": "propose"},
        "consumed_inputs": {"def": "1" * 64}, "requirements": {"obligation": "base_22.clock_sink_inventory"},
        "configuration": {"clocks": ["clka", "clkb"]}}}
    _write(project / clock.SINK_SOURCE, {"clock_sink_inventory": payload})
    if approval:
        _approved(project, clock.SINK_REFERENCE, "vibeic.flow109.adopted-reference.v1",
                  payload, clock.SINK_SOURCE)
    context = flow109.execution_context(flow109.resolve_plan(_profile()), "D34", "D34")
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


def _complete(tmp_path, monkeypatch, **case):
    project, context, component = _d34_case(tmp_path, monkeypatch, **case)
    result = clock.consume_default_row_completion(project, context, component)
    return result, {o["id"]: o for o in result.get("metric_acceptance", {}).get("obligations", [])}


def test_clock_plan_sinks_closes_the_census_or_refuses():
    assert current.clock_plan_sinks(_log(DOMAINS), ["clka", "clkb"]) == DOMAINS
    with pytest.raises(ValueError, match="CLOCK_PLAN_SINK_CENSUS_INCOMPLETE"):
        current.clock_plan_sinks(_log(DOMAINS).replace("SINK_COUNT clka|2", "SINK_COUNT clka|3"),
                                 ["clka", "clkb"])
    with pytest.raises(ValueError, match="CLOCK_PLAN_SINK_CENSUS_INCOMPLETE"):
        current.clock_plan_sinks("CLOCK_PLAN_SINK clka|a/CLK\n", ["clka"])


def test_liberty_declarations_decide_sequential_cells_and_pin_roles():
    assert clock.liberty_clock_pins(LIBERTY) == {"DFF": "CLK", "DFFN": "CLKN", "LAT": "E"}
    roles = clock.liberty_pin_roles(LIBERTY)
    assert roles["PADIN"]["PAD"] == {"direction": "input", "clock": False, "is_pad": True}
    assert roles["BUF"]["A"]["direction"] == "input" and roles["BUF"]["Z"]["direction"] == "output"
    with pytest.raises(ValueError, match="D34_LIBERTY_CLOCK_EXPRESSION_UNSUPPORTED"):
        clock.liberty_clock_pins('cell (G) { ff (Q, QN) { clocked_on : "CLK & EN"; } }')
    with pytest.raises(ValueError, match="D34_LIBERTY_BANK_UNSUPPORTED"):
        clock.liberty_clock_pins('cell (B) { ff_bank (Q, QN, 2) { clocked_on : "CLK"; } }')


def test_structural_trace_assigns_each_sink_through_pads_and_buffers_to_its_clock():
    assert _trace(_def()) == {"clocks": DOMAINS, "unclocked": []}


def test_structural_trace_reports_a_clock_pin_without_driver_as_unclocked():
    traced = _trace(_def(clock_b_driver=""))
    assert traced["unclocked"] == ["u_core/r[1]/CLKN"] and traced["clocks"]["clkb"] == []


def test_structural_trace_refuses_a_path_it_cannot_decide():
    gated = _def(clock_b_driver="( u_and Z )", extra="\n    - ckb_in ( PIN clkb ) ( u_and A ) ;")
    with pytest.raises(ValueError, match="D34_CLOCK_TRACE_UNRESOLVED"):
        _trace(gated)


def test_d34_sinks_reconcile_but_unconsumed_targets_stay_unmeasured(tmp_path, monkeypatch):
    result, obligations = _complete(tmp_path, monkeypatch)
    assert obligations["base_22.clock_sink_inventory"]["status"] == "PASS"
    targets = obligations["base_22.skew_insertion_targets"]
    assert targets["status"] == "NOT_MEASURED" and targets["reason"] == "D34_TARGET_CONSUMPTION_UNSUPPORTED"
    assert result["default_row_status"] == "NOT_MEASURED" and result["completed"] is False


def test_d34_fails_when_two_clocks_reach_each_others_sinks(tmp_path, monkeypatch):
    swapped = {"clka": ["u_core/r[1]/CLKN"], "clkb": ["u_core/l0/E", "u_core/r[0]/CLK"]}
    result, obligations = _complete(tmp_path, monkeypatch, measured=swapped)
    sinks = obligations["base_22.clock_sink_inventory"]
    assert result["default_row_status"] == "FAIL" and sinks["status"] == "FAIL"
    assert sinks["unreached_sinks"]["clka"] == ["u_core/l0/E", "u_core/r[0]/CLK"]


def test_d34_fails_on_a_required_sink_no_clock_reaches(tmp_path, monkeypatch):
    reference = {"clocks": {"clka": DOMAINS["clka"], "clkb": []}, "unclocked": ["u_core/r[1]/CLKN"]}
    measured = {"clka": DOMAINS["clka"], "clkb": []}
    result, obligations = _complete(tmp_path, monkeypatch, measured=measured, reference=reference)
    sinks = obligations["base_22.clock_sink_inventory"]
    assert result["default_row_status"] == "FAIL"
    assert sinks["status"] == "FAIL" and sinks["unclocked_required_sinks"] == ["u_core/r[1]/CLKN"]


def test_d34_fails_on_a_planning_target_beyond_its_bound(tmp_path, monkeypatch):
    result, obligations = _complete(tmp_path, monkeypatch, skew=2.5)
    targets = obligations["base_22.skew_insertion_targets"]
    assert result["default_row_status"] == "FAIL"
    assert targets["reason"] == "D34_PLANNING_TARGET_EXCEEDS_BOUND"
    assert targets["checks"]["clock_skew_ns"]["status"] == "FAIL"


def test_d34_unapproved_reference_is_not_measured(tmp_path, monkeypatch):
    result, _ = _complete(tmp_path, monkeypatch, approval=False)
    assert result["default_row_status"] == "NOT_MEASURED"
    assert result["metric_acceptance"]["reason"] == "METRIC_AUTHORITY_ABSENT"


def test_d34_refuses_a_plan_changed_after_the_component(tmp_path, monkeypatch):
    project, context, component = _d34_case(tmp_path, monkeypatch)
    plan = project / clock.OUTPUT
    plan.write_text(plan.read_text().replace('"period_ns": 24.0', '"period_ns": 25.0', 1))
    result = clock.consume_default_row_completion(project, context, component)
    assert result["default_row_status"] == "NOT_MEASURED"
    assert result["metric_acceptance"]["reason"] == "D34_PLAN_STALE"


def test_d34_measurement_is_the_native_log_not_the_json_summary(tmp_path, monkeypatch):
    project, context, component = _d34_case(tmp_path, monkeypatch)
    (project / "phase3/stage3/cts/clock_plan.log").write_text(_log({"clka": ["u_core/r[0]/CLK"], "clkb": []}))
    result = clock.consume_default_row_completion(project, context, component)
    assert result["default_row_status"] == "NOT_MEASURED"
    assert result["metric_acceptance"]["reason"] == "D34_SINK_CENSUS_DIFFERS_FROM_LOG"
