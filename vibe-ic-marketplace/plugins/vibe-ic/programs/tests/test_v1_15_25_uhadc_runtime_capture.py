#!/usr/bin/env python3
"""Round-3 U-Hawaii ADC capture: runtime metadata and cocotb evidence.

Both cases are chip-agnostic.  A watchdog pidfile is process-control metadata,
not a project deliverable; an executed cocotb test is testbench evidence, not
an unrecognised source file.  The controls keep a real external artefact and
an under-covered Verilog-only testbench blocking.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]
OUTPUT_GATE = PROGRAMS / "project_outputs_in_tree_check.py"
TB_GATE = PROGRAMS / "testbench_exists_check.py"


def _run(program: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(program), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _verilog_tb(test_count: int) -> str:
    checks = "\n".join(
        f'    #1; $display("TEST {index}: check");'
        for index in range(1, test_count + 1)
    )
    return (
        "module neutral_tb;\n"
        "  reg clk;\n"
        "  initial begin clk = 0; forever #1 clk = ~clk; end\n"
        "  initial begin\n"
        f"{checks}\n"
        "    $finish;\n"
        "  end\n"
        "endmodule\n"
    )


def _cocotb_tb() -> str:
    return """\
import cocotb
from cocotb.triggers import RisingEdge, Timer

@cocotb.test()
async def scored_protocol(dut):
    dut.input_signal.value = 0
    await Timer(1, units="ns")
    assert int(dut.output_signal.value) == 0
    await RisingEdge(dut.clk)
    assert int(dut.output_signal.value) in (0, 1)
    assert dut.output_signal.value.is_resolvable
    assert int(dut.counter.value) >= 0
"""


def test_watchdog_pidfile_in_json_is_disclosed_nonblocking(tmp_path: Path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "lec.telemetry.20260901T000000-neutral.json").write_text(
        json.dumps({
            "schema_version": "vibeic.lec.telemetry.v1",
            "status": "complete",
            "pidfile": "/tmp/.vibeic-job-0123456789abcdef.pid",
            "verdict": "PASS",
        })
    )

    result = _run(OUTPUT_GATE, str(tmp_path))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "ephemeral process-marker" in result.stdout
    assert "/tmp/.vibeic-job-0123456789abcdef.pid" in result.stdout


def test_real_external_deliverable_remains_blocking(tmp_path: Path):
    reports = tmp_path / "reports"
    reports.mkdir()
    external = Path("/tmp/vibeic_capture_control_design.gds")
    external.write_text("real external deliverable control\n")
    try:
        (reports / "signoff.json").write_text(json.dumps({
            "gds": str(external),
            "status": "PASS",
        }))
        result = _run(OUTPUT_GATE, str(tmp_path))
        assert result.returncode == 1, result.stdout + result.stderr
        assert "live external-storage artifact" in result.stdout
        assert str(external) in result.stdout
    finally:
        external.unlink(missing_ok=True)


def test_cocotb_checks_contribute_to_project_test_denominator(tmp_path: Path):
    stage = tmp_path / "phase2" / "stage1"
    (stage / "sim_self").mkdir(parents=True)
    (stage / "sim_professional" / "neutral").mkdir(parents=True)
    (stage / "sim_self" / "neutral_tb.sv").write_text(_verilog_tb(5))
    (stage / "sim_professional" / "neutral" / "tb_neutral.py").write_text(
        _cocotb_tb()
    )

    result = _run(TB_GATE, "--rtl-dir", str(tmp_path))

    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["summary"]["total_test_cases"] == 10
    assert any(item["language"] == "python-cocotb"
               for item in report["testbenches"])


def test_verilog_only_undercoverage_remains_blocking(tmp_path: Path):
    stage = tmp_path / "phase2" / "stage1" / "sim_self"
    stage.mkdir(parents=True)
    (stage / "neutral_tb.sv").write_text(_verilog_tb(9))

    result = _run(TB_GATE, "--rtl-dir", str(tmp_path))

    assert result.returncode == 1, result.stdout + result.stderr
    assert "INSUFFICIENT_TESTS" in result.stdout
