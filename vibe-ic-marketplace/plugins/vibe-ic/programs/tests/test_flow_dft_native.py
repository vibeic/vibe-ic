"""Selected DFT rows run native scan tools and preserve their verdicts."""
import json
import shutil
import subprocess

import pytest

import flow_engine as engine


def test_scan_intent_reads_the_canonical_layer_filename(tmp_path):
    from flow_dft_steps import scan_intent

    payload = {"scan_chains": [{"clock": "clk", "scan_in": "sin", "scan_out": "sout", "scan_enable": "shift"}],
               "test_mode": {"reset": {"signal": "rst", "shift_value": 0}}}
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L20_DFT_SCAN_TOPOLOGY.json").write_text(json.dumps({"fields": payload}))
    assert scan_intent(tmp_path) == (payload["scan_chains"][0], payload["test_mode"]["reset"])


@pytest.mark.parametrize("name,step,metric", [
    ("dft_architecture_and_insertion", "VibeIC.ScanInsertion", "scan_test_protocol_integrity"),
    ("post_dft_optimization", "VibeIC.ScanPreservation", "scan_preservation_errors"),
    ("physical_scan_stitching", "VibeIC.PhysicalScan", "scan_flush_errors"),
])
@pytest.mark.parametrize("errors,ran,expected", [(0, True, "PASS"), (1, True, "FAIL"),
                                               (None, False, "NOT_MEASURED")])
def test_selected_scan_row_runs_native_tools(tmp_path, monkeypatch, name, step, metric, errors, ran, expected):
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L20_DFT_TEST.json").write_text(json.dumps({"scan_required": True,
        "scan_chains": [{"clock": "clk", "scan_in": "sin", "scan_out": "sout", "scan_enable": "shift"}]}))
    calls = []

    def execute(self, directory, tool):
        calls.extend(tool["steps"])
        metrics = {metric: errors} if step in tool["steps"] and errors is not None else {}
        return engine.ToolResult(ran, 0 if ran else None, metrics)

    monkeypatch.setattr(engine.NativeChain, "execute", execute)
    route = {"entry_step": name, "verify_through": name,
             "delivery_target": "gds", "input_contract": "structured"}
    result = engine.run(tmp_path, route=route, from_name=name, to_name=name)
    assert step in calls
    assert result["steps"][0]["status"] == expected


@pytest.mark.parametrize("fault", ["healthy", "stuck_output", "short_chain"])
def test_serial_bench_measures_the_actual_chain(tmp_path, fault):
    if not shutil.which("iverilog") or not shutil.which("vvp"):
        pytest.skip("Native Icarus is required")
    from flow_dft_steps import serial_bench

    ports = {"clk": "INPUT", "rst": "INPUT", "sin": "INPUT", "shift": "INPUT",
             **{f"q[{bit}]": "OUTPUT" for bit in range(4)}}
    chain = {"clock": "clk", "scan_in": "sin", "scan_out": "q[0]", "scan_enable": "shift"}
    bench = tmp_path / "tb.v"
    bench.write_text(serial_bench("core", ports, chain, {"signal": "rst", "shift_value": 0}, 4, 20))
    expression = "{sin,q[3:1]}" if fault == "healthy" else "{sin,q[3:2],1'b0}"
    if fault == "short_chain":
        expression = "{sin,1'b0,q[3:2]}"
    design = tmp_path / "core.v"
    design.write_text("module core(input clk,rst,sin,shift,output reg[3:0]q);"
                      f"always @(posedge clk) if(shift) q<={expression};endmodule\n")
    executable = tmp_path / "scan.vvp"
    compile = subprocess.run(["iverilog", "-g2012", "-s", "tb", "-o", str(executable),
                              str(design), str(bench)], capture_output=True, text=True)
    assert compile.returncode == 0, compile.stderr
    run = subprocess.run(["vvp", str(executable)], capture_output=True, text=True)
    assert (run.returncode == 0) == (fault == "healthy"), run.stdout + run.stderr
    if fault == "healthy":
        assert "SCAN_FLUSH checked=32 errors=0" in run.stdout
