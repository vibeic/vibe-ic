#!/usr/bin/env python3
"""Tests for sdf_gate_sim.py pure helpers (Step 29: SDF gate-level sim).

Only the container-free helpers are exercised here — the golden model, the
vvp-output parser, the results.log builder (incl. the gate-contract invariant
that a PASS log has no FATAL/ERROR-at-line-start and a FAIL surfaces one), the
transcript curator, and the netlist/port detectors.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import sdf_gate_sim as sg  # noqa: E402

# the exact regex the gate uses to reject a results.log
_GATE_FATAL = re.compile(r"^\s*(\*\*\s*)?(FATAL|ERROR)\b", re.IGNORECASE | re.MULTILINE)


def test_serial_golden_basic():
    assert sg.serial_golden(3, 3, 32) == 9
    assert sg.serial_golden(0, 123, 32) == 0
    assert sg.serial_golden(0xFFFFFFFF, 0xFFFFFFFF, 32) == 1  # (2^32-1)^2 mod 2^32
    assert sg.serial_golden(2, 0xFFFFFFFF, 32) == 0xFFFFFFFE
    # width truncation
    assert sg.serial_golden(0xFF, 0xFF, 8) == (0xFF * 0xFF) & 0xFF


SAMPLE_STDOUT = """SDF INFO: Loading /x/spm.sdf from tb_spm_sdf.v:25
SDF INFO: /x/spm.sdf:3: Design: spm
SDF INFO: /x/spm.sdf:9: Created a vpiInterModPath
SDF INFO: /x/spm.sdf:10: Created a vpiInterModPath
=== spm SDF-annotated gate-level simulation ===
streaming scoreboard locked: order=lsb latency=1
ok  x=3 y=3  p=9
ok  x=1 y=1  p=1
GATE_SIM_RESULT PASS 50/50 vectors, order=lsb latency=1
tb_spm_sdf.v:145: $finish called at 36715000 (1ps)
"""


def test_parse_sim_stdout_pass():
    p = sg.parse_sim_stdout(SAMPLE_STDOUT)
    assert p["annotated_interconnect_delays"] == 2
    assert p["verdict"] == "PASS"
    assert p["passed"] == 50 and p["total"] == 50
    assert p["bit_order"] == "lsb" and p["latency"] == 1
    assert p["calibrated"] is True


def test_parse_sim_stdout_calibration_fail():
    txt = ("SDF INFO: Loading /x/spm.sdf from tb.v:1\n"
           "CALIBRATION_FAIL: no (order,latency) reproduces (x*y) mod 2^N\n"
           "GATE_SIM_RESULT FAIL 0/0 vectors\n")
    p = sg.parse_sim_stdout(txt)
    assert p["verdict"] == "FAIL"
    assert p["passed"] == 0 and p["total"] == 0
    assert p["calibrated"] is False


def _meta(verdict, passed, total):
    return {
        "top": "spm", "width": 32, "netlist": "n.v", "pdk_lib": "pdk.v",
        "sdf": "/x/spm.sdf", "simulator": "iverilog 14",
        "compile_flags": "-g2012 -ginterconnect", "runtime_flags": "-sdf-info",
        "annotated_interconnect_delays": 634, "bit_order": "lsb", "latency": 1,
        "verdict": verdict, "passed": passed, "total": total,
    }


def test_build_results_log_pass_has_no_fatal_and_refs_sdf():
    log = sg.build_results_log(_meta("PASS", 50, 50), SAMPLE_STDOUT)
    # gate invariant 1: references SDF annotation
    assert re.search(r"\$sdf_annotate|\.sdf\b", log)
    # gate invariant 2: no line starts with FATAL/ERROR
    assert not _GATE_FATAL.search(log)
    assert "VERDICT: PASS" in log
    # curated transcript dropped the verbose interconnect lines
    assert "Created a vpiInterModPath" not in log
    # but kept the functional evidence
    assert "GATE_SIM_RESULT PASS 50/50" in log


def test_build_results_log_fail_surfaces_error_line():
    fail_stdout = SAMPLE_STDOUT.replace(
        "GATE_SIM_RESULT PASS 50/50 vectors, order=lsb latency=1",
        "MISMATCH  x=3 y=3 exp=9 got=7\nGATE_SIM_RESULT FAIL 1/50 vectors mismatched")
    log = sg.build_results_log(_meta("FAIL", 49, 50), fail_stdout)
    # a functional failure MUST trip the gate (never a silent pass)
    assert _GATE_FATAL.search(log), "FAIL results.log must contain an ERROR line"


def test_curate_transcript_drops_verbose_keeps_functional():
    cur = sg._curate_transcript(SAMPLE_STDOUT)
    assert "Created a vpiInterModPath" not in cur
    assert "Design: spm" in cur          # SDF header retained
    assert "ok  x=3 y=3  p=9" in cur     # functional line retained
    assert "GATE_SIM_RESULT PASS" in cur


SPM_NETLIST = """
module spm (clk, p, rst, y, x, VDD, VSS);
 input clk;
 output p;
 input rst;
 input y;
 input [31:0] x;
 inout VDD;
 inout VSS;
 wire _000_;
 NAND2D1 _197_ (.Y(_065_), .A(y), .B(x[25]));
 DFFHQD1 _400_ (.Q(s[7]), .D(_017_), .CK(clk));
 FILL1 FILLER_0_116 ();
 DECAP4 FILLER_0_110 ();
 TIELO spare_tielo_drv (.Y(spare_tielo));
 assign p = p_r;
endmodule
"""


def test_netlist_cells_and_ports():
    used, ports = sg.netlist_cells_and_ports(SPM_NETLIST, "spm")
    assert {"NAND2D1", "DFFHQD1", "FILL1", "DECAP4", "TIELO"} <= used
    assert ports["clk"]["dir"] == "input" and ports["clk"]["width"] == 1
    assert ports["x"]["dir"] == "input" and ports["x"]["width"] == 32
    assert ports["y"]["width"] == 1
    assert ports["p"]["dir"] == "output" and ports["p"]["width"] == 1


def test_detect_serial_mult():
    _, ports = sg.netlist_cells_and_ports(SPM_NETLIST, "spm")
    pm = sg._detect_serial_mult(ports)
    assert pm is not None
    assert pm["clk"] == "clk" and pm["rst"] == "rst"
    assert pm["xport"] == "x" and pm["yport"] == "y" and pm["pport"] == "p"
    assert pm["width"] == 32


def test_detect_serial_mult_rejects_non_serial():
    # two multi-bit inputs -> not a serial multiplier contract
    ports = {"clk": {"dir": "input", "width": 1},
             "rst": {"dir": "input", "width": 1},
             "a": {"dir": "input", "width": 8},
             "b": {"dir": "input", "width": 8},
             "q": {"dir": "output", "width": 8}}
    assert sg._detect_serial_mult(ports) is None


def test_missing_empty_cell_stubs():
    # FILL1 has empty () and is NOT in the PDK -> needs a stub;
    # DECAP4 has empty () but IS in the PDK -> no stub; TIELO has ports -> no stub
    pdk = "module DECAP4;\nendmodule\nmodule NAND2D1 (Y,A,B); endmodule\n"
    used, _ = sg.netlist_cells_and_ports(SPM_NETLIST, "spm")
    stubs = sg.missing_empty_cell_stubs(SPM_NETLIST, used, pdk)
    assert stubs == ["FILL1"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
