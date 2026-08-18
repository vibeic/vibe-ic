#!/usr/bin/env python3
"""Tests for spec_fsm_extract.extract — PROGRAM-FIRST structural extractor for
CVDP FSM-transition specs (fsm_state + fsm_transition items).

Covers (per the deliverable contract):
  (a) POSITIVE — a real state+transition block embedded VERBATIM from a prompt
      (the concatenate / enhanced_fsm_signal_processor IDLE/PROCESS/READY/FAULT
      FSM, plus the sprite enum) -> the states + transitions extract;
  (b) §4.05 NEGATIVE — "implement a state machine" with NO enumerated states /
      no explicit transition -> [];
  (c) chip-AGNOSTIC rename invariance — renaming the states preserves the FSM
      shape (count of states + transitions unchanged), proving the extractor
      keys on STRUCTURE, not a problem id or a specific state name;
  (d) extra structural guards: the contract dict shape, the >=2-state / >=1-edge
      gate, and the no-leak guard that document/port tokens never become states.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spec_fsm_extract import extract  # noqa: E402


def _states(items):
    return [it for it in items if it["kind"] == "fsm_state"]


def _transitions(items):
    return [it for it in items if it["kind"] == "fsm_transition"]


def _state_names(items):
    return {it["state"] for it in _states(items)}


# ---------------------------------------------------------------------------
# (a) POSITIVE — a real state + transition block embedded VERBATIM.
# Source: cvdp_copilot_concatenate_0001 (enhanced_fsm_signal_processor). The
# `o_fsm_status` encoding list `IDLE(00), PROCESS(01), READY(10), FAULT(11)` is
# the state set; the per-state "transitions to FAULT" / "transition to PROCESS"
# prose are the edges.
# ---------------------------------------------------------------------------
CONCATENATE_FSM_VERBATIM = """\
- `o_fsm_status`(2 bits): Current FSM state, encoded as a 2-bit signal, \
representing one of the FSM states: IDLE(00), PROCESS(01), READY(10), or \
FAULT(11). Default is IDLE.

## **FSM States and Functionality**

### **States**
1. **IDLE**:
   - Default state.
   - FSM waits for `i_enable` to assert high to transition to PROCESS.
   - If `i_fault` is detected, FSM transitions to FAULT.

2. **PROCESS**:
   - Concatenates six 5-bit input vectors into a single 30-bit bus.
   - If `i_fault` is detected during this state, FSM transitions to FAULT.

3. **READY**:
   - Indicates processing is complete by asserting `o_ready`.
   - FSM waits for `i_ack` to transition back to IDLE.

4. **FAULT**:
   - Asserts `o_error` to indicate a fault condition.
   - FSM transitions to IDLE only when `i_clear` is asserted and `i_fault` is deasserted.
"""


def test_positive_concatenate_states_and_transitions():
    items = extract(CONCATENATE_FSM_VERBATIM)
    # all four named states extract, from the encoding + the section headers
    assert _state_names(items) == {"IDLE", "PROCESS", "READY", "FAULT"}
    # the stated edges extract (at least the four explicit ones below)
    edges = {(it["state"], it["next_state"]) for it in _transitions(items)}
    assert ("IDLE", "PROCESS") in edges        # "transition to PROCESS"
    assert ("IDLE", "FAULT") in edges          # "transitions to FAULT"
    assert ("PROCESS", "FAULT") in edges       # "transitions to FAULT" in PROCESS
    assert ("READY", "IDLE") in edges          # "transition back to IDLE"
    assert ("FAULT", "IDLE") in edges          # "transitions to IDLE only when..."
    # every emitted transition's endpoints are real states
    names = _state_names(items)
    for it in _transitions(items):
        if it["state"]:
            assert it["state"] in names
        assert it["next_state"] in names


# A second POSITIVE — a SystemVerilog state enum + markdown transition prose
# embedded VERBATIM from cvdp_copilot_sprite_0004. Proves the enum-block source
# and the "Moves to the **STATE** state" markdown transition both work.
SPRITE_FSM_VERBATIM = """\
## FSM States and Transitions

 typedef enum logic [2:0] {
       IDLE,
       INIT_WRITE,
       WRITE,
       INIT_READ,
       READ,
       WAIT,
       DONE
   } state_t;

### 1. **IDLE**
   - **Transition**:
     - Moves to `INIT_WRITE` on the next clock cycle after reset is deasserted.

### 2. **INIT_WRITE**
   - **Transition**:
     - Moves to the **WRITE** state.

### 3. **WRITE**
   - **Transition**:
     - Moves to the **INIT_READ** state when `addr_counter` equals `N_ROM - 1`.

### 7. **DONE**
   - **Transition**:
     - Returns to the **IDLE** state on the next clock cycle.
"""


def test_positive_sprite_enum_and_markdown_transitions():
    items = extract(SPRITE_FSM_VERBATIM)
    names = _state_names(items)
    # the seven enum members are the states (a config param like a counter is NOT)
    assert names == {"IDLE", "INIT_WRITE", "WRITE", "INIT_READ", "READ",
                     "WAIT", "DONE"}
    edges = {(it["state"], it["next_state"]) for it in _transitions(items)}
    assert ("IDLE", "INIT_WRITE") in edges
    assert ("INIT_WRITE", "WRITE") in edges
    assert ("WRITE", "INIT_READ") in edges
    assert ("DONE", "IDLE") in edges


# ---------------------------------------------------------------------------
# (b) §4.05 NEGATIVE — a vague "state machine" with NO enumerated states / no
# explicit transition fabricates nothing.
# ---------------------------------------------------------------------------
def test_negative_vague_state_machine_no_states():
    prompt = (
        "Design a divider module. The module performs iterative division "
        "controlled by an internal state machine. When asserted (0), the reset "
        "resets the internal state machine, outputs and registers to their "
        "initial states. Pipeline the iterations of calculation."
    )
    assert extract(prompt) == []


def test_negative_one_state_only():
    # a single named state with no second state and no transition is not an FSM
    prompt = ("The module has an IDLE state where it waits for input. "
              "No other states are defined.")
    assert extract(prompt) == []


def test_negative_two_states_but_no_transition():
    # two states stated, but NO explicit transition between them -> [] (the gate
    # requires >=1 explicit transition; a bare state list is not enough).
    prompt = ("The FSM has the following states:\n"
              "- `ALPHA`: the first phase.\n"
              "- `BETA`: the second phase.\n"
              "Each phase processes one word.")
    assert extract(prompt) == []


def test_negative_empty_and_blank():
    assert extract("") == []
    assert extract("   \n\t  ") == []


# ---------------------------------------------------------------------------
# (c) chip-AGNOSTIC rename invariance — renaming every state preserves the FSM
# shape. The extractor must key on STRUCTURE (state-name shape + transition
# grammar), not on a specific name or a problem id.
# ---------------------------------------------------------------------------
def test_chip_agnostic_rename_invariance():
    base = CONCATENATE_FSM_VERBATIM
    items_base = extract(base)
    n_states = len(_states(items_base))
    n_trans = len(_transitions(items_base))

    # rename the states to entirely different (but same-shaped) tokens
    renamed = (base
               .replace("IDLE", "WAIT_A")
               .replace("PROCESS", "RUN_B")
               .replace("READY", "DONE_C")
               .replace("FAULT", "ERR_D"))
    items_renamed = extract(renamed)

    assert len(_states(items_renamed)) == n_states
    assert len(_transitions(items_renamed)) == n_trans
    assert _state_names(items_renamed) == {"WAIT_A", "RUN_B", "DONE_C", "ERR_D"}
    # and the renamed edges mirror the originals (same topology)
    base_edges = {(it["state"], it["next_state"]) for it in _transitions(items_base)}
    ren_edges = {(it["state"], it["next_state"]) for it in _transitions(items_renamed)}
    name_map = {"IDLE": "WAIT_A", "PROCESS": "RUN_B", "READY": "DONE_C",
                "FAULT": "ERR_D"}
    mapped = {(name_map.get(s, s), name_map.get(d, d)) for (s, d) in base_edges}
    assert ren_edges == mapped


# ---------------------------------------------------------------------------
# (d) structural guards.
# ---------------------------------------------------------------------------
def test_contract_dict_shape():
    items = extract(CONCATENATE_FSM_VERBATIM)
    assert items, "expected a non-empty FSM"
    for it in items:
        assert it["kind"] in ("fsm_state", "fsm_transition")
        assert isinstance(it["requirement"], str) and it["requirement"]
        assert isinstance(it["evidence"], str) and it["evidence"]
        assert isinstance(it["coverage_tokens"], list) and it["coverage_tokens"]
        # transition-structured fields always present
        for k in ("state", "next_state", "condition"):
            assert k in it
    # a transition item always carries a real destination + a covering token
    for it in _transitions(items):
        assert it["next_state"]
        assert it["next_state"] in it["coverage_tokens"]


def test_no_leak_document_and_port_tokens_not_states():
    # a prompt with document-section bold headings + a `- `port`:` list, but a
    # genuine 2-state FSM. The headings/ports must NOT become states.
    prompt = """\
## **Interface**

### **Inputs**
- `clk`: clock.
- `rst`: reset.
- `start`: begin.

### **Outputs**
- `done`: completion flag.

## **State Machine**
The FSM operates between IDLE and BUSY states.
- When `start` is asserted, the FSM transitions to BUSY.
- When processing completes, the FSM returns to IDLE.
"""
    items = extract(prompt)
    names = _state_names(items)
    assert names == {"IDLE", "BUSY"}
    # none of the document/port tokens leaked as states
    for leak in ("Interface", "Inputs", "Outputs", "clk", "rst", "start",
                 "done"):
        assert leak not in names


def test_state_encoding_param_not_config_param():
    # a comma-chained localparam state encoding is split into states, while a
    # config-width parameter is NOT minted as a state.
    prompt = """\
## State Machine
localparam IDLE = 2'b00, RUN = 2'b01, STOP = 2'b10;
parameter WIDTH = 16;
- On `go`, the FSM transitions to RUN.
- When finished, the FSM transitions to STOP, then returns to IDLE.
"""
    items = extract(prompt)
    names = _state_names(items)
    assert "IDLE" in names and "RUN" in names and "STOP" in names
    assert "WIDTH" not in names


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
