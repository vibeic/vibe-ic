"""Typed pulsed-event contract in fsm_table_rtl_gen (issue #2035, family 2).

Defect class distilled: "pulsed interrupts disappear before acknowledgment;
waiting contenders never report starvation". Before this, a spec could STATE in
its own input that a request is pulsed and must be held until acknowledged, and
the generator emitted nothing at all for it — the capability lived only in a
human remembering the lesson.

The contract is read from the INPUT ONLY (§4.05): `kind`, `ack`, `deadline` and
`starvation_out` are all declared by the design. Nothing about pulse-vs-level is
inferred; an unstated field is REFUSED BY NAME so the interpretation is routed to
AI rather than guessed.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "fsm_table_rtl_gen.py"
DISPATCH = Path(__file__).parent.parent / "deterministic_rtl_dispatcher.py"
assert SCRIPT.exists() and DISPATCH.exists()

BASE = {
    "module": "irq_fsm", "kind": "moore_seq", "clk": "clk",
    "input": "in", "output": "out",
    "reset": {"name": "rst_n", "mode": "sync", "polarity": "low", "to": "IDLE"},
    "encoding": {"IDLE": 0, "SERVE": 1},
    "transitions": {"IDLE": {"0": "IDLE", "1": "SERVE"},
                    "SERVE": {"0": "IDLE", "1": "SERVE"}},
    "outputs": {"IDLE": 0, "SERVE": 1},
}

PULSED = dict(BASE, events={
    "irq_a": {"kind": "pulse", "ack": "ack_a",
              "deadline": 16, "starvation_out": "starved_a"},
    "irq_b": {"kind": "level"},
})


def _run(tmp_path, spec, script=None):
    p = tmp_path / "fsm.json"
    p.write_text(json.dumps(spec))
    out = tmp_path / "out.sv"
    r = subprocess.run([sys.executable, str(script or SCRIPT), str(p),
                        "-o", str(out)], capture_output=True, text=True)
    return r, (out.read_text() if out.exists() else "")


# --------------------------------------------------------------------------
# 1. the declared contract becomes STRUCTURE
# --------------------------------------------------------------------------
def test_pulsed_event_gets_pending_storage_held_until_ack(tmp_path):
    r, rtl = _run(tmp_path, PULSED)
    assert r.returncode == 0, r.stderr
    assert "reg pending_irq_a;" in rtl
    # set-dominant: a request coincident with an ack is retained, not dropped
    assert "pending_irq_a <= irq_a || (pending_irq_a && !ack_a);" in rtl


def test_declared_deadline_emits_bounded_starvation_report(tmp_path):
    _, rtl = _run(tmp_path, PULSED)
    assert "reg [4:0] wait_irq_a;" in rtl          # ceil(log2(16+1)) = 5 bits
    assert "assign starved_a = pending_irq_a && (wait_irq_a == 5'd16);" in rtl


def test_event_signals_become_ports(tmp_path):
    _, rtl = _run(tmp_path, PULSED)
    for port in ("  input        irq_a,", "  input        ack_a,",
                 "  input        irq_b,", "  output       starved_a"):
        assert port in rtl, port


# --------------------------------------------------------------------------
# 2. ALTERNATIVE-ARCHITECTURE CONTROL — a level request keeps its own topology
# --------------------------------------------------------------------------
def test_level_event_is_not_forced_into_pending_storage(tmp_path):
    """A source that HOLDS its request needs no capture register. The rule must
    fire on the DECLARED BEHAVIOUR, never on the word 'interrupt'."""
    _, rtl = _run(tmp_path, PULSED)
    assert "pending_irq_b" not in rtl
    assert "wait_irq_b" not in rtl
    assert "  input        irq_b," in rtl          # still wired, just not stored


def test_spec_with_no_events_is_byte_identical_to_before(tmp_path):
    """No events declared -> no change whatsoever to existing designs."""
    _, rtl = _run(tmp_path, BASE)
    assert "pending_" not in rtl and "wait_" not in rtl
    assert rtl.count("module irq_fsm (") == 1


# --------------------------------------------------------------------------
# 3. UNRESOLVED INTERPRETATION IS ROUTED, NEVER GUESSED
# --------------------------------------------------------------------------
@pytest.mark.parametrize("contract,needle", [
    ({"ack": "a1"},                                   "does not state 'kind'"),
    ({"kind": "pulse"},                               "names no 'ack'"),
    ({"kind": "pulse", "ack": "a1", "deadline": 8},   "names no 'starvation_out'"),
    ({"kind": "pulse", "ack": "a1",
      "starvation_out": "s1"},                        "no 'deadline'"),
    ({"kind": "edge"},                                "unknown kind"),
])
def test_unstated_field_is_refused_by_name(tmp_path, contract, needle):
    r, _ = _run(tmp_path, dict(BASE, events={"e1": contract}))
    assert r.returncode == 1, r.stdout
    assert needle in r.stderr
    assert "e1" in r.stderr          # the refusal NAMES the event


def test_events_on_a_clockless_fsm_are_refused(tmp_path):
    spec = {k: v for k, v in BASE.items() if k not in ("reset", "clk")}
    spec["kind"] = "moore_comb"
    spec["events"] = {"e1": {"kind": "pulse", "ack": "a1"}}
    r, _ = _run(tmp_path, spec)
    assert r.returncode == 1
    assert "events require a clocked FSM" in r.stderr


def test_event_signal_colliding_with_a_state_is_refused(tmp_path):
    r, _ = _run(tmp_path, dict(BASE, events={
        "IDLE": {"kind": "pulse", "ack": "a1"}}))
    assert r.returncode == 1
    assert "collides with a state name" in r.stderr


# --------------------------------------------------------------------------
# 4. REACHED THROUGH THE GENERAL FRONT DOOR — no harness, no design id
# --------------------------------------------------------------------------
def test_ordinary_phase1_spec_reaches_the_fix_through_the_dispatcher(tmp_path):
    p = tmp_path / "fsm.json"
    p.write_text(json.dumps(PULSED))
    out = tmp_path / "fd.sv"
    r = subprocess.run([sys.executable, str(DISPATCH), str(p), "-o", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "reg pending_irq_a;" in out.read_text()


def test_generation_is_deterministic(tmp_path):
    _, a = _run(tmp_path, PULSED)
    _, b = _run(tmp_path, PULSED)
    assert a == b


# --------------------------------------------------------------------------
# 5. the emitted RTL actually behaves (executable, not textual, evidence)
# --------------------------------------------------------------------------
TB = r'''
`timescale 1ns/1ps
module tb;
  reg clk=0, rst_n=0, in=0, irq_a=0, ack_a=0, irq_b=0;
  wire out, starved_a;
  integer i; integer errors=0;
  irq_fsm dut(.clk(clk),.rst_n(rst_n),.in(in),.out(out),
              .irq_a(irq_a),.ack_a(ack_a),.irq_b(irq_b),.starved_a(starved_a));
  always #5 clk = ~clk;
  initial begin
    @(negedge clk); rst_n=1;
    @(negedge clk); irq_a=1;
    @(negedge clk); irq_a=0;
    for (i=0;i<10;i=i+1) @(negedge clk);
    if (dut.pending_irq_a !== 1'b1) errors=errors+1;   // pulse lost before ack
    for (i=0;i<10;i=i+1) @(negedge clk);
    if (starved_a !== 1'b1) errors=errors+1;           // no starvation report
    ack_a=1; @(negedge clk); ack_a=0; @(negedge clk);
    if (dut.pending_irq_a !== 1'b0 || starved_a !== 1'b0) errors=errors+1;
    irq_a=1; ack_a=1; @(negedge clk); irq_a=0; ack_a=0; @(negedge clk);
    if (dut.pending_irq_a !== 1'b1) errors=errors+1;   // dropped on coincidence
    if (errors==0) $display("ALL_PASS"); else $display("ERRORS=%0d", errors);
    $finish;
  end
endmodule
'''


@pytest.mark.skipif(not shutil.which("iverilog"), reason="iverilog not installed")
def test_emitted_rtl_holds_the_pulse_and_reports_starvation(tmp_path):
    _, rtl = _run(tmp_path, PULSED)
    (tmp_path / "dut.sv").write_text(rtl)
    (tmp_path / "tb.v").write_text(TB)
    sim = tmp_path / "sim"
    c = subprocess.run(["iverilog", "-g2012", "-o", str(sim),
                        str(tmp_path / "dut.sv"), str(tmp_path / "tb.v")],
                       capture_output=True, text=True)
    assert c.returncode == 0, c.stderr
    r = subprocess.run([str(sim)], capture_output=True, text=True)
    assert "ALL_PASS" in r.stdout, r.stdout
