#!/usr/bin/env python3
"""ORGANIC #766 — the SHARED port parser
`reset_clock_variant_alias.parse_module_ports` could not parse a NON-ANSI port
list (`module foo(clk, resetn, ...); input clk; ...`): the header carries only
bare names and the ANSI scan dropped every one, returning []. Every gate routing
through the shared parser then aborted — `latency_conformance_check` exited rc=2
'no ports parsed ... ANSI port list?' on the ENTIRE non-ANSI design class BEFORE
any classification or simulation.

Fix (additive, chip-AGNOSTIC): when the ANSI scan finds zero ports AND the
header held bare names, fall back to scanning the module BODY for
`input|output|inout [w] name1, name2;` declarations and bind each bare header
name to its body direction/width in header order — mirroring the field-verified
non-ANSI body scan in iface_conformance_v2 `_parse_module_match`.

Tests
=====
NEW-PATH        : a 7-port non-ANSI module now yields exactly 7 (dir,width,name)
                  tuples in HEADER order.
REGRESSION-GUARD: an ANSI / comma-bundled header is byte-identical to shipped
                  1.0.84 (§4.05 — the fallback fires only when ANSI returns []).
§4.05 NO-LEAK   : a bare header name with NO body direction is NOT promoted to a
                  phantom port; a body-declared INPUT named as --output is still
                  rejected by latency_conformance ('not found as an OUTPUT');
                  a GENUINE 2-cycle non-ANSI design still BLOCKs (rc=1).
#478 END-STATE  : write non-ANSI RTL to tmp_path, invoke the REAL
                  latency_conformance_check.py via subprocess; assert it REACHES
                  measurement (rc 0/1/3) — NOT rc=2 'no ports parsed'.

chip-AGNOSTIC: pure Verilog/SV module-body grammar; no chip/SKU literal.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import reset_clock_variant_alias as V  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_LCC = _PROGRAMS / "latency_conformance_check.py"


# ── RTL fixtures ────────────────────────────────────────────────────────────

NONANSI_7PORT = """
module arithmetic_progression_generator(clk, resetn, enable, start_val,
                                         step_val, result, valid);
  input  logic clk;
  input  logic resetn;
  input  logic enable;
  input  logic [7:0] start_val;
  input  logic [7:0] step_val;
  output logic [7:0] result;
  output logic valid;
endmodule
"""

ANSI_BUNDLED = """
module m(input clk, input rst_n, input [7:0] a, b, c, output reg [7:0] q);
endmodule
"""

# bare header name `junk_name` has NO body direction declaration → must NOT
# become a phantom port.
NONANSI_STRAY = """
module s(clk, resetn, junk_name);
  input clk;
  input resetn;
  wire  junk_name;   // internal, NOT a port direction decl
endmodule
"""


# ── NEW-PATH ────────────────────────────────────────────────────────────────

def test_nonansi_body_ports_parsed_in_header_order():
    ports = V.parse_module_ports(NONANSI_7PORT,
                                 "arithmetic_progression_generator")
    assert ports == [
        ("input", "", "clk"),
        ("input", "", "resetn"),
        ("input", "", "enable"),
        ("input", "[7:0]", "start_val"),
        ("input", "[7:0]", "step_val"),
        ("output", "[7:0]", "result"),
        ("output", "", "valid"),
    ], ports
    assert len(ports) == 7


# ── REGRESSION-GUARD (§4.05 — ANSI byte-identical) ──────────────────────────

def test_ansi_bundled_byte_identical_to_shipped():
    # The shipped 1.0.84 output for this comma-bundled ANSI header. The non-ANSI
    # fallback must NOT change a single tuple of it (it fires only when the ANSI
    # scan returns []).
    assert V.parse_module_ports(ANSI_BUNDLED, "m") == [
        ("input", "", "clk"),
        ("input", "", "rst_n"),
        ("input", "[7:0]", "a"),
        ("input", "[7:0]", "b"),
        ("input", "[7:0]", "c"),
        ("output", "[7:0]", "q"),
    ]


def test_pure_ansi_unaffected_does_not_hit_fallback():
    # A pure ANSI module (every port direction-led) yields a non-empty list, so
    # the `if not out and header_bare_names` fallback is never entered.
    rtl = "module p(input wire clk, output wire q);\nendmodule\n"
    assert V.parse_module_ports(rtl, "p") == [
        ("input", "", "clk"),
        ("output", "", "q"),
    ]


# ── §4.05 NO-LEAK: stray bare name not promoted ─────────────────────────────

def test_stray_header_name_without_body_dir_not_promoted():
    ports = V.parse_module_ports(NONANSI_STRAY, "s")
    # only clk + resetn have a body direction; junk_name (a bare header token
    # with only an internal `wire` decl) is correctly dropped.
    assert ports == [("input", "", "clk"), ("input", "", "resetn")], ports
    assert all(n != "junk_name" for _d, _w, n in ports)


# ── #478 END-STATE: real program reaches measurement on non-ANSI ────────────

_NONANSI_LAT1 = """
module apg(clk, resetn, enable, start_val, step_val, result, valid);
  input         clk;
  input         resetn;
  input         enable;
  input  [7:0]  start_val;
  input  [7:0]  step_val;
  output [7:0]  result;
  output        valid;
  reg [7:0] result;
  reg       valid;
  always @(posedge clk or negedge resetn) begin
    if (!resetn) begin valid <= 1'b0; result <= 8'b0; end
    else if (enable) begin valid <= 1'b1; result <= start_val + step_val; end
    else valid <= 1'b0;
  end
endmodule
"""

_NONANSI_LAT2 = """
module apg2(clk, resetn, enable, result, valid);
  input         clk;
  input         resetn;
  input         enable;
  output [7:0]  result;
  output        valid;
  reg [7:0] result;
  reg       valid;
  reg       stage1;
  always @(posedge clk or negedge resetn) begin
    if (!resetn) begin valid <= 1'b0; stage1 <= 1'b0; result <= 0; end
    else begin stage1 <= enable; valid <= stage1; result <= 8'd5; end
  end
endmodule
"""


def _run_lcc(args):
    cp = _pr.run([sys.executable, str(_LCC), *args],
                        capture_output=True, text=True)
    return cp.returncode, cp.stdout + cp.stderr


def test_endstate_nonansi_reaches_measurement_not_parse_abort(tmp_path):
    rtl = tmp_path / "apg.sv"
    rtl.write_text(_NONANSI_LAT1)
    rc, out = _run_lcc(["--rtl", str(rtl), "--top", "apg",
                        "--event", "enable", "--output", "valid",
                        "--expect", "1"])
    # the defect was rc=2 'no ports parsed ... ANSI port list?'. After the fix
    # the gate REACHES classification/measurement: rc 0 (PASS) when iverilog is
    # present, or a SKIP (rc 0) when it is absent — NEVER the parse-abort rc=2.
    assert "no ports parsed" not in out, out
    if shutil.which("iverilog") and shutil.which("vvp"):
        assert rc == 0, out
        assert "measured=1 == spec 1" in out, out
    else:
        assert rc == 0, out  # iverilog-absent SKIP


@pytest.mark.skipif(not (shutil.which("iverilog") and shutil.which("vvp")),
                    reason="iverilog/vvp required to MEASURE latency")
def test_endstate_nonansi_genuine_2cycle_still_blocks(tmp_path):
    # §4.05 NO-LEAK: the fix is pure parsing — a REAL 2-cycle non-ANSI design
    # vs expect=1 must STILL flag LATENCY-MISMATCH rc=1.
    rtl = tmp_path / "apg2.sv"
    rtl.write_text(_NONANSI_LAT2)
    rc, out = _run_lcc(["--rtl", str(rtl), "--top", "apg2",
                        "--event", "enable", "--output", "valid",
                        "--expect", "1"])
    assert rc == 1, out
    assert "LATENCY-MISMATCH" in out and "measured=2" in out, out


def test_endstate_nonansi_body_input_named_as_output_rejected(tmp_path):
    # §4.05 NO-LEAK: direction validation is untouched — a body-declared INPUT
    # asked for as --output is still rejected ('not found as an OUTPUT').
    rtl = tmp_path / "apg.sv"
    rtl.write_text(_NONANSI_LAT1)
    rc, out = _run_lcc(["--rtl", str(rtl), "--top", "apg",
                        "--event", "enable", "--output", "enable",
                        "--expect", "1"])
    assert rc == 2, out
    assert "not found as an OUTPUT" in out, out


# ── (#766r2) §4.05 NO-LEAK: non-ANSI body UNPACKED-array port must NOT be dropped
#    (a dropped array port floats in the TB and silently PASSed before this fix) ──
def test_766r2_nonansi_unpacked_array_port_not_dropped():
    """A non-ANSI body decl `input [7:0] a [3:0];` must STILL yield the port `a`
    (with its packed width) — the prior regex required the name list to be
    immediately followed by `;`, so an unpacked-dim port was silently DROPPED,
    floating in the latency TB and masking a real array-dependent defect."""
    rtl = ("module m(a, b);\n input [7:0] a [3:0];\n output b;\n reg b;\n"
           "endmodule\n")
    ports = V.parse_module_ports(rtl, "m")
    names = [n for _d, _w, n in ports]
    assert "a" in names, ports
    assert ("input", "[7:0]", "a") in ports, ports


@pytest.mark.skipif(not (shutil.which("iverilog") and shutil.which("vvp")),
                    reason="iverilog/vvp required")
def test_766r2_nonansi_unpacked_output_reaches_same_verdict_as_ansi(tmp_path):
    """§4.05 PARITY no-leak: an UNPACKED-array OUTPUT must reach the SAME verdict
    in non-ANSI form as in ANSI form (rc=3 NOT_APPLICABLE) — never the silent
    rc=0 PASS the dropped/floating scalar produced before the fix."""
    ansi = tmp_path / "a.sv"
    ansi.write_text("module da(input clk, input en, output reg [7:0] d [3:0]);\n"
                    " always @(posedge clk) d[0] <= en;\nendmodule\n")
    nonansi = tmp_path / "n.sv"
    nonansi.write_text("module dn(clk, en, d);\n input clk;\n input en;\n"
                       " output [7:0] d [3:0];\n reg [7:0] d [3:0];\n"
                       " always @(posedge clk) d[0] <= en;\nendmodule\n")
    rc_a, _ = _run_lcc(["--rtl", str(ansi), "--top", "da", "--event", "en",
                        "--output", "d", "--expect", "1"])
    rc_n, out_n = _run_lcc(["--rtl", str(nonansi), "--top", "dn", "--event", "en",
                            "--output", "d", "--expect", "1"])
    assert rc_a == rc_n == 3, (rc_a, rc_n, out_n)
    assert rc_n != 0, out_n   # never the pre-fix silent PASS


# ── (#766r2) §4.05 NO-LEAK: the non-ANSI fallback must NOT erase L9 POWER pins
#    from the full-stack TB. A power-managed non-ANSI top declares its supply
#    pins only inside `ifdef USE_POWER_PINS; before #766 such a top parsed to []
#    (reconcile skipped, L9 kept), so #766 making it parse must NOT drop the L9
#    POWER pins / erase the supply ifdef (the #645 invariant). ─────────────────
def test_766r2_nonansi_top_preserves_l9_power_pins_ifdef(tmp_path):
    import json
    import design_one_shot_runner as P2
    l9 = {"top_module": "soc_top", "top_ports": [
        {"name": "wb_clk_i", "direction": "input", "width": 1},
        {"name": "wbs_dat_i", "direction": "input", "width": 32,
         "msb": 31, "lsb": 0},
        {"name": "vccd1", "direction": "inout", "width": 1, "io": "POWER"},
        {"name": "vssd1", "direction": "inout", "width": 1, "io": "POWER"}]}
    # NON-ANSI top (bare header names; directions in body; supply pins gated).
    rtl = ("module soc_top(\n wb_clk_i, wbs_dat_i\n"
           "`ifdef USE_POWER_PINS\n , vccd1, vssd1\n`endif\n);\n"
           " input wb_clk_i; input [31:0] wbs_dat_i;\n"
           "`ifdef USE_POWER_PINS\n inout vccd1, vssd1;\n`endif\nendmodule\n")
    proj = tmp_path / "proj"
    gd = P2._pl.generated_docs_dir(proj)
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(l9))
    rd = P2._pl.rtl_dir(proj)
    rd.mkdir(parents=True)
    (rd / "soc_top.v").write_text(rtl)
    P2.step_full_stack_tb_gen(proj, "chip_top")
    body = list((P2._pl.sim_full_stack_dir(proj)).glob("tb_*_full.v"))[0].read_text()
    assert "`ifdef USE_POWER_PINS" in body and "`endif" in body, body
    assert ".vccd1(vccd1)" in body, body


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
