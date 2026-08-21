#!/usr/bin/env python3
"""Tests for pdk_otp_altsyncram_inject.py — post-flatten OTP/ROM rewire.

Pins the two pure transforms:
  * hex_to_mif: ascii-hex bytes -> Quartus .mif (correct WIDTH/DEPTH header,
    zero-padding to depth, truncation past depth).
  * patch_netlist: locate the rdata concat assign, rewire each DFF D-input
    to otp_altsyncram_q[bit] (MSB-first bit mapping), and splice an
    altsyncram instance before endmodule — preserving the original driver
    in a comment. Failure modes (missing concat / wrong width) raise.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import pytest  # noqa: E402

import pdk_otp_altsyncram_inject as mod  # noqa: E402


_FLAT_2BIT = (
    "module top(input clk);\n"
    "  assign u_otp_rdata_r = { _01__I0_out , _02__I0_out };\n"
    "  assign _01__I0_in = some_gate_expr_a;\n"
    "  assign _02__I0_in = some_gate_expr_b;\n"
    "endmodule\n"
)


# ----------------------------------------------------------------------
# hex_to_mif — PASS + zero-pad + truncate.
# ----------------------------------------------------------------------
def test_hex_to_mif_pass(tmp_path):
    hx = tmp_path / "apple.hex"
    hx.write_text("00\n0F\nA5\n")
    mif = tmp_path / "apple.mif"
    n = mod.hex_to_mif(hx, mif, depth=4, width=8)
    assert n == 4  # 3 bytes + 1 zero-pad up to depth
    txt = mif.read_text()
    assert "WIDTH=8;" in txt and "DEPTH=4;" in txt
    assert "0 : 00;" in txt
    assert "1 : 0F;" in txt
    assert "2 : A5;" in txt
    assert "3 : 00;" in txt  # zero-padded tail
    assert txt.rstrip().endswith("END;")


def test_hex_to_mif_truncates_past_depth(tmp_path):
    hx = tmp_path / "big.hex"
    hx.write_text("\n".join(f"{i:02X}" for i in range(10)))
    mif = tmp_path / "big.mif"
    n = mod.hex_to_mif(hx, mif, depth=4, width=8)
    assert n == 4  # only first 4 bytes survive
    txt = mif.read_text()
    assert "3 : 03;" in txt
    assert "4 :" not in txt  # truncated


def test_hex_to_mif_ignores_comment_lines(tmp_path):
    hx = tmp_path / "c.hex"
    hx.write_text("// header comment\n00\n01\n")
    mif = tmp_path / "c.mif"
    n = mod.hex_to_mif(hx, mif, depth=2, width=8)
    assert n == 2
    assert "0 : 00;" in mif.read_text()


# ----------------------------------------------------------------------
# patch_netlist — PASS: rewires DFF D-inputs + injects altsyncram.
# ----------------------------------------------------------------------
def test_patch_netlist_pass(tmp_path):
    flat = tmp_path / "flat.v"
    flat.write_text(_FLAT_2BIT)
    out = tmp_path / "out.v"
    info = mod.patch_netlist(
        flat, out, "apple.mif", "u_otp_rdata_r", "u_fsm_otp_addr",
        depth=4, width=2, widthad=2,
    )
    assert info["otp_dff_d_inputs_rewired"] == 2
    body = out.read_text()
    # MSB-first concat: parts[0]=_01 -> bit width-1 (=1); parts[1]=_02 -> bit 0
    assert "assign _01__I0_in = otp_altsyncram_q[1];" in body
    assert "assign _02__I0_in = otp_altsyncram_q[0];" in body
    # original driver preserved in a trailing comment
    assert "// orig: some_gate_expr_a" in body
    # altsyncram spliced in before endmodule, init from the mif
    assert "altsyncram #(" in body
    assert '.init_file         ("apple.mif"),' in body
    assert ".address_a (u_fsm_otp_addr)," in body
    assert "wire [1:0] otp_altsyncram_q;" in body
    assert body.rstrip().endswith("endmodule")


# ----------------------------------------------------------------------
# Failure modes — the defects this transform refuses to silently pass.
# ----------------------------------------------------------------------
def test_patch_netlist_missing_concat_raises(tmp_path):
    flat = tmp_path / "bad.v"
    flat.write_text("module top; endmodule\n")
    with pytest.raises(RuntimeError, match="could not find"):
        mod.patch_netlist(flat, tmp_path / "o.v", "m.mif",
                          "u_otp_rdata_r", "a", 128, 8, 7)


def test_patch_netlist_width_mismatch_raises(tmp_path):
    # concat has 2 parts but caller claims width=8 -> contract violation.
    flat = tmp_path / "w.v"
    flat.write_text(
        "module t; assign u_otp_rdata_r = { a , b }; endmodule\n")
    with pytest.raises(RuntimeError, match="concat has 2 parts"):
        mod.patch_netlist(flat, tmp_path / "o.v", "m.mif",
                          "u_otp_rdata_r", "a", depth=4, width=8, widthad=2)


def test_patch_netlist_no_endmodule_raises(tmp_path):
    # A concat present but no endmodule -> cannot splice the instance.
    flat = tmp_path / "ne.v"
    flat.write_text(
        "module t(input clk);\n"
        "  assign u_otp_rdata_r = { _01__I0_out };\n"
        "  assign _01__I0_in = x;\n"
    )
    with pytest.raises(RuntimeError, match="no endmodule"):
        mod.patch_netlist(flat, tmp_path / "o.v", "m.mif",
                          "u_otp_rdata_r", "a", depth=2, width=1, widthad=1)
