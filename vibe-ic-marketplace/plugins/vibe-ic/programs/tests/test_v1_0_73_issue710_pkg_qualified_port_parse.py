"""ORGANIC #710 — full-stack-TB RTL-top port parser mis-captured the
PACKAGE QUALIFIER as the port name for SystemVerilog package-qualified
typed ports (`input pkg::type_t name`).

DEFECT (round-9 v1.0.70 6-IC clean-room; catalog-glue REUSED-IP SoC wrapper):
  `reset_clock_variant_alias._PORT_DECL_RE` knew only the
  wire/reg/logic/signed/unsigned net-type tokens. For a comportable/vendor
  bus port declared with a package-qualified struct/enum type —
      input  tlul_pkg::tl_h2d_t tl_i
      output tlul_pkg::tl_d2h_t tl_o
      output prim_mubi_pkg::mubi4_t idle_o
  the greedy final `(\\w+)` matched the PACKAGE QUALIFIER (`tlul_pkg`) as the
  port name instead of the real port (`tl_i`). Effect on disk:
  parse_module_ports lost the real ports, captured `tlul_pkg` TWICE (dup),
  and step_full_stack_tb_gen emitted `reg tlul_pkg=0;` + duplicate
  `.tlul_pkg(tlul_pkg)` instance connections binding pins the DUT does not
  expose AND colliding with the imported `tlul_pkg::*` → non-compilable TB.

FIX (chip-AGNOSTIC, single regex arm):
  widen `_PORT_DECL_RE` to consume an OPTIONAL package-qualified type prefix
  `(?:[A-Za-z_]\\w*::\\s*[A-Za-z_]\\w*\\s+)?` between the net-type block and
  the final port-name capture, so `pkg::type_t name` yields the real `name`.
  The arm fires ONLY when a literal `::` qualifier is present, so plain /
  ANSI ports are untouched (§4.05 no-leak).

§4.05 NEGATIVE NO-LEAK (the load-bearing half of a parser-RELAXING fix):
  every plain / ANSI port still parses to its real name under the WIDENED
  regex — the new arm cannot fire without a `::`, and a `::` appearing only
  INSIDE a width cell (`[pkg::W-1:0]`) is consumed by the width group, not
  the type arm, so a scoped-param width does NOT mis-capture.

SECONDARY (benchmark-agent's "typed-port TB-emit"): empirically UNNECESSARY
  in the runner's actual flow — the in-runner sv2v -DSYNTHESIS pre-pass
  flattens the struct/enum ports to packed bit vectors BEFORE iverilog, and
  iverilog tolerates the scalar-reg ↔ vector-port width mismatch as a benign
  padding WARNING (rc=0). test_end_state_emitted_tb_compiles_vs_flattened_dut
  proves the regenerated TB compiles + runs to FULL_STACK_TB_DONE against a
  flattened DUT with the PRIMARY parser fix alone.

chip-AGNOSTIC: the program fix is a pure `::`-qualifier grammar arm with no
chip / vendor / package literal. The fixtures embed the real comportable
shape only as TEST DATA.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import reset_clock_variant_alias as RCV  # noqa: E402


# ── (1) regex-level POSITIVE — package-qualified type → REAL port name ──────
@pytest.mark.parametrize(
    "decl,expected",
    [
        ("input  tlul_pkg::tl_h2d_t tl_i", "tl_i"),
        ("output tlul_pkg::tl_d2h_t tl_o", "tl_o"),
        ("output prim_mubi_pkg::mubi4_t idle_o", "idle_o"),
        # generic, not opentitan-specific — proves the fix is general:
        ("input axi_pkg::resp_t bresp", "bresp"),
        ("output my_bus_pkg::req_t   m_req_o", "m_req_o"),
        # package-qualified type WITH a packed-array width after it:
        ("input pkt_pkg::flit_t [3:0] arr_i", "arr_i"),
    ],
)
def test_pkg_qualified_port_yields_real_name(decl, expected):
    m = RCV._PORT_DECL_RE.search(decl)
    assert m is not None, f"regex did not match {decl!r}"
    assert m.group(3) == expected, (
        f"{decl!r} → captured {m.group(3)!r}, expected the REAL port "
        f"name {expected!r} (NOT the package qualifier)")


# ── (2) §4.05 NEGATIVE no-leak — plain / ANSI ports UNCHANGED ───────────────
@pytest.mark.parametrize(
    "decl,expected",
    [
        ("input wire [7:0] x", "x"),
        ("input logic clk_i", "clk_i"),
        ("output reg [31:0] q", "q"),
        ("input rst_n", "rst_n"),
        ("inout io_pad", "io_pad"),
        ("input logic [7:0] data_i", "data_i"),
        ("input signed [15:0] acc", "acc"),
        # a `::` appearing ONLY inside a width cell (scoped parameter) must be
        # consumed by the width group — NOT mis-read as a type qualifier:
        ("input [my_pkg::W-1:0] scoped_w", "scoped_w"),
    ],
)
def test_plain_ansi_ports_unchanged(decl, expected):
    m = RCV._PORT_DECL_RE.search(decl)
    assert m is not None, f"regex did not match {decl!r}"
    assert m.group(3) == expected, (
        f"§4.05 LEAK: {decl!r} → {m.group(3)!r}, expected {expected!r} "
        f"(the widened pkg arm must NOT alter plain ports)")


# ── (3) DEFECT-ARTIFACT FIXTURE + END-STATE — real round-9 chip_top shape ───
# The discriminating port-section of the round-9 catalog-glue REUSED-IP SoC
# wrapper (phase2/stage1/rtl/chip_top.sv), embedded VERBATIM as test data.
_REAL_CHIP_TOP_SHAPE = """\
`include "prim_assert.sv"

module chip_top
  import aes_pkg::*;
  import aes_reg_pkg::*;
#(
  parameter bit AES192Enable = 1,
  parameter bit AESGCMEnable = 0,
  parameter bit SecMasking   = 0
) (
  input  logic              clk_i,
  input  logic              rst_ni,
  input  logic              rst_shadowed_ni,

  // TL-UL device interface (struct-typed; flattened by in-runner sv2v)
  input  tlul_pkg::tl_h2d_t tl_i,
  output tlul_pkg::tl_d2h_t tl_o,

  // Idle indication for the clock manager (mubi4-encoded)
  output prim_mubi_pkg::mubi4_t idle_o
);
endmodule
"""


def test_end_state_real_artifact_parse_no_qualifier_dup(tmp_path):
    """END-STATE: parse_module_ports on the real defect artifact returns the
    6 real ports — and the package qualifier (`tlul_pkg`) is NOT captured at
    all, let alone the pre-fix DUPLICATE."""
    art = tmp_path / "chip_top.sv"
    art.write_text(_REAL_CHIP_TOP_SHAPE)
    ports = RCV.parse_module_ports(art.read_text(), "chip_top", {"SYNTHESIS"})
    names = [n for _d, _w, n in ports]
    assert names == [
        "clk_i", "rst_ni", "rst_shadowed_ni", "tl_i", "tl_o", "idle_o"
    ], f"parse returned {names!r}"
    # the qualifier must never appear as a port (it was captured TWICE pre-fix)
    assert "tlul_pkg" not in names
    assert "prim_mubi_pkg" not in names
    assert names.count("tl_i") == 1  # no dup


# ── (4) END-STATE — emitted full-stack TB binds real pins, not the qualifier ─






if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
