"""The selected system row executes produced benches and reads native checks."""
import json
import shutil
import subprocess

import pytest

import flow_engine as engine
import flow_native_adapters as adapters


@pytest.mark.parametrize("code,output,expected", [
    (0, "ORACLE_TB_DONE pass=4/4", "PASS"),
    (0, "ORACLE_TB_DONE pass=3/4", "FAIL"),
    (0, "Simulation finished", "NOT_MEASURED"),
    (1, "ERROR invalid transaction", "FAIL"),
    (None, "", "NOT_MEASURED"),
])
def test_system_row_runs_native_icarus(tmp_path, monkeypatch, code, output, expected):
    rtl = tmp_path / "core.v"
    rtl.write_text("module core; endmodule\n")
    bench = tmp_path / "phase2/stage1/sim_full_stack/tb_system.v"
    bench.parent.mkdir(parents=True)
    bench.write_text("module tb_system; core dut(); endmodule\n")
    monkeypatch.setattr(adapters, "inputs", lambda *args: ([rtl], "core"))
    monkeypatch.setattr(adapters, "simulation_sources", lambda *args: ([rtl], []))
    calls = []

    def run(self, argv, **kwargs):
        assert "timeout" not in kwargs
        calls.append(list(map(str, argv)))
        if code is None:
            return None
        rc, text = (0, "") if len(calls) == 1 else (code, output)
        self.records.append({"exit_code": rc, "log": str(self.directory / f"{len(calls)}.log")})
        return subprocess.CompletedProcess(argv, rc, text, "")

    monkeypatch.setattr(adapters.Commands, "run", run)
    row = next(row for row in engine.read_json(engine.TABLE)["steps"]
               if row["name"] == "system_and_software_scenarios")
    native = engine.ToolResult(**adapters.execute(tmp_path, tmp_path / "step", row["tool"], {}))
    assert len(calls) == (1 if code is None else 2)
    assert calls[0][0] == "iverilog"
    measured = engine.measure(row["checks"], native.metrics, {}, {"requires_system_scenarios": True})
    assert engine.evaluate(native, measured) == expected
    if "ORACLE_TB_DONE" in output:
        failures = 0 if "4/4" in output else 1
        assert native.metrics["blocking_system_scenario_failures"] == failures
        assert native.metrics["boot_workload_protocol_errors"] == failures
    else:
        assert native.metrics == {}


def test_system_bench_compiles_its_included_header(tmp_path):
    if not all(shutil.which(tool) for tool in ("iverilog", "vvp")):
        pytest.skip("Native Icarus is required")
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"top_module": "core"}))
    rtl = tmp_path / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    (rtl / "core.v").write_text("module core(output wire q); assign q=1; endmodule\n")
    benches = tmp_path / "phase2/stage1/sim_full_stack"
    benches.mkdir(parents=True)
    (benches / "expected.svh").write_text("`define EXPECTED 1'b1\n")
    (benches / "tb_system.v").write_text('''`include "expected.svh"
module tb_system;
wire q; core dut(.q(q));
initial begin #1; if(q !== `EXPECTED) $fatal(1,"mismatch");
$display("ORACLE_TB_DONE pass=1/1"); $finish; end
endmodule
''')
    row = next(row for row in engine.read_json(engine.TABLE)["steps"]
               if row["name"] == "system_and_software_scenarios")
    native = engine.ToolResult(**adapters.execute(tmp_path, tmp_path / "step", row["tool"], {}))
    measured = engine.measure(row["checks"], native.metrics, {}, {"requires_system_scenarios": True})
    assert engine.evaluate(native, measured) == "PASS"
