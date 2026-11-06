"""Final ATPG keeps raw coverage and measured protocol errors separate."""
import json
from pathlib import Path
import subprocess

import pytest

pytest.importorskip("librelane")
from librelane.steps import StepError, StepException

import flow_dft_steps
import flow_engine as engine
import flow_native_adapters as adapters


@pytest.mark.parametrize("code,coverage,protocol,expected", [
    (0, 99, "PASS", "PASS"), (1, 80, "PASS", "FAIL"),
    (0, 90, "PASS", "FAIL"), (2, None, "PASS", "NOT_MEASURED"),
    (0, 99, "FAIL", "FAIL"), (0, 99, "NOT_MEASURED", "NOT_MEASURED"),
])
def test_final_atpg_uses_native_coverage_and_serial_replay(tmp_path, monkeypatch, code, coverage, protocol, expected):
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L20_DFT_SCAN_TOPOLOGY.json").write_text(json.dumps({"fields": {
        "scan_chains": [{"scan_in": "sin", "scan_out": "sout", "scan_enable": "shift", "clock": "clk"}],
        "test_mode": {"reset": {"signal": "rst", "shift_value": 0}}}}))
    netlist, database, model = (tmp_path / name for name in ["core.v", "core.odb", "models.v"])
    for path in [netlist, database, model]:
        path.write_text("")
    calls = []

    def run(self, argv, **kwargs):
        argv = list(map(str, argv))
        calls.append(argv)
        assert argv[argv.index("--reset") + 1] == "rst"
        assert "--no-transition" not in argv
        report = Path(argv[argv.index("--json") + 1])
        report.write_text(json.dumps({"faults_total": 10 if coverage is not None else 0,
                                     "coverage_pct": coverage, "test_coverage_pct": 100}))
        self.records.append({"exit_code": code, "log": str(self.directory / "native.log")})
        return subprocess.CompletedProcess(argv, code)

    def replay(step, state, metric):
        assert metric == "test_protocol_errors"
        if protocol == "FAIL":
            raise StepError("native Icarus mismatch")
        if protocol == "NOT_MEASURED":
            raise StepException("native scan data missing")
        return {metric: 0}

    monkeypatch.setattr(adapters.Commands, "run", run)
    monkeypatch.setattr(flow_dft_steps, "replay", replay)
    row = next(row for row in engine.read_json(engine.TABLE)["steps"]
               if row["name"] == "final_test_patterns_and_test_activity")
    native = engine.ToolResult(**adapters.execute(tmp_path, tmp_path / "step", row["tool"], {},
        state={"nl": str(netlist), "odb": str(database)},
        config={"DESIGN_DIR": str(tmp_path), "DESIGN_NAME": "core", "CLOCK_PORT": "clk",
                "CELL_VERILOG_MODELS": [str(model)]}))
    checks = [{**check, **({"limit": {"min": 95}} if check["metric"] == "final_test_pattern_coverage" else {})}
              for check in row["checks"]]
    measured = engine.measure(checks, native.metrics, {}, {"requires_dft": True})
    assert len(calls) == 1
    assert engine.evaluate(native, measured) == expected
    if coverage is not None:
        assert native.metrics["final_test_pattern_coverage"] == coverage
        assert native.metrics["test_coverage_pct"] == 100
