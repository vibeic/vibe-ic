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
                        from_name="structural_rtl_preflight", to_name="die_floorplan_and_macros")
    steps = {row["name"]: row for row in report["steps"]}
    for name in ("rtl_validation_and_lint", "synthesis"):
        assert steps[name]["status"] == "PASS", steps[name]
    floorplan = steps["die_floorplan_and_macros"]
    actual = [row for row in floorplan["native_steps"] if row["name"] == "OpenROAD.Floorplan"]
    assert len(actual) == 1 and actual[0]["ran"] and actual[0]["exit_code"] == 0, floorplan
    state = json.loads((project / "steps/die_floorplan_and_macros/state_out.json").read_text())
    assert Path(state["odb"]).is_file()
    assert report["route"] == route
    assert report["fail"] == 0, report
    return report


def test_native_lint_synthesis_floorplan(tmp_path):
    if importlib.util.find_spec("librelane") is None:
        pytest.skip("LibreLane runtime is required for the real-tool test")
    native_run(tmp_path, Path(os.environ.get(
        "FLOW_ENGINE_PROGRAMS", str(Path(__file__).resolve().parents[1]))))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--programs", type=Path, default=Path(__file__).resolve().parents[1])
    arguments = parser.parse_args()
    result = native_run(arguments.project.resolve(), arguments.programs.resolve())
    print(json.dumps({key: value for key, value in result.items() if key != "steps"}, indent=2))
