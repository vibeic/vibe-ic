"""v0.3.18 — #520 (Bucket C): optional-handshake inference (graceful degradation)
+ genre-conventional port ordering, to recover the under-spec / positional
standalone-design floors WITHOUT regressing clean designs.

chip-AGNOSTIC: only generic handshake names + genre orderings are baked in.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import port_convention_corpus as C  # noqa: E402


# ── Part 1: optional handshake inference — recovery + no regression ─────

def test_handshake_inferred_on_downstream_hint():
    prose = ("The block produces a result each cycle; assert valid when the "
             "result has been consumed by the downstream consumer.")
    hs = C.infer_optional_handshake(prose, ["clk", "rst_n", "data_in", "result"])
    assert hs is not None
    assert hs.direction == "input"
    assert hs.graceful_default == "1'b1"   # unconnected → always ready


def test_handshake_not_inferred_without_hint():
    # a clean combinational design with no downstream-flow prose → no port.
    prose = "Compute the bitwise AND of a and b."
    assert C.infer_optional_handshake(prose, ["a", "b", "y"]) is None


def test_handshake_not_added_when_ready_already_present():
    prose = "Stall when downstream is not ready (back-pressure)."
    for existing in (["clk", "ready", "d", "q"],
                     ["clk", "out_ready", "d", "q"],
                     ["clk", "res_ready", "d", "q"]):
        assert C.infer_optional_handshake(prose, existing) is None, existing


def test_weak_ready_word_alone_does_not_fire():
    # the bare word "ready" without a consume/backpressure flow is too weak.
    prose = "Output is ready-formatted hexadecimal."
    assert C.infer_optional_handshake(prose, ["a", "y"]) is None


def test_graceful_idiom_elaborates_connected_and_unconnected(tmp_path):
    prose = "Hold output until the result has been consumed downstream."
    hs = C.infer_optional_handshake(prose, ["clk", "rst_n", "d", "q"])
    assert hs is not None
    idiom = C.graceful_handshake_idiom(hs)
    core = tmp_path / "core.v"
    core.write_text(
        "module core (\n"
        "  input clk, input rst_n, input [3:0] d,\n"
        f"  input {hs.name},\n"
        "  output reg [3:0] q\n"
        ");\n"
        f"{idiom}\n"
        "  always @(posedge clk or negedge rst_n)\n"
        f"    if (!rst_n) q <= 0; else if ({hs.effective_wire}) q <= d;\n"
        "endmodule\n")
    iv = shutil.which("iverilog")
    if not iv:
        pytest.skip("iverilog not on this host — structural checks only")
    # TB A: drives the handshake port.
    tbA = tmp_path / "tbA.v"
    tbA.write_text(
        "module tbA; reg clk=0,rst_n=0,ready=1; reg [3:0] d=0; wire [3:0] q;"
        " core dut(.clk(clk),.rst_n(rst_n),.d(d),.ready(ready),.q(q));"
        " endmodule\n")
    # TB B: leaves the handshake port UNCONNECTED → graceful default.
    tbB = tmp_path / "tbB.v"
    tbB.write_text(
        "module tbB; reg clk=0,rst_n=0; reg [3:0] d=0; wire [3:0] q;"
        " core dut(.clk(clk),.rst_n(rst_n),.d(d),.q(q));"
        " endmodule\n")
    for tb, top in ((tbA, "tbA"), (tbB, "tbB")):
        r = subprocess.run(
            [iv, "-g2012", "-s", top, "-o", str(tmp_path / f"{top}.out"),
             str(core), str(tb)],
            capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"{top}: {r.stderr}"


# ── Part 2: genre-conventional port ordering ────────────────────────────

def test_arithmetic_primitive_outputs_first():
    assert C.genre_order_policy("digital_arithmetic_primitive") == "outputs_first"
    ports = [("input", "[7:0]", "a"), ("input", "[7:0]", "b"),
             ("output", "[7:0]", "y")]
    ordered = C.order_ports(ports, "outputs_first")
    assert [p[2] for p in ordered] == ["y", "a", "b"]


def test_sequential_outputs_clk_reset_inputs():
    assert (C.genre_order_policy("digital_sequential_primitive")
            == "outputs_clk_reset_inputs")
    ports = [("input", "", "clk"), ("input", "", "rst_n"),
             ("input", "[3:0]", "d"), ("output", "[3:0]", "q")]
    ordered = C.order_ports(ports, "outputs_clk_reset_inputs")
    assert [p[2] for p in ordered] == ["q", "clk", "rst_n", "d"]


def test_ordering_is_pure_reorder_no_add_drop_rename():
    ports = [("input", "", "a"), ("output", "", "y"), ("inout", "", "io")]
    for policy in ("outputs_first", "outputs_clk_reset_inputs"):
        ordered = C.order_ports(ports, policy)
        assert sorted(ordered) == sorted(ports), policy   # same multiset


def test_already_conventional_unchanged():
    # outputs already first → outputs_first returns the same order.
    ports = [("output", "", "y"), ("input", "", "a"), ("input", "", "b")]
    assert C.order_ports(ports, "outputs_first") == ports


def test_unknown_class_falls_back_to_default():
    assert C.genre_order_policy("some_novel_class") == "outputs_first"
    assert C.genre_order_policy(None) == "outputs_first"
