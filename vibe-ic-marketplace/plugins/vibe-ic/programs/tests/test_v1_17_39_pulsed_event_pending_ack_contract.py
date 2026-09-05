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
import re
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


@pytest.mark.skipif(not shutil.which("iverilog"), reason=(
    "NOT MEASURED HERE: no iverilog on PATH, so the ONLY executable proof that the "
    "pulse survives unacked, that starvation asserts at the declared deadline, that "
    "ack clears both, and that a request coincident with an ack is not dropped did "
    "NOT run. Everything else in this file is textual. Measured in the pinned image, "
    "where it passes -- a green run WITHOUT this line is weaker evidence than it looks."))
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


# --------------------------------------------------------------------------
# 6. the ORDINARY Phase-2 runner path, pinned
#
# `deterministic_rtl_dispatcher` is only half the front door. The other half is
# `design_one_shot_runner`, which looks for a project-shipped structured spec at
# a fixed list of conventional locations and routes it through that dispatcher
# with NO LLM. This pins both halves together: a spec dropped where the runner
# actually looks, carrying nothing but the design's own declaration, produces
# the pending/starvation structure. No harness, no benchmark name, no design id.
#
# SCOPE, stated honestly: this is reached when a project SHIPS a structured spec.
# Nothing in the plugin extracts an `events` contract out of PROSE today — and
# nothing extracts the pre-existing `state_outputs` field out of prose either, so
# that limitation is the shape of the existing spec-delivery architecture rather
# than anything this contract introduced. See LAND.md, finding CZ2035-N6.
# --------------------------------------------------------------------------
RUNNER = Path(__file__).parent.parent / "design_one_shot_runner.py"


def _runner_spec_locations():
    """The conventional spec paths, read out of the runner's own source."""
    src = RUNNER.read_text()
    m = re.search(r"for cand in \((.*?)\):", src, re.S)
    assert m, "the runner's spec-location list moved; this test must follow it"
    return re.findall(r'"([^"]+rtl_spec\.[a-z]+)"', m.group(1))


def test_the_runner_looks_where_a_shipped_spec_would_be():
    locs = _runner_spec_locations()
    assert "phase2/stage1/rtl_spec.json" in locs, locs
    assert len(locs) >= 4, locs


def test_a_shipped_spec_at_the_runners_own_location_gets_the_contract(tmp_path):
    """End to end over the two halves of the ordinary path, with no harness."""
    loc = _runner_spec_locations()[0]
    p = tmp_path / loc
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(PULSED))
    out = tmp_path / "out.sv"
    r = subprocess.run([sys.executable, str(DISPATCH), str(p), "-o", str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    rtl = out.read_text()
    assert "reg pending_irq_a;" in rtl
    assert "assign starved_a = pending_irq_a && (wait_irq_a == 5'd16);" in rtl
    assert "pending_irq_b" not in rtl      # the level control still holds here


# --------------------------------------------------------------------------
# 7. the COMPATIBILITY change this contract makes, stated and bounded
#
# Adding `events` RESERVES that key name. A spec that previously carried an
# `events` key meaning something else was silently ignored and generated RTL;
# it now REFUSES. Measured against the base program: rc 0 -> rc 1.
#
# That direction is deliberate. Fail-closed on a key whose meaning is now
# defined beats emitting RTL that quietly ignores something the design said,
# and it matches the doctrine the neighbouring solvers already follow
# (`full_moore_fsm_synth` returns None unless everything is unambiguous;
# `register_bus_driver_gen` refuses with a reason rather than guessing).
#
# But the blast radius has to be EXACTLY one key, not a general tightening, so
# both halves are pinned here. No spec shipped anywhere in this repo carries an
# `events` key, so nothing in-tree is affected. See LAND.md, finding CZ2035-N8.
# --------------------------------------------------------------------------
def test_a_foreign_events_key_refuses_instead_of_being_silently_ignored(tmp_path):
    r, _ = _run(tmp_path, dict(BASE, events=["some", "unrelated", "list"]))
    assert r.returncode == 1
    assert "events must be an event-to-contract mapping" in r.stderr


def test_unrelated_unknown_keys_are_still_ignored(tmp_path):
    """The bound on the change: validation did NOT become globally strict.
    A spec carrying arbitrary extra keys still generates, byte-identically."""
    plain = _run(tmp_path, BASE)[1]
    extra = _run(tmp_path, dict(BASE, notes="free-form", author="someone",
                                revision=7))
    assert extra[0].returncode == 0, extra[0].stderr
    assert extra[1] == plain, "an unrelated key changed the emitted RTL"


# --------------------------------------------------------------------------
# 8. the runner step EXECUTED, not read
#
# The pins above assert that the wiring exists by reading source. This RUNS it:
# `design_one_shot_runner._try_deterministic_rtl_dispatch` is the actual Phase-2
# step, handed an ordinary project directory containing nothing but a spec, with
# no harness, no scorer, no benchmark name and no design id. It must return PASS
# and leave RTL carrying the contract on disk.
# --------------------------------------------------------------------------
def test_the_runner_step_executes_and_emits_the_contract(tmp_path):
    sys.path.insert(0, str(SCRIPT.parent))
    import design_one_shot_runner as R

    (tmp_path / "phase2" / "stage1").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl_spec.json").write_text(json.dumps(PULSED))

    res = R._try_deterministic_rtl_dispatch(tmp_path, 0.0)
    assert res is not None, "the runner step did not fire on a shipped spec"
    assert getattr(res, "status", None) == "PASS", getattr(res, "detail", res)

    emitted = list(tmp_path.rglob("*.sv"))
    assert len(emitted) == 1, emitted
    rtl = emitted[0].read_text()
    assert "reg pending_irq_a;" in rtl
    assert "assign starved_a = pending_irq_a && (wait_irq_a == 5'd16);" in rtl
    assert "pending_irq_b" not in rtl      # the level control survives the real step


# --------------------------------------------------------------------------
# 9. CROSS-EVENT CONFLICTS and an unbounded deadline
#
# Both found by auditing my own emitter, not by a failing test.
#
# Two events naming the same `starvation_out` produced TWO continuous
# assignments on one wire. That is legal Verilog -- iverilog compiles it without
# a word -- and it resolves to X the moment the two disagree. Measured: with e1
# starved and e2 idle the output read `x`, so a genuinely starved event reports
# an unusable value and NOTHING anywhere says so. That is the exact defect class
# this contract exists to remove, reintroduced by the fix for it.
#
# An unbounded `deadline` sized the wait counter, so an absurd value emitted a
# several-hundred-bit register no synthesiser would take.
#
# A SHARED ACK is deliberately still allowed: one acknowledgment clearing
# several pending events is a real design and nothing is driven by it.
# --------------------------------------------------------------------------
def test_two_events_cannot_drive_one_starvation_output(tmp_path):
    r, _ = _run(tmp_path, dict(BASE, events={
        "e1": {"kind": "pulse", "ack": "a1", "deadline": 4, "starvation_out": "same"},
        "e2": {"kind": "pulse", "ack": "a2", "deadline": 4, "starvation_out": "same"}}))
    assert r.returncode == 1
    assert "both drive starvation output 'same'" in r.stderr


def test_a_starvation_output_cannot_also_be_a_request_input(tmp_path):
    r, _ = _run(tmp_path, dict(BASE, events={
        "e1": {"kind": "pulse", "ack": "a1", "deadline": 4, "starvation_out": "e2"},
        "e2": {"kind": "level"}}))
    assert r.returncode == 1
    assert "also an event request input" in r.stderr


def test_a_starvation_output_cannot_also_be_an_acknowledgment(tmp_path):
    r, _ = _run(tmp_path, dict(BASE, events={
        "e1": {"kind": "pulse", "ack": "a1", "deadline": 4, "starvation_out": "a2"},
        "e2": {"kind": "pulse", "ack": "a2"}}))
    assert r.returncode == 1
    assert "acknowledgment of" in r.stderr


def test_an_unimplementable_deadline_is_refused(tmp_path):
    r, _ = _run(tmp_path, dict(BASE, events={
        "e": {"kind": "pulse", "ack": "a", "deadline": 10 ** 60,
              "starvation_out": "s"}}))
    assert r.returncode == 1
    assert "is not a wait bound" in r.stderr


def test_a_shared_acknowledgment_is_still_allowed(tmp_path):
    """The CONTROL on the rule above: one ack clearing several pending events is
    a legitimate architecture and must not be swept up by the conflict check."""
    r, rtl = _run(tmp_path, dict(BASE, events={
        "e1": {"kind": "pulse", "ack": "ack", "deadline": 4, "starvation_out": "s1"},
        "e2": {"kind": "pulse", "ack": "ack", "deadline": 4, "starvation_out": "s2"}}))
    assert r.returncode == 0, r.stderr
    assert "assign s1 =" in rtl and "assign s2 =" in rtl
    assert rtl.count("  input        ack,") == 1, "the shared ack is declared twice"


@pytest.mark.skipif(not shutil.which("iverilog"), reason=(
    "NOT MEASURED HERE: no iverilog on PATH, so the elaboration half of the one-driver-per-starvation-output check did NOT run; only the textual assert-count "
    "half did. Measured in the pinned image, where it passes."))
def test_each_starvation_output_has_exactly_one_driver(tmp_path):
    """Structural guarantee, checked on emitted RTL that actually elaborates."""
    _, rtl = _run(tmp_path, dict(BASE, events={
        "e1": {"kind": "pulse", "ack": "a1", "deadline": 4, "starvation_out": "s1"},
        "e2": {"kind": "pulse", "ack": "a2", "deadline": 8, "starvation_out": "s2"}}))
    for sig in ("s1", "s2"):
        assert rtl.count(f"assign {sig} =") == 1, f"{sig} has multiple drivers"
    (tmp_path / "d.sv").write_text(rtl)
    c = subprocess.run(["iverilog", "-g2012", "-o", str(tmp_path / "s"),
                        str(tmp_path / "d.sv")], capture_output=True, text=True)
    assert c.returncode == 0, c.stderr


# --------------------------------------------------------------------------
# 10. an event may not take the module's OWN port name
#
# An event named `clk` emitted a SECOND `input clk` in the same header. iverilog
# rejects it outright ("clk definition conflicts with definition at ..."), so the
# generator was producing RTL that cannot elaborate instead of saying what was
# wrong. Loud rather than silent, unlike the rest of this audit series, but still
# the generator's job to catch.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["clk", "rst_n", "in", "out"])
def test_an_event_cannot_take_the_modules_own_port_name(tmp_path, name):
    r, _ = _run(tmp_path, dict(BASE, events={name: {"kind": "level"}}))
    assert r.returncode == 1
    assert "collides with the module's own port" in r.stderr


def test_an_ordinary_event_name_is_unaffected(tmp_path):
    """CONTROL: the rule is about the module's ports, not about event names."""
    r, rtl = _run(tmp_path, dict(BASE, events={
        "irq": {"kind": "pulse", "ack": "ack", "deadline": 4,
                "starvation_out": "starved"}}))
    assert r.returncode == 0, r.stderr
    assert rtl.count("  input        irq,") == 1


def test_the_deadline_bound_is_exact_at_its_edge(tmp_path):
    """OFF-BY-ONE CONTROL on the bound itself.

    The refusal test uses 10**60 and the working tests use 16, so the BOUND was
    never pinned: it could be moved to any value between and every test would
    still pass, silently over-refusing real designs. A bound needs its edge
    tested from both sides, not just a far-outside and a far-inside case."""
    import fsm_table_rtl_gen as G
    # The bound's VALUE is asserted, not just read. Measured: reading it from
    # the module made this test move WITH the constant, so shifting the bound by
    # one changed nothing and the test still passed -- it pinned the boundary
    # SEMANTICS (it does catch `>` becoming `>=`) but not the boundary VALUE.
    # A bound that nobody has written down can drift to any value silently.
    assert G._EVENT_DEADLINE_MAX == (1 << 32) - 1, (
        "the wait-bound limit moved; that is a deliberate decision and this "
        "test is where it gets recorded")
    limit = G._EVENT_DEADLINE_MAX
    ok, _ = _run(tmp_path, dict(BASE, events={
        "e": {"kind": "pulse", "ack": "a", "deadline": limit,
              "starvation_out": "s"}}))
    assert ok.returncode == 0, f"the bound itself was refused: {ok.stderr}"
    over, _ = _run(tmp_path, dict(BASE, events={
        "e": {"kind": "pulse", "ack": "a", "deadline": limit + 1,
              "starvation_out": "s"}}))
    assert over.returncode == 1
    assert "is not a wait bound" in over.stderr
