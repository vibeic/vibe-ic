from decimal import Decimal
import json
from types import SimpleNamespace

import pytest

from flow_pdn_recovery import Wire, RecoveryPlan, finish_replay, measured_settings, plan_recovery, printed_bound, _wires


class Tech:
    def getManufacturingGrid(self): return 5
    def getDbUnitsPerMicron(self): return 1000
    def findLayer(self, name):
        return SimpleNamespace(getSpacing=lambda *args: 300, findTwSpacing=lambda *args: 300)


def config():
    result = {"VDD_NETS": ["power"], "GND_NETS": ["ground"], "PDN_CORE_RING": True,
              "PDN_VERTICAL_LAYER": "vertical", "PDN_HORIZONTAL_LAYER": "horizontal"}
    for axis in ("V", "H"):
        for suffix, value in (("WIDTH", 1.6), ("SPACING", 1.7), ("PITCH", 160), ("OFFSET", 7)):
            result[f"PDN_{axis}{suffix}"] = value
        result[f"PDN_CORE_RING_{axis}WIDTH"] = 1.6
        result[f"PDN_CORE_RING_{axis}SPACING"] = 1.7
    return result


def hotspot(layer="vertical", current="1.100e-03", area="1.0000e+00"):
    return {"Layer": layer, "Node0 X": "0", "Node0 Y": "0", "Node1 X": "0", "Node1 Y": "5",
            "Current(A)": current, "Area(um^2)": area, "Basis": "AREAL", "Cuts": "0", "Status": "VIOLATED"}


def test_printed_current_and_area_bounds_follow_actual_decimal_precision():
    assert printed_bound("1.100e-03", True) == Decimal("0.0011005")
    assert printed_bound("1.0000e+00", False) == Decimal("0.99995")


def test_measured_strap_width_and_ring_follow_exact_capacity_without_margin():
    plan = measured_settings(config(), [hotspot()], Tech(), {"vertical": Decimal(".001")},
        [Wire("vertical", "PDN_VWIDTH", (-1, -1, 1, 6))], {"vertical": {"thickness_um": .54}})
    assert plan.settings["PDN_VWIDTH"] == 2.04
    assert plan.settings["PDN_CORE_RING_VWIDTH"] == 2.04
    assert plan.settings["PDN_VOFFSET"] == 7.22
    assert "PDN_RAIL_WIDTH" not in plan.settings


def test_measured_rail_overload_reduces_pitch_without_changing_cell_rail_width():
    plan = measured_settings(config(), [hotspot("rail")], Tech(), {"rail": Decimal(".001")},
        [Wire("rail", "rail", (-1, -1, 1, 6))], {"rail": {"thickness_um": .54}})
    assert plan.settings == {"PDN_VPITCH": 80, "PDN_HPITCH": 80}


def test_native_resistor_between_separate_fixed_pin_regions_remains_a_rail_actuator():
    plan = measured_settings(config(), [hotspot("rail")], Tech(), {"rail": Decimal(".001")},
        [Wire("rail", "rail", (-1, -1, 1, 1)), Wire("rail", "rail", (-1, 4, 1, 6))],
        {"rail": {"thickness_um": .54}})
    assert plan.settings == {"PDN_VPITCH": 80, "PDN_HPITCH": 80}


@pytest.mark.parametrize("wires,basis", [([], "AREAL"),
    ([Wire("vertical", "PDN_VWIDTH", (-1, -1, 1, 6)), Wire("vertical", "rail", (-1, -1, 1, 6))], "AREAL"),
    ([Wire("vertical", "PDN_VWIDTH", (-1, -1, 1, 6))], "PER_CUT")])
def test_unsupported_or_ambiguous_fixed_conductors_keep_original_failure(wires, basis):
    row = {**hotspot(), "Basis": basis}
    assert measured_settings(config(), [row], Tech(), {"vertical": Decimal(".001")},
                             wires, {"vertical": {"thickness_um": .54}}) is None


def test_other_blocking_step_prevents_recovery_without_reading_native_files(tmp_path):
    summary = {"steps": [{"name": "candidate_electromigration", "status": "FAIL"},
                         {"name": "candidate_timing", "status": "NOT_MEASURED"}]}
    assert plan_recovery(tmp_path, {"delivery_target": "ip_hardmacro"}, summary) is None


def test_public_entry_performs_one_replay_even_when_second_em_fails(tmp_path, monkeypatch):
    import sys
    import flow_engine
    import flow_engine_frontend as frontend
    import flow_pdn_current
    import flow_pdn_recovery
    calls, plans = [], []
    names = ["die_floorplan_and_macros", "candidate_electromigration"]
    def run(project, **kwargs):
        calls.append(kwargs)
        return {"steps": [{"name": names[-1], "status": "FAIL"}], "selected_names": names,
                "fail": 1, "not_measured": 0, "completed_at": 20, "common_wall_seconds": 10}
    monkeypatch.setattr(flow_pdn_current, "needs_estimate", lambda *args: False)
    def plan(*args):
        plans.append(args)
        return RecoveryPlan({"PDN_VPITCH": 80}, ())
    monkeypatch.setattr(flow_pdn_recovery, "plan_recovery", plan)
    monkeypatch.setattr(flow_pdn_recovery, "apply_plan", lambda *args: tmp_path / "archive")
    monkeypatch.setattr(flow_pdn_recovery, "finish_replay", lambda project, first, final, archive, **kwargs: final)
    monkeypatch.setitem(sys.modules, "flow_engine", SimpleNamespace(run=run, TABLE=flow_engine.TABLE))
    args = SimpleNamespace(project=tmp_path, entry_step="requirements_and_delivery_route",
        exit_step="candidate_electromigration", rtl_input="structured", delivery_target="ip_hardmacro",
        route="ip", pdk="auto", from_name=None)
    assert frontend.run_public(args) == 1
    assert len(calls) == 2
    assert len(plans) == 1
    assert calls[1]["from_name"] == "die_floorplan_and_macros"


def test_public_prepass_preserves_historical_native_clock_on_retained_run(tmp_path, monkeypatch):
    import sys
    import flow_engine
    import flow_engine_frontend as frontend
    import flow_pdn_current
    reports = []
    def run(project, **kwargs):
        if kwargs.get("to_name"):
            return {"native_common_started_at": 100, "common_wall_seconds": 5}
        return {"fail": 0}
    monkeypatch.setattr(flow_pdn_current, "needs_estimate", lambda *args: True)
    monkeypatch.setattr(frontend, "time", SimpleNamespace(time=lambda: 200, perf_counter=lambda: 2000))
    monkeypatch.setitem(sys.modules, "flow_engine", SimpleNamespace(run=run, TABLE=flow_engine.TABLE,
        write_json=lambda path, report: reports.append(dict(report))))
    args = SimpleNamespace(project=tmp_path, entry_step="requirements_and_delivery_route",
        exit_step="candidate_electromigration", rtl_input="structured", delivery_target="ip_hardmacro",
        route="ip", pdk="auto", from_name=None)
    assert frontend.run_public(args) == 0
    assert reports[-1]["common_wall_seconds"] == 100
    assert reports[-1]["native_common_started_at"] == 100


@pytest.mark.parametrize("native_epoch", [False, True])
def test_actual_retained_engine_cannot_erase_original_public_clock(tmp_path, monkeypatch, native_epoch):
    import flow_engine
    import flow_engine_frontend as frontend
    from test_flow_engine import command_row
    names = ["pre_layout_timing", "die_floorplan_and_macros", "candidate_electromigration"]
    rows = [command_row(name) for name in names]
    for row in rows:
        row["tool"]["timing_group"] = "librelane"
    table = tmp_path / "steps.json"
    table.write_text(json.dumps({"steps": rows}))
    monkeypatch.setattr(flow_engine, "TABLE", table)
    route = {"entry_step": names[0], "verify_through": names[-1],
             "delivery_target": "ip_hardmacro", "input_contract": "structured"}
    flow_engine.run(tmp_path, route=route)
    first = tmp_path / "steps" / names[0] / "result.json"
    saved = json.loads(first.read_text())
    saved.update(started_at=100, completed_at=101)
    if native_epoch:
        saved["native_common_started_at"] = 100
    first.write_text(json.dumps(saved))
    args = SimpleNamespace(project=tmp_path, entry_step=names[0], exit_step=names[-1],
        rtl_input="structured", delivery_target="ip_hardmacro", route="ip", pdk="auto", from_name=None)
    assert frontend.run_public(args) == 0
    retained = json.loads(first.read_text())
    assert retained["retained"]
    assert "native_common_started_at" not in retained
    report = json.loads((tmp_path / "reports/flow_engine.json").read_text())
    assert report["native_common_started_at"] == 100
    assert report["common_wall_seconds"] > 100


def test_actual_floorplan_resume_keeps_failed_attempt_execution_times(tmp_path, monkeypatch):
    import flow_engine
    import flow_engine_frontend as frontend
    from test_flow_engine import command_row
    names = ["pre_layout_timing", "die_floorplan_and_macros", "candidate_electromigration"]
    rows = [command_row(name) for name in names]
    table = tmp_path / "steps.json"
    table.write_text(json.dumps({"steps": rows}))
    monkeypatch.setattr(flow_engine, "TABLE", table)
    route = {"entry_step": names[0], "verify_through": names[-1],
             "delivery_target": "ip_hardmacro", "input_contract": "structured"}
    first = flow_engine.run(tmp_path, route=route)
    first["pdn_recovery"] = {"first_attempt": str(tmp_path / "archive"), "physical_replays": 1}
    report_path = tmp_path / "reports/flow_engine.json"
    report_path.write_text(json.dumps(first))
    old_floorplan = next(row["tool_seconds"] for row in first["steps"] if row["name"] == names[1])
    args = SimpleNamespace(project=tmp_path, entry_step=names[0], exit_step=names[-1],
        rtl_input="structured", delivery_target="ip_hardmacro", route="ip", pdk="auto", from_name=names[1])
    assert frontend.run_public(args) == 0
    report = json.loads(report_path.read_text())
    assert report["selected_names"] == names
    assert report["pdn_recovery"]["physical_replays"] == 1
    assert next(row["tool_seconds"] for row in report["steps"] if row["name"] == names[1]) > old_floorplan


def test_replayed_metrics_replace_old_candidate_and_spent_times_remain(tmp_path):
    import flow_engine
    row = {"name": "die_floorplan_and_macros", "status": "PASS", "tool_seconds": 4,
           "program_seconds": 1, "wall_seconds": 5, "started_at": 20, "completed_at": 25,
           "native_common_started_at": 20, "native_common_completed_at": 25,
           "timing_group": "librelane", "ai_seconds": 0, "native_metrics": {"measured": 2}}
    old = {**row, "tool_seconds": 7, "program_seconds": 2, "wall_seconds": 9,
           "started_at": 10, "completed_at": 19, "native_common_started_at": 10,
           "native_metrics": {"measured": 1}}
    first = {"steps": [old], "selected": 1, "selected_names": [row["name"]],
             "native_common_started_at": 10, "started_at": 8, "common_step_names": [row["name"]]}
    final = {"steps": [row], "completed_at": 25, "native_common_completed_at": 25}
    result = finish_replay(tmp_path, first, final, tmp_path / "archive", extra_program_seconds=2)
    assert result["steps"][0]["native_metrics"] == {"measured": 2}
    assert result["tool_seconds"] == 11
    assert result["program_seconds"] >= 5
    assert result["common_wall_seconds"] == 15
    assert result["started_at"] == 8


def test_native_special_wire_roles_use_actual_shape_types(tmp_path):
    odb = pytest.importorskip("odb")
    lef = tmp_path / "tech.lef"
    lef.write_text("""VERSION 5.8 ;
UNITS
 DATABASE MICRONS 1000 ;
END UNITS
MANUFACTURINGGRID 0.005 ;
LAYER vertical
 TYPE ROUTING ;
 DIRECTION VERTICAL ;
 PITCH 1 ;
 WIDTH 0.3 ;
 SPACING 0.3 ;
END vertical
END LIBRARY
""")
    definition = tmp_path / "unit.def"
    definition.write_text("VERSION 5.8 ;\nDESIGN unit ;\nUNITS DISTANCE MICRONS 1000 ;\n"
                          "DIEAREA ( 0 0 ) ( 10000 10000 ) ;\nEND DESIGN\n")
    database = odb.dbDatabase.create()
    try:
        odb.read_lef(database, str(lef))
        odb.read_def(database.getTech(), str(definition))
        block = database.getChip().getBlock()
        net = odb.dbNet.create(block, "power")
        net.setSigType("POWER")
        swire = odb.dbSWire.create(net, "ROUTED")
        odb.dbSBox.create(swire, database.getTech().findLayer("vertical"), 0, 0, 100, 1000, "STRIPE")
        native = {**config(), "PDN_RAIL_LAYER": "rail"}
        assert _wires(block, native) == [Wire("vertical", "PDN_VWIDTH", (0, 0, .1, 1))]
    finally:
        odb.dbDatabase.destroy(database)
