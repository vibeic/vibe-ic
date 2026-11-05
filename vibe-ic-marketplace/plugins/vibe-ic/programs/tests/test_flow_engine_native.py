from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest


def native_run(project: Path, programs: Path) -> dict:
    sys.path.insert(0, str(programs))
    import flow_engine as engine
    import task_nature_route as router

    prompt = "Build a 16-bit synchronous counter hard macro IP on sky130A for integration."
    docs = project / "phase1/generated_docs"
    rtl = project / "phase2/stage1/rtl"
    docs.mkdir(parents=True, exist_ok=True)
    rtl.mkdir(parents=True, exist_ok=True)
    (project / "input/docs").mkdir(parents=True, exist_ok=True)
    (project / "input/docs/requirements.md").write_text(prompt + "\n")
    (rtl / "unit.v").write_text(
        "module unit(input wire clk, input wire reset_n, output reg [15:0] q);\n"
        "always @(posedge clk) begin\n"
        "  if (!reset_n) q <= 16'b0; else q <= q + 16'b1;\n"
        "end\nendmodule\n")
    for name, value in {
        "L9_INTEGRATION_SPEC.json": {"top_module": "unit"},
        "L8_TIMING_WAVEFORM.json": {"clock_domains": [{
            "domain_kind": "primary", "source_pin": "clk", "period_ns": 20}]},
        "L19_CONSTRAINTS_PDK.json": {"fields": {"pdk_target": "sky130A"}},
    }.items():
        (docs / name).write_text(json.dumps(value) + "\n")
    route = router.route_decision_receipt(
        prompt, nature="spec_generation", delivery_target="ip_hardmacro")
    report = engine.run(project, route=route,
                        from_name="structural_rtl_preflight", to_name="io_pad_ring_and_power_distribution")
    steps = {row["name"]: row for row in report["steps"]}
    for name in ("rtl_validation_and_lint", "synthesis"):
        native_checks = [check for check in steps[name]["metrics"]
                         if "/librelane/" in (check.get("source") or {}).get("file", "")]
        assert native_checks and all(check["status"] == "PASS" for check in native_checks), steps[name]
        assert all(row["exit_code"] in (None, 0) for row in steps[name]["native_steps"]), steps[name]
    floorplan = steps["die_floorplan_and_macros"]
    actual = [row for row in floorplan["native_steps"] if row["name"] == "OpenROAD.Floorplan"]
    assert len(actual) == 1 and actual[0]["ran"] and actual[0]["exit_code"] == 0, floorplan
    state = json.loads((project / "steps/die_floorplan_and_macros/state_out.json").read_text())
    assert Path(state["odb"]).is_file()
    sizing = json.loads((project / "work/flow/chip/pdn_sizing.json").read_text())
    config = json.loads((project / "steps/io_pad_ring_and_power_distribution/openroad_generatepdn/config.json").read_text())
    from decimal import Decimal
    assert all(Decimal(str(config[key])) == Decimal(str(value)) for key, value in sizing["settings"].items())
    assert report["route"] == route
    assert report["fail"] == 0, report
    return report


def test_native_lint_synthesis_floorplan(tmp_path):
    if importlib.util.find_spec("librelane") is None:
        pytest.skip("LibreLane runtime is required for the real-tool test")
    native_run(tmp_path, Path(os.environ.get(
        "FLOW_ENGINE_PROGRAMS", str(Path(__file__).resolve().parents[1]))))


@pytest.mark.parametrize("lint_errors", [None, 0, 2])
def test_missing_metadata_preserves_a_valid_native_database(tmp_path, lint_errors):
    if importlib.util.find_spec("librelane") is None:
        pytest.skip("LibreLane runtime is required")
    import flow_engine as engine
    from librelane.state import State, DesignFormat
    from librelane.common import Path as NativePath

    rtl = tmp_path / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    (rtl / "unit.v").write_text("module unit(input clk, output q); assign q=clk; endmodule\n")
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"top_module": "unit"}))
    (docs / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({"clock_domains": [
        {"domain_kind": "primary", "source_pin": "clk", "period_ns": 20}]}))
    (docs / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps({"fields": {"pdk_target": "sky130A"}}))
    chain = engine.NativeChain(tmp_path, {"delivery_target": "ip_hardmacro"})
    chain.initialize()
    odb = tmp_path / "valid-input.odb"
    odb.touch()
    metrics = {"upstream": 1}
    if lint_errors is not None:
        metrics["design__lint_error__count"] = lint_errors
    chain.state = State({DesignFormat.ODB: NativePath(str(odb))}, metrics=metrics)
    output = tmp_path / "step"
    output.mkdir()
    result = chain.execute(output, {"steps": ["Odb.SetPowerConnections"] +
        (["Checker.LintErrors"] if lint_errors is not None else [])})
    assert "missing required input 'json_h'" in result.native_steps[0]["detail"]
    assert result.native_steps[0]["status"] == "NOT_MEASURED"
    assert result.native_steps[0]["exit_code"] is None
    assert (output / "odb_setpowerconnections/state_in.json").is_file()
    if lint_errors is None:
        assert not result.ran
    else:
        assert result.native_steps[1]["ran"]
        assert result.native_steps[1]["status"] == ("FAIL" if lint_errors else "PASS")
        assert result.metrics["design__lint_error__count"] == lint_errors
    assert chain.state.get_by_df(DesignFormat.ODB) == str(odb)
    assert chain.state.metrics["upstream"] == 1


def test_failed_chip_preparation_charges_native_time_once(tmp_path):
    if importlib.util.find_spec("librelane") is None:
        pytest.skip("LibreLane runtime is required")
    import flow_engine as engine
    rtl = tmp_path / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    (rtl / "unit.v").write_text("module unit(input clk, output q); this is invalid RTL; endmodule\n")
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"top_module": "unit"}))
    (docs / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({"clock_domains": [
        {"domain_kind": "primary", "source_pin": "clk", "period_ns": 20}]}))
    (docs / "L19_CONSTRAINTS_PDK.json").write_text(json.dumps({"fields": {"pdk_target": "sky130A"}}))
    chain = engine.NativeChain(tmp_path, {"delivery_target": "shippable_gds"})
    first = chain.execute(tmp_path / "first", {"steps": ["Yosys.JsonHeader"]})
    assert first.tool_seconds > 0
    assert first.tool_seconds == sum(row.get("tool_seconds", 0) for row in first.native_steps)
    assert first.native_steps[0]["name"] == "Yosys.JsonHeader"
    assert first.native_steps[0]["status"] == "FAIL"
    assert engine.evaluate(first, []) == "FAIL"
    second = chain.execute(tmp_path / "second", {"steps": ["Yosys.JsonHeader"]})
    assert second.tool_seconds == 0
    assert len(chain.preparation_runs) == 1


def test_restoring_native_state_replaces_cached_metrics(tmp_path):
    if importlib.util.find_spec("librelane") is None:
        pytest.skip("LibreLane runtime is required")
    import flow_engine as engine
    import librelane.flows
    from librelane.state import State, DesignFormat
    from librelane.common import Path as NativePath

    database = tmp_path / "current.odb"
    database.touch()
    native = State({DesignFormat.ODB: NativePath(str(database))},
                   metrics={"native_tool_count": 0, "upstream_area": 5})
    (tmp_path / "state_out.json").write_text(native.dumps())
    chain = engine.NativeChain(tmp_path, {"delivery_target": "rtl"})
    chain.state = State(metrics={"cached_tool_count": 1, "upstream_area": 9})

    chain.restore(tmp_path)

    assert "cached_tool_count" not in chain.state.metrics
    assert dict(chain.state.metrics) == {"native_tool_count": 0, "upstream_area": 5}
    assert chain.state.get_by_df(DesignFormat.ODB) == str(database)


def test_resumed_pdn_uses_sized_native_configuration(tmp_path, monkeypatch):
    pytest.importorskip("librelane")
    import flow_engine as engine
    import flow_pdn_current

    report = native_run(tmp_path, Path(__file__).resolve().parents[1])
    floorplan = tmp_path / "steps/die_floorplan_and_macros/result.json"
    earlier = floorplan.read_bytes()
    monkeypatch.setattr(flow_pdn_current, "current_settings", lambda *args, **kwargs: {
        "PDN_VWIDTH": 2.0, "PDN_HWIDTH": 2.0})

    resumed = engine.run(tmp_path, route=report["route"],
        from_name="io_pad_ring_and_power_distribution", to_name="io_pad_ring_and_power_distribution")

    config = json.loads((tmp_path / "steps/io_pad_ring_and_power_distribution/openroad_generatepdn/config.json").read_text())
    assert config["PDN_VWIDTH"] == config["PDN_HWIDTH"] == 2
    assert resumed["steps"][0]["status"] == "PASS"
    assert floorplan.read_bytes() == earlier


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--programs", type=Path, default=Path(__file__).resolve().parents[1])
    arguments = parser.parse_args()
    result = native_run(arguments.project.resolve(), arguments.programs.resolve())
    print(json.dumps({key: value for key, value in result.items() if key != "steps"}, indent=2))
