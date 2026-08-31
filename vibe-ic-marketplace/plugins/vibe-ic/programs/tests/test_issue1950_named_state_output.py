"""Issue #1950: named FSM states own their one-cycle protocol outputs.

The fixtures are deliberately synthetic and chip-agnostic.  They exercise the
three observable phases an external consumer sees: before entry, the complete
named-state cycle, and the following cycle.  The generated-clock fixtures also
separate data preparation from the edge that makes the data observable.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import json
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

try:
    import fsm_state_output_check as state_output_check  # noqa: E402
except ModuleNotFoundError:  # The origin/main control intentionally lacks it.
    state_output_check = None
import fsm_table_rtl_gen as rtl_gen  # noqa: E402
import spec_fsm_extract  # noqa: E402

BENCHMARK = PROGRAMS.parent / "benchmark"
sys.path.insert(0, str(BENCHMARK))
import cvdp_gate  # noqa: E402


STATE_SPEC = """
The controller has states IDLE, FIRE, and DONE.
In the IDLE state, when `go` is high, transition to FIRE.
In the FIRE state, transition to DONE.
In the DONE state, transition to IDLE.

## FIRE State
The controller sets `event_pulse` high for exactly one clock cycle.
The controller sets `error_pulse` high for one cycle.
"""


def test_extracts_one_cycle_outputs_owned_by_named_state():
    items = spec_fsm_extract.extract(STATE_SPEC)
    got = {
        (item.get("state"), item.get("signal"))
        for item in items
        if item["kind"] == "fsm_state_output"
    }
    assert got == {("FIRE", "event_pulse"), ("FIRE", "error_pulse")}
    for item in items:
        if item["kind"] == "fsm_state_output":
            assert item["duration_cycles"] == 1
            assert item["asserted_value"] == 1
            assert item["coverage_tokens"] == [item["state"], item["signal"]]


def test_one_cycle_output_without_a_named_owner_is_not_fabricated():
    prompt = """
The controller has states IDLE and RUN.
In IDLE, transition to RUN.  In RUN, transition to IDLE.
`done` pulses high for one cycle when the operation finishes.
"""
    items = spec_fsm_extract.extract(prompt)
    assert not [i for i in items if i["kind"] == "fsm_state_output"]


def _state_owned_spec():
    return {
        "module": "pulse_controller",
        "kind": "moore_seq",
        "clk": "clk",
        "input": "go",
        "reset": {
            "name": "rst",
            "mode": "async",
            "polarity": "high",
            "to": "IDLE",
        },
        "encoding": {"IDLE": 0, "FIRE": 1, "DONE": 2},
        "transitions": {
            "IDLE": {"0": "IDLE", "1": "FIRE"},
            "FIRE": {"0": "DONE", "1": "DONE"},
            "DONE": {"0": "IDLE", "1": "IDLE"},
        },
        "state_outputs": {
            "event_pulse": ["FIRE"],
            "error_pulse": ["FIRE"],
        },
    }


def test_generator_uses_named_state_decode_with_default_deassertion():
    rtl = rtl_gen.generate(_state_owned_spec())
    assert "output       event_pulse" in rtl
    assert "output       error_pulse" in rtl
    assert "assign event_pulse = (state == FIRE);" in rtl
    assert "assign error_pulse = (state == FIRE);" in rtl
    assert "event_pulse <=" not in rtl
    assert "error_pulse <=" not in rtl


@pytest.mark.skipif(not shutil.which("iverilog") or not shutil.which("vvp"),
                    reason="iverilog/vvp not installed")
def test_generated_microtest_samples_entry_owned_and_following_cycles(tmp_path):
    rtl = rtl_gen.generate(_state_owned_spec())
    dut = tmp_path / "dut.sv"
    dut.write_text(rtl)
    tb = tmp_path / "tb.sv"
    tb.write_text(r"""
module tb;
  reg clk = 0;
  reg rst = 0;
  reg go = 0;
  wire event_pulse;
  wire error_pulse;
  pulse_controller dut(.*);
  always #5 clk = ~clk;

  task check_phase;
    input expected;
    input [8*24-1:0] phase;
    begin
      #1;
      if (event_pulse !== expected || error_pulse !== expected) begin
        $display("FAIL %0s event=%b error=%b expected=%b",
                 phase, event_pulse, error_pulse, expected);
        $fatal(1);
      end
    end
  endtask

  initial begin
    #1; rst = 1;
    #1; rst = 0;
    @(negedge clk); go = 0;
    @(posedge clk); check_phase(0, "before-entry");
    @(negedge clk); go = 1;
    @(posedge clk); check_phase(1, "state-owned-cycle");
    @(negedge clk); go = 0;
    @(posedge clk); check_phase(0, "following-cycle");
    $display("PASS entry/state/following");
    $finish;
  end
endmodule
""")
    out = tmp_path / "sim.out"
    comp = subprocess.run(
        ["iverilog", "-g2012", "-s", "tb", "-o", str(out), str(dut), str(tb)],
        capture_output=True,
        text=True,
    )
    assert comp.returncode == 0, comp.stderr
    run = subprocess.run(["vvp", str(out)], capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "PASS entry/state/following" in run.stdout


BAD_TRANSITION_PULSE = r"""
module pulse_controller(input clk, input rst, input go, output reg event_pulse);
  localparam IDLE = 2'd0, FIRE = 2'd1, DONE = 2'd2;
  reg [1:0] state;
  always @(posedge clk or posedge rst) begin
    if (rst) begin
      state <= IDLE;
      event_pulse <= 1'b0;
    end else begin
      event_pulse <= 1'b0;
      case (state)
        IDLE: if (go) begin
          event_pulse <= 1'b1;
          state <= FIRE;
        end
        FIRE: state <= DONE;
        DONE: state <= IDLE;
        default: state <= IDLE;
      endcase
    end
  end
endmodule
"""


GOOD_STATE_OWNED_PULSE = r"""
module pulse_controller(input clk, input rst, input go, output event_pulse);
  localparam IDLE = 2'd0, FIRE = 2'd1, DONE = 2'd2;
  reg [1:0] state, next_state;
  assign event_pulse = (state == FIRE);
  always @(*) begin
    next_state = state;
    case (state)
      IDLE: if (go) next_state = FIRE;
      FIRE: next_state = DONE;
      DONE: next_state = IDLE;
      default: next_state = IDLE;
    endcase
  end
  always @(posedge clk or posedge rst)
    if (rst) state <= IDLE; else state <= next_state;
endmodule
"""


def test_transition_arm_pulse_is_rejected_but_state_decode_passes():
    assert state_output_check is not None
    bad, bad_status = state_output_check.check_text(
        BAD_TRANSITION_PULSE, STATE_SPEC)
    assert bad_status == "CHECKED"
    assert {(f.rule, f.signal, f.state) for f in bad} == {
        ("fsm-state-output-transition-owned", "event_pulse", "FIRE")
    }

    good, good_status = state_output_check.check_text(
        GOOD_STATE_OWNED_PULSE, STATE_SPEC)
    assert good_status == "CHECKED"
    assert good == []


STROBE_SPEC = """
The controller has states IDLE, PREPARE, and TOGGLE.
In IDLE, transition to PREPARE. In PREPARE, transition to TOGGLE.
In TOGGLE, transition to IDLE.
During TOGGLE, raise `serial_clk`; external logic samples `serial_data` and
`bits_left` on the rising edge of `serial_clk`. `serial_data` and `bits_left`
must be stable before that observable edge.
"""


BAD_STROBE = r"""
module serial_source(input clk, input rst, output reg serial_clk,
                     output reg serial_data, output reg [4:0] bits_left);
  localparam IDLE=0, PREPARE=1, TOGGLE=2;
  reg [1:0] state;
  always @(posedge clk) begin
    case (state)
      IDLE: state <= PREPARE;
      PREPARE: state <= TOGGLE;
      TOGGLE: begin
        serial_clk <= 1'b1;
        serial_data <= ~serial_data;
        bits_left <= bits_left - 1'b1;
        state <= IDLE;
      end
    endcase
  end
endmodule
"""


GOOD_STROBE = r"""
module serial_source(input clk, input rst, output reg serial_clk,
                     output reg serial_data, output reg [4:0] bits_left);
  localparam IDLE=0, PREPARE=1, TOGGLE=2;
  reg [1:0] state;
  always @(posedge clk) begin
    case (state)
      IDLE: begin serial_clk <= 1'b0; state <= PREPARE; end
      PREPARE: begin
        serial_data <= ~serial_data;
        bits_left <= bits_left - 1'b1;
        state <= TOGGLE;
      end
      TOGGLE: begin serial_clk <= 1'b1; state <= IDLE; end
    endcase
  end
endmodule
"""


def test_generated_strobe_data_and_status_are_prepared_before_edge():
    assert state_output_check is not None
    bad, status = state_output_check.check_text(BAD_STROBE, STROBE_SPEC)
    assert status == "CHECKED"
    assert {(f.rule, f.signal) for f in bad} == {
        ("generated-strobe-data-not-prepared", "serial_data"),
        ("generated-strobe-data-not-prepared", "bits_left"),
    }

    good, good_status = state_output_check.check_text(GOOD_STROBE, STROBE_SPEC)
    assert good_status == "CHECKED"
    assert good == []


def test_sole_emit_surfaces_guard_advisory_without_unmeasured_blocking():
    assert hasattr(cvdp_gate, "fsm_state_output_gate_record")
    ok, note = cvdp_gate.fsm_state_output_gate_record(
        "synthetic", BAD_TRANSITION_PULSE, STATE_SPEC)
    assert ok is False
    assert note.startswith("fsm-state-output FAIL:")

    source = Path(cvdp_gate.__file__).read_text()
    assert "[ADVISORY — passing_302 had zero applicable contracts]" in source
    assert "if not _b7_ok:" not in source


def test_capture_routes_program_and_expert_assets_hold_the_same_contract():
    plugin = PROGRAMS.parent
    routing = json.loads((plugin / "benchmark/CAPTURE_ROUTING.json").read_text())
    related = routing["steps"]["phase2.rtl_gen"]["bucket_A_related"]
    assert "programs/fsm_state_output_check.py" in related
    assert "programs/fsm_table_rtl_gen.py" in related
    assert "programs/spec_fsm_extract.py" in related

    db = json.loads((plugin / "agents/ic_expert_db/ic_expert_db.json").read_text())
    assert db["classes"] == len(db["entries"])
    assert db["total_lessons"] == sum(
        len(entry.get("lessons", [])) for entry in db["entries"])
    lessons = "\n".join(
        lesson for entry in db["entries"] for lesson in entry.get("lessons", []))
    assert "one-hot combinational decode of registered CURRENT state" in lessons
    assert "PREPARE phase" in lessons

    agent = (plugin / "agents/ic-expert-agent.md").read_text()
    assert "### Skill: named-state protocol outputs" in agent
    assert "before entry (low)" in agent
    assert "stable BEFORE a generated clock/strobe rises" in agent
