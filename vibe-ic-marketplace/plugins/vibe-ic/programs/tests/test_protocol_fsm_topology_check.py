#!/usr/bin/env python3
"""Tests for protocol_fsm_topology_check.py (BACKLOG-v11 P0.1).

Coverage:
  - non-protocol design → exit 2 (skip)
  - protocol design with explicit single_fsm topology → PASS
  - protocol design with modular_split + rationale → PASS
  - protocol design with modular_split, no rationale → WARN
  - protocol design (auto) with 1 orchestration FSM → PASS
  - protocol design (auto) with 3+ orchestration FSMs and pulses → WARN
  - --strict upgrades WARN → ERROR (exit 1)
  - JSON report shape sanity
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / \
    "protocol_fsm_topology_check.py"


def _run(tmp_path: Path, strict: bool = False) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(PROG), str(tmp_path),
           "--json", str(tmp_path / "report.json")]
    if strict:
        cmd.append("--strict")
    return subprocess.run(cmd, capture_output=True, text=True)


def _load_report(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


def _make_l8(tmp_path: Path, content: dict | None = None):
    """Create a minimal L8 doc with protocol-IP triggers."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    body = content or {
        "doc_layer": "L8_RTL_CONSTANTS",
        "host_rx_thresholds_ticks_at_5MHz": {"IBT_MIN": 40},
        "byte_framing": "8 data bits LSB-first + IBT idle",
    }
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps(body))


def _make_l9(tmp_path: Path, fsm_topology: str | None = None,
             rationale: str = ""):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    body: dict = {"doc_layer": "L9_INTEGRATION_SPEC"}
    if fsm_topology:
        body["fsm_topology"] = fsm_topology
        if rationale:
            body["fsm_topology_rationale"] = rationale
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(body))


def _write_rtl(tmp_path: Path, name: str, body: str):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / name).write_text(body)


# Reusable RTL fragments
_FSM_MOD_TEMPLATE = """\
module {name} (input logic clk, input logic rstn,
               output logic {pulse}, output logic dispatcher_busy);
  typedef enum logic [1:0] {{ S_IDLE, S_BUSY }} st_e;
  st_e st;
  always_ff @(posedge clk or negedge rstn) begin
    if (!rstn) begin
      st <= S_IDLE;
      {pulse} <= 1'b0;
    end else begin
      {pulse} <= 1'b0;       // default low (pulse strobe)
      case (st)
        S_IDLE: if (cmd_pass) begin
          st <= S_BUSY;
          {pulse} <= 1'b1;   // 1-cycle pulse — RACE RISK
        end
        S_BUSY: st <= S_IDLE;
      endcase
    end
  end
endmodule
"""


def _modular_3_fsm_design(tmp_path: Path):
    """Create 3 modules, each with explicit FSM + cross-module pulse."""
    _write_rtl(tmp_path, "decoder.sv",
               _FSM_MOD_TEMPLATE.format(name="decoder", pulse="cmd_pass"))
    _write_rtl(tmp_path, "main_fsm.sv",
               _FSM_MOD_TEMPLATE.format(name="main_fsm", pulse="tsrs_ok"))
    _write_rtl(tmp_path, "dispatcher.sv",
               _FSM_MOD_TEMPLATE.format(name="dispatcher",
                                        pulse="kick_wake_pulse"))


# -- Test 1: non-protocol design → skip (exit 2) --

def test_skip_non_protocol(tmp_path):
    """No L8 IBT/protocol tokens, no L9 fsm_topology, no opcode table."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "doc_layer": "L8_RTL_CONSTANTS",
        "clock_freq_mhz": 50,  # plain counter design, no protocol
    }))
    r = _run(tmp_path)
    assert r.returncode == 2
    rpt = _load_report(tmp_path)
    assert rpt["summary"]["is_protocol_ip"] is False


# -- Test 2: explicit single_fsm topology → PASS --

def test_explicit_single_fsm(tmp_path):
    _make_l8(tmp_path)
    _make_l9(tmp_path, fsm_topology="single_fsm")
    _modular_3_fsm_design(tmp_path)  # even with 3 FSMs, override should silence
    r = _run(tmp_path)
    assert r.returncode == 2  # skip — engineer override
    rpt = _load_report(tmp_path)
    assert rpt["summary"]["fsm_topology_declared"] == "single_fsm"


# -- Test 3: modular_split + rationale → PASS --

def test_modular_split_with_rationale(tmp_path):
    _make_l8(tmp_path)
    _make_l9(tmp_path, fsm_topology="modular_split",
             rationale="explicit pipeline parallelism for high-bw design")
    _modular_3_fsm_design(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 2  # skip — engineer override
    rpt = _load_report(tmp_path)
    assert rpt["summary"]["fsm_topology_declared"] == "modular_split"


# -- Test 4: modular_split without rationale → WARN --

def test_modular_split_without_rationale(tmp_path):
    _make_l8(tmp_path)
    _make_l9(tmp_path, fsm_topology="modular_split")  # no rationale
    _modular_3_fsm_design(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0  # WARN, not ERROR
    rpt = _load_report(tmp_path)
    rules = [f["rule"] for f in rpt["findings"]]
    assert "MODULAR_SPLIT_WITHOUT_RATIONALE" in rules


# -- Test 5: 1 orchestration FSM only (PHY-style) → PASS --

def test_single_orchestration_fsm(tmp_path):
    _make_l8(tmp_path)
    # one orchestration FSM module
    _write_rtl(tmp_path, "ctrl.sv",
               _FSM_MOD_TEMPLATE.format(name="ctrl", pulse="cmd_pass"))
    # plus a PHY-only module: has always_ff but NO orchestration tokens,
    # NO state case decode → must NOT count as orchestration.
    _write_rtl(tmp_path, "rx_phy.sv", """\
module rx_phy (input logic clk, input logic rstn,
               output logic rx_byte_vld, output logic [7:0] rx_byte);
  always_ff @(posedge clk or negedge rstn) begin
    if (!rstn) rx_byte_vld <= 1'b0;
    else rx_byte_vld <= 1'b1;
  end
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0  # PASS clean (1 orch module < 3)
    rpt = _load_report(tmp_path)
    assert len(rpt["summary"]["modules_with_protocol_state"]) == 1
    assert len(rpt["findings"]) == 0


# -- Test 6: 3 orchestration FSMs with pulses → WARN --

def test_modular_3_fsm_with_pulses(tmp_path):
    _make_l8(tmp_path)
    _modular_3_fsm_design(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0  # WARN, not ERROR
    rpt = _load_report(tmp_path)
    rules = [f["rule"] for f in rpt["findings"]]
    assert "MODULAR_PROTOCOL_FSM_RACE_RISK" in rules
    assert len(rpt["summary"]["modules_with_protocol_state"]) >= 3


# -- Test 7: --strict upgrades WARN → ERROR --

def test_strict_upgrades_to_error(tmp_path):
    _make_l8(tmp_path)
    _modular_3_fsm_design(tmp_path)
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1  # ERROR


# -- Test 8: JSON report shape --

def test_json_report_shape(tmp_path):
    _make_l8(tmp_path)
    _modular_3_fsm_design(tmp_path)
    _run(tmp_path)
    rpt = _load_report(tmp_path)
    assert "program" in rpt
    assert rpt["program"] == "protocol_fsm_topology_check"
    assert "summary" in rpt
    assert "findings" in rpt
    assert "is_protocol_ip" in rpt["summary"]
    assert "modules_with_protocol_state" in rpt["summary"]
    assert "cross_module_pulse_outputs" in rpt["summary"]


# -- Test 9: PHY-only design (always_ff present but no orchestration) → PASS --

def test_phy_only_no_orchestration(tmp_path):
    _make_l8(tmp_path)
    # 4 PHY-style modules, none qualifying as orchestration FSM (no
    # cmd_pass / dispatcher_busy / set_awake tokens, no FSM state case).
    for i in range(4):
        _write_rtl(tmp_path, f"phy{i}.sv", f"""\
module phy{i} (input logic clk, input logic rstn,
               output logic tx_done);
  always_ff @(posedge clk or negedge rstn) begin
    if (!rstn) tx_done <= 1'b0;
    else tx_done <= 1'b1;
  end
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert len(rpt["summary"]["modules_with_protocol_state"]) == 0
    assert len(rpt["findings"]) == 0
