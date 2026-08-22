"""#120 — reset-alias residual: a NEUTRALIZED alias wrapper is unsafe as a
*direct* Verilator sim-bind top.

CONTEXT. v1.3.85/#115 keeps the `ifdef VERILATOR tri reset pull on the
OUTERMOST face only: chip_top keeps the copied pull; the INNER alias wrapper is
neutralized to plain port faces (its additive intent survives only as body
`tri0/tri1 <face>__rcvar_pull; nets + a port-direct `ifdef VERILATOR combine).
v1.3.88/#119 restores that pull on chip_top's OWN faces at re-emit. Both fix the
chip_top bind. RESIDUAL: a Verilator TB that direct-binds the neutralized
wrapper ITSELF (e.g. `seq_al`, not chip_top) still ties an unbound reset face to
0 -> active-low reset permanently asserted -> stuck in reset. We cannot re-pull
the inner wrapper (single on-disk artifact; re-pulling recreates the #115
two-level tri-port dead-reset for the primary chip_top bind), so the sound fix
is OPTION B: a DISCLOSED guard so a neutralized wrapper can never SILENTLY
become the Verilator bind top.

This test pins the pure guard/emitter string logic (no Verilator / no container).
"""
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import design_one_shot_runner as R          # noqa: E402


# The #115-neutralized shape: PLAIN reset port faces; the pull survives only as
# body `__rcvar_pull nets + the port-direct `ifdef VERILATOR combine arm.
_NEUTRALIZED_WRAPPER = """\
module counter (
    input clk,
    input
    resetn,
    input
    rst_n,
    output [7:0] cnt
);
`ifdef VERILATOR
    wire resetn__rcvar_net = resetn & rst_n;
`elsif YOSYS
    wire resetn__rcvar_net = resetn & rst_n;
`else
    tri1 resetn__rcvar_pull;
    tri1 rst_n__rcvar_pull;
    assign resetn__rcvar_pull = resetn;
    assign rst_n__rcvar_pull = rst_n;
    wire resetn__rcvar_net = resetn__rcvar_pull & rst_n__rcvar_pull;
`endif
    counter__rcvar_inner u_counter__rcvar_inner (
        .clk(clk),
        .resetn(resetn__rcvar_net),
        .cnt(cnt)
    );
endmodule
"""

# The pre-neutralize (safe) shape: the reset port faces STILL carry the
# `ifdef VERILATOR tri pull, so a direct Verilator bind is fine.
_SAFE_WRAPPER = """\
module counter (
    input clk,
    input
`ifdef VERILATOR
    tri1
`endif
    resetn,
    input
`ifdef VERILATOR
    tri1
`endif
    rst_n,
    output [7:0] cnt
);
`ifdef VERILATOR
    wire resetn__rcvar_net = resetn & rst_n;
`else
    tri1 resetn__rcvar_pull;
    tri1 rst_n__rcvar_pull;
    assign resetn__rcvar_pull = resetn;
    assign rst_n__rcvar_pull = rst_n;
    wire resetn__rcvar_net = resetn__rcvar_pull & rst_n__rcvar_pull;
`endif
    counter__rcvar_inner u_counter__rcvar_inner (.clk(clk),
        .resetn(resetn__rcvar_net), .cnt(cnt));
endmodule
"""

_PLAIN_MODULE = (
    "module counter (input clk, input resetn, output [7:0] cnt);\n"
    "endmodule\n")


# ---- _alias_wrapper_neutralized_reset_faces ----------------------------------

def test_detects_neutralized_reset_faces():
    faces = R._alias_wrapper_neutralized_reset_faces(
        _NEUTRALIZED_WRAPPER, "counter")
    assert faces == ["resetn", "rst_n"]


def test_safe_wrapper_is_not_neutralized():
    # Port faces still carry the VERILATOR tri pull -> safe -> None.
    assert R._alias_wrapper_neutralized_reset_faces(
        _SAFE_WRAPPER, "counter") is None


def test_plain_module_is_not_an_alias_wrapper():
    assert R._alias_wrapper_neutralized_reset_faces(
        _PLAIN_MODULE, "counter") is None


# ---- _alias_wrapper_vl_bind_guard_finding ------------------------------------

def test_finding_shape_for_neutralized_wrapper():
    f = R._alias_wrapper_vl_bind_guard_finding(
        _NEUTRALIZED_WRAPPER, "counter", "chip_top")
    assert f is not None
    assert f["kind"] == "neutralized_alias_wrapper_unsafe_as_vl_bind_top"
    assert f["issue"] == "#120"
    assert f["wrapper"] == "counter"
    assert f["reset_faces"] == ["resetn", "rst_n"]
    assert f["safe_vl_bind_top"] == "chip_top"
    # The whole point: iverilog is fine, Verilator is NOT.
    assert f["sim_bind_safe"] == {"iverilog": True, "verilator": False}
    assert "stuck" in f["message"].lower() or "reset" in f["message"].lower()
    # Machine-readable (JSON round-trips).
    assert json.loads(json.dumps(f)) == f


def test_finding_none_for_safe_wrapper():
    assert R._alias_wrapper_vl_bind_guard_finding(
        _SAFE_WRAPPER, "counter", "chip_top") is None


# ---- _alias_wrapper_unsafe_as_vl_bind_top (the reusable GUARD) ---------------

def test_guard_fires_when_wrapper_is_the_bind_top():
    f = R._alias_wrapper_unsafe_as_vl_bind_top(
        _NEUTRALIZED_WRAPPER, "counter", vl_bind_top="counter",
        chip_top_name="chip_top")
    assert f is not None
    assert f["wrapper"] == "counter"
    assert f["safe_vl_bind_top"] == "chip_top"


def test_guard_silent_when_chip_top_is_the_bind_top():
    # In-flow default: TBs bind chip_top, not the wrapper -> no false alarm.
    assert R._alias_wrapper_unsafe_as_vl_bind_top(
        _NEUTRALIZED_WRAPPER, "counter", vl_bind_top="chip_top",
        chip_top_name="chip_top") is None


def test_guard_silent_for_unrelated_bind_top():
    assert R._alias_wrapper_unsafe_as_vl_bind_top(
        _NEUTRALIZED_WRAPPER, "counter", vl_bind_top="some_other_top") is None


def test_guard_silent_when_wrapper_not_neutralized():
    # Even bound directly, a wrapper that still owns its port-face pull is safe.
    assert R._alias_wrapper_unsafe_as_vl_bind_top(
        _SAFE_WRAPPER, "counter", vl_bind_top="counter") is None


# ---- no regression to #119 chip_top restore ----------------------------------

def test_119_restore_still_intact():
    """The #120 guard is ADDITIVE — it must not perturb the #119 chip_top
    pull-restore that the primary (chip_top) Verilator bind depends on."""
    block = ("(\n    input clk,\n    input resetn,\n    input rst_n,\n"
             "    output [7:0] cnt\n)")
    out = R._chip_top_restore_vl_port_tri(block, _NEUTRALIZED_WRAPPER)
    assert out is not None
    assert out.count("`ifdef VERILATOR") == 2
    assert out.count("tri1") == 2
