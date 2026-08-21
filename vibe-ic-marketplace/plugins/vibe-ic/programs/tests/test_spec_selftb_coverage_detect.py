#!/usr/bin/env python3
"""Tests for spec_selftb_coverage_detect — the self-TB coverage advisory."""
import importlib.util
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
_spec = importlib.util.spec_from_file_location(
    "spec_selftb_coverage_detect", _PROGRAMS / "spec_selftb_coverage_detect.py")
_M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_M)
detect = _M.detect_selftb_coverage


def test_handshake_fsm_shape():
    # signed_adder shape: a request/ready FSM
    p = ("The module has an input `i_start` and an output `o_ready`. After op1 "
         "completes, assert i_start again for one i_clk edge to start op2.")
    r = detect(p)
    assert "handshake_fsm" in r["shapes"]
    assert r["requirement"] and "BACK-TO-BACK" in r["requirement"]


def test_register_dynamic_shape():
    # axil_precision_counter shape: AXI-Lite peripheral with a running counter
    p = ("An AXI4-Lite peripheral. A countdown counter decrements every cycle "
         "while ctl[0]=1; elapsed increments after it hits 0. Read slv_reg via "
         "the AXI handshake.")
    r = detect(p)
    assert "register_dynamic" in r["shapes"]
    assert "ADVANCE SIMULATION TIME" in r["requirement"]


def test_interrupt_controller_shape():
    p = ("An interrupt controller. On cpu_ack, clear the serviced IRQ; "
         "cpu_interrupt must re-assert for remaining pending interrupts.")
    r = detect(p)
    assert "interrupt_controller" in r["shapes"]
    assert "RE-ASSERT" in r["requirement"]


def test_fsm_completion_shape():
    # binary_search_tree_sorting shape: complete a partial FSM/algorithm
    p = ("Complete the partial SystemVerilog code for a search module. The "
         "search process is controlled by an FSM traversing a sorted BST; "
         "output key_position on completion.")
    r = detect(p)
    assert "fsm_completion" in r["shapes"]
    assert "NON-DEGENERATE" in r["requirement"]


def test_completion_without_fsm_context_does_not_fire_completion():
    # a plain "complete the code" combinational block is NOT an fsm_completion
    p = ("Complete the SystemVerilog code for a 4-bit ripple-carry adder that "
         "outputs sum and carry. Purely combinational.")
    r = detect(p)
    assert "fsm_completion" not in r["shapes"]


def test_plain_combinational_prompt_does_not_fire():
    r = detect("Design a 2-to-1 multiplexer with select line s.")
    assert r["shapes"] == []
    assert r["requirement"] is None


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
