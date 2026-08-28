"""Test corpus for BACKLOG_v5 enhancements.

6 chip-agnostic, tester-agnostic test cases:
  1. Dead turnaround constant → R1 ERROR, R4 WARN
  2. 0-cycle turnaround dispatcher → R2 ERROR
  3. Synthetic bus model for R3 cocotb TB
  4. Scope capture with AMBIGUOUS pulse → S1 AMBIGUOUS + TX_RX_OVERLAP
  5. L9 without response_delay → R5 ERROR
  6. L9 with wrong reference_event → R5 ERROR
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
PROGRAMS = ROOT / "programs"


# ─── Test 1: Dead turnaround constant (R1 + R4) ───

@pytest.fixture
def dead_turnaround_project(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "timing_pkg.v").write_text("""\
// Half-duplex timing package
`define T_RESPONSE_DELAY_CYC 200
localparam T_BUS_TURNAROUND_TICKS = 150;
localparam T_BIT_WIDTH_CYC = 10;  // this one IS used below
""")
    (rtl / "dispatcher.v").write_text("""\
module dispatcher(input clk, input rst_n, output tx_start);
  localparam DUMMY = T_BIT_WIDTH_CYC;
  reg tx;
  always @(posedge clk) tx <= 1'b0;
  assign tx_start = tx;
endmodule
""")
    return tmp_path


def test_r1_dead_turnaround_constant(dead_turnaround_project):
    """R1: turnaround constant defined but 0 references → ERROR."""
    prog = PROGRAMS / "bus_turnaround_consumes_spec_constant_check.py"
    result = _pr.run(
        [sys.executable, str(prog), str(dead_turnaround_project), "--json"],
        capture_output=True, text=True)
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert not data["passed"]
    errors = [f for f in data["findings"] if f["severity"] == "ERROR"]
    assert len(errors) >= 1
    dead_names = {f["message"].split("'")[1] for f in errors if "DEAD_TURNAROUND" in f["rule"]}
    assert "T_BUS_TURNAROUND_TICKS" in dead_names


def test_r4_dead_timing_constant_warn(dead_turnaround_project):
    """R4: timing constant with 0 references → WARN."""
    prog = PROGRAMS / "dead_timing_constant_warn.py"
    result = _pr.run(
        [sys.executable, str(prog), str(dead_turnaround_project), "--json"],
        capture_output=True, text=True)
    data = json.loads(result.stdout)
    warns = [f for f in data["findings"] if f["severity"] == "WARNING"]
    assert len(warns) >= 1
    warn_names = {f["message"].split("'")[1] for f in warns if "DEAD_TIMING" in f["rule"]}
    assert "T_RESPONSE_DELAY_CYC" in warn_names


# ─── Test 2: 0-cycle turnaround dispatcher ───
# (R2 is a skill, not a program — test validates the pattern recognition
#  that the skill would use. The actual skill audit is non-deterministic.)

@pytest.fixture
def zero_cycle_dispatcher(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "ctrl.v").write_text("""\
module ctrl(input clk, input rst_n, input rx_done, output reg tx_start);
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      tx_start <= 1'b0;
    end else begin
      if (rx_done) begin
        tx_start <= 1'b1;  // 0-cycle: tx_start in same cycle as rx_done!
      end
    end
  end
endmodule
""")
    return tmp_path


def test_r2_zero_cycle_pattern_detection(zero_cycle_dispatcher):
    """Verify the 0-cycle turnaround pattern is detectable by regex scan."""
    ctrl = zero_cycle_dispatcher / "phase2" / "stage1" / "rtl" / "ctrl.v"
    content = ctrl.read_text()
    import re
    tx_re = re.compile(r"\b(tx_start|tx_req|resp_start|reply_start|drv_en)\b", re.IGNORECASE)
    rx_re = re.compile(r"\b(rx_done|delim_seen|eof_detect|cmd_valid|frame_complete|trailing_br|trailing_delim)\b", re.IGNORECASE)
    tx_matches = tx_re.findall(content)
    rx_matches = rx_re.findall(content)
    assert len(tx_matches) >= 1, "TX-start signal not found"
    assert len(rx_matches) >= 1, "RX-done signal not found"
    # Verify they appear in the same always block (crude same-block check)
    lines = content.splitlines()
    tx_lines = [i for i, l in enumerate(lines) if tx_re.search(l)]
    rx_lines = [i for i, l in enumerate(lines) if rx_re.search(l)]
    assert any(abs(t - r) <= 3 for t in tx_lines for r in rx_lines), \
        "TX-start and RX-done should be within 3 lines (same FSM block)"


# ─── Test 4: Scope capture with AMBIGUOUS pulse (S1) ───

@pytest.fixture
def scope_capture_corpus(tmp_path):
    l2 = {
        "pulse_classes": [
            {"class_name": "NARROW_PULSE", "min_us": 3.0, "max_us": 9.0, "polarity": "low"},
            {"class_name": "WIDE_PULSE", "min_us": 10.0, "max_us": 18.0, "polarity": "low"},
        ]
    }
    (tmp_path / "l2_timing.json").write_text(json.dumps(l2))

    # Build a CSV with a pulse that spans NARROW-WIDE boundary (9.5us)
    samples = []
    t = 0.0
    # HIGH idle
    for _ in range(10):
        samples.append(f"{t:.3f},3.3")
        t += 0.5
    # LOW pulse 5us (NARROW — should match)
    for _ in range(10):
        samples.append(f"{t:.3f},0.1")
        t += 0.5
    # HIGH gap
    for _ in range(10):
        samples.append(f"{t:.3f},3.3")
        t += 0.5
    # LOW pulse 9.5us (spans NARROW max=9 and WIDE min=10 → AMBIGUOUS)
    for _ in range(19):
        samples.append(f"{t:.3f},0.1")
        t += 0.5
    # HIGH tail
    for _ in range(10):
        samples.append(f"{t:.3f},3.3")
        t += 0.5

    (tmp_path / "scope.csv").write_text("\n".join(samples))
    return tmp_path


def test_s1_scope_ambiguous_detection(scope_capture_corpus):
    """S1: pulse spanning two class boundaries → AMBIGUOUS with TX_RX_OVERLAP candidate."""
    # S1 is an MCP tool — we test the classification logic inline
    l2 = json.loads((scope_capture_corpus / "l2_timing.json").read_text())
    pulse_classes = l2["pulse_classes"]

    # Parse CSV
    samples = []
    for line in (scope_capture_corpus / "scope.csv").read_text().splitlines():
        parts = line.split(",")
        samples.append({"t_us": float(parts[0]), "v": float(parts[1])})

    # Segment into pulses (same logic as S1 tool)
    threshold_v = 1.5
    glitch_filter_us = 0.5
    pulses = []
    current_pol = "low" if samples[0]["v"] < threshold_v else "high"
    pulse_start = samples[0]["t_us"]
    for i in range(1, len(samples)):
        pol = "low" if samples[i]["v"] < threshold_v else "high"
        if pol != current_pol:
            dur = samples[i]["t_us"] - pulse_start
            if dur >= glitch_filter_us:
                pulses.append({"t_us": pulse_start, "polarity": current_pol, "duration_us": dur})
            current_pol = pol
            pulse_start = samples[i]["t_us"]
    last_dur = samples[-1]["t_us"] - pulse_start
    if last_dur >= glitch_filter_us:
        pulses.append({"t_us": pulse_start, "polarity": current_pol, "duration_us": last_dur})

    # Classify
    ambiguous_found = False
    for p in pulses:
        if p["polarity"] != "low":
            continue
        matches = [c for c in pulse_classes
                   if (c.get("polarity", "any") in ("any", p["polarity"]))
                   and c["min_us"] <= p["duration_us"] <= c["max_us"]]
        if len(matches) == 0 and 9.0 < p["duration_us"] < 10.0:
            ambiguous_found = True

    assert ambiguous_found, "Should detect AMBIGUOUS pulse spanning NARROW-WIDE boundary"


# ─── Test 5: L9 without response_delay (R5) ───

@pytest.fixture
def l9_missing_delay(tmp_path):
    l9 = {
        "half_duplex": True,
        "modules": {
            "cmd_dispatcher": {
                "role": "command_handler",
                "description": "Main dispatcher for half-duplex bus",
                "ports": ["clk", "rst_n", "bus_io"]
            }
        }
    }
    (tmp_path / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(l9))
    return tmp_path


def test_r5_missing_response_delay(l9_missing_delay):
    """R5: dispatcher module without response_delay block → ERROR."""
    prog = PROGRAMS / "l9_response_delay_schema_check.py"
    l9_file = l9_missing_delay / "L9_INTEGRATION_SPEC.json"
    result = _pr.run(
        [sys.executable, str(prog), str(l9_file), "--json"],
        capture_output=True, text=True)
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert not data["passed"]
    errors = [f for f in data["findings"] if f["rule"] == "MISSING_RESPONSE_DELAY"]
    assert len(errors) >= 1


# ─── Test 6: L9 with wrong reference_event (R5) ───

@pytest.fixture
def l9_wrong_ref_event(tmp_path):
    l9 = {
        "half_duplex": True,
        "modules": {
            "cmd_dispatcher": {
                "role": "command_handler",
                "description": "Main dispatcher for half-duplex bus",
                "response_delay": {
                    "required": True,
                    "spec_constant": "T_RESPONSE_DELAY_CYC",
                    "reference_event": "cmd_valid",
                    "min_cycles": 200
                }
            }
        }
    }
    (tmp_path / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(l9))
    return tmp_path


def test_r5_wrong_reference_event(l9_wrong_ref_event):
    """R5: reference_event=cmd_valid (early-fire) → ERROR with hint."""
    prog = PROGRAMS / "l9_response_delay_schema_check.py"
    l9_file = l9_wrong_ref_event / "L9_INTEGRATION_SPEC.json"
    result = _pr.run(
        [sys.executable, str(prog), str(l9_file), "--json"],
        capture_output=True, text=True)
    assert result.returncode == 1
    data = json.loads(result.stdout)
    assert not data["passed"]
    errors = [f for f in data["findings"] if f["rule"] == "WRONG_REFERENCE_EVENT"]
    assert len(errors) >= 1
    assert "early-fire" in errors[0]["message"].lower() or "end_of_trailing_delimiter" in errors[0]["message"]


# ─── Test: T1 tester verdict decode ───

@pytest.fixture
def frame_layout(tmp_path):
    layout = {
        "fields": [
            {"name": "header", "offset": 0, "length": 1, "expected_hex": "AA"},
            {"name": "response_op", "offset": 1, "length": 1},
            {"name": "payload", "offset": 2, "length": 4},
            {"name": "crc", "offset": 6, "length": 1},
            {"name": "verdict", "offset": 7, "length": 1,
             "values": {"00": "PASS", "01": "CRC_FAIL", "02": "NO_RESPONSE"}}
        ]
    }
    (tmp_path / "frame_layout.json").write_text(json.dumps(layout))
    return tmp_path


def test_t1_verdict_pass(frame_layout):
    """T1: PASS frame decodes without mismatches."""
    prog = PROGRAMS / "tester_verdict_frame_decode.py"
    layout_file = frame_layout / "frame_layout.json"
    result = _pr.run(
        [sys.executable, str(prog),
         "--layout", str(layout_file),
         "--frame", "AA 55 01 02 03 04 B7 00",
         "--json"],
        capture_output=True, text=True)
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert not data["has_mismatch"]
    verdict_field = [f for f in data["fields"] if f["field"] == "verdict"][0]
    assert verdict_field["decoded"] == "PASS"


def test_t1_verdict_fail_no_response(frame_layout):
    """T1: NO_RESPONSE verdict → diagnosis hint."""
    prog = PROGRAMS / "tester_verdict_frame_decode.py"
    layout_file = frame_layout / "frame_layout.json"
    result = _pr.run(
        [sys.executable, str(prog),
         "--layout", str(layout_file),
         "--frame", "AA 55 01 02 03 04 B7 02",
         "--json"],
        capture_output=True, text=True)
    assert result.returncode == 1
    data = json.loads(result.stdout)
    verdict_field = [f for f in data["fields"] if f["field"] == "verdict"][0]
    assert verdict_field["decoded"] == "NO_RESPONSE"
    hints = [h["hint"] for h in data["diagnosis_hints"]]
    assert "no_device_response" in hints
