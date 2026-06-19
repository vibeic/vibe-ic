#!/usr/bin/env python3
"""ORGANIC-20260618 [chip-AGNOSTIC] — spec_coverage / iface structured-only
port & checklist extraction.

A whole class of gate FALSE-POSITIVES came from deriving "required ports /
checklist items" by scraping FREE PROSE or NON-PORT markdown tables, then
demanding TB coverage of those phantom items. The fix restricts port/checklist
extraction to STRUCTURED declarations (a fenced ANSI module header, real
input/output decls, a port table that carries a Direction column) — never a bare
prose noun or a test-vector results-table column.

ROOT CAUSES fixed here:
  1/2. `_specrtl_common._module_port_region` MISSED a real ANSI header whose
       `#( ... )` parameter block embeds nested parens (`$clog2(N)`,
       `(A>B)?A:B`, `{N{1'b1}}`) — the old `#\\([^)]*\\)` regex cannot span an
       inner `)`. It then fell through to the prose-scan fallback and harvested
       English words ('data','and','provides','image','matrix','generation',
       'must','word','is','to') as phantom ports. Now the param block is
       BALANCE-matched, and a PARTIAL header with an UNclosed port list is
       bounded at the first body decl (so a truncated template still yields the
       real ports, never prose). The width bracket also tolerates a parameter
       range (`[INPUT_ADDR_WIDTH-1:0]`) so the type keyword `logic` is no longer
       captured as a phantom port while the real port is dropped.
  3.   iface `_table_ports` scraped a TEST-VECTOR RESULTS table column
       (`expected_root`) as a port. A table with NO Direction column is not a
       port table (mirrors the shared `_parse_md_table_ports` Direction rule).
  4.   enum_set: a Verilog SIGNAL concatenation `{c1,c2,c3}` followed by prose
       "any of the bits" was promoted to a value enum. Object-governing
       membership markers (one of / any of / each of) now license a brace only
       when they directly PRECEDE it (the brace is the object).
  5.   byte_order: a TB net bound to a DUT port via `.port(net)` is now resolved
       so an ordering assertion on the bound net counts as DUT-tied.
  6.   overflow: a `rounding`/`truncation` requirement is covered by the
       ceil/floor-division idiom or a reference-model equality — it is NOT the
       range-comparator overflow/saturation model.

§4.05 NO-LEAK: every relaxation can only DROP a phantom or CREDIT a faithful TB;
a real omitted port, a real uncovered saturate/overflow, and a real uncovered
identifier value-set ALL still hard-block under --strict (negatives below).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import os

# This test lives in programs/tests/, so parent.parent is the programs dir. An
# env override (VIBE_PROGRAMS) lets it run from an arbitrary location too.
PROGRAMS = Path(os.environ.get(
    "VIBE_PROGRAMS", str(Path(__file__).resolve().parent.parent)))
SPEC_COVERAGE = PROGRAMS / "spec_coverage_check.py"
IFACE = PROGRAMS / "iface_conformance_v2.py"
sys.path.insert(0, str(PROGRAMS))

import _specrtl_common as SRC          # noqa: E402
import spec_coverage_check as SC       # noqa: E402
import iface_conformance_v2 as IF      # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────────────
def _w(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return str(p)


def _run_sc(tmp_path, prompt, rtl, tb, strict=True):
    pp = _w(tmp_path, "p.txt", prompt)
    rp = _w(tmp_path, "rtl.sv", rtl)
    tp = _w(tmp_path, "tb.sv", tb)
    cmd = [sys.executable, str(SPEC_COVERAGE), "--prompt", pp,
           "--rtl", rp, "--tb", tp]
    if strict:
        cmd.append("--strict")
    return subprocess.run(cmd, capture_output=True, text=True)


def _run_iface(tmp_path, prompt, rtl, strict=True):
    pp = _w(tmp_path, "p.txt", prompt)
    rp = _w(tmp_path, "rtl.sv", rtl)
    cmd = [sys.executable, str(IFACE), "--prompt", pp, "--rtl", rp]
    if strict:
        cmd.append("--strict")
    return subprocess.run(cmd, capture_output=True, text=True)


# ── 1/2 — balanced param block (nested parens) reaches the real ANSI ports ────
def test_module_port_region_balances_nested_param_block():
    txt = (
        "Complete `cascaded_adder`.\n\n```\n"
        "module cascaded_adder #(\n"
        "  parameter int IN_DATA_WIDTH = 16,\n"
        "  parameter int IN_DATA_NS = 4,\n"
        "  parameter int NUM_STAGES = $clog2(IN_DATA_NS),\n"
        "  parameter logic [NUM_STAGES-1:0] REG = {NUM_STAGES{1'b1}}\n"
        ") (\n"
        "  input  logic clk,\n"
        "  input  logic rst_n,\n"
        "  input  logic i_valid,\n"
        "  input  logic [IN_DATA_WIDTH*IN_DATA_NS-1:0] i_data,\n"
        "  output logic o_valid,\n"
        "  output logic [(IN_DATA_WIDTH+$clog2(IN_DATA_NS))-1:0] o_data\n"
        ");\nendmodule\n```\n"
    )
    c = SRC.extract_spec_contract(txt, confirm=False)
    assert c.source == "verilog"
    names = {p.name for p in c.ports}
    assert names == {"clk", "rst_n", "i_valid", "i_data", "o_valid", "o_data"}
    # the phantom prose-word class is gone
    for phantom in ("data", "and", "provides", "elements", "vector", "latching",
                    "logic"):
        assert phantom not in names


def test_port_decl_parameter_width_keeps_real_name_not_logic():
    """A parameterized bus must not capture the type keyword `logic` as the port
    name while dropping the real port."""
    ports = SRC.parse_verilog_ports(
        "input  logic [INPUT_ADDR_WIDTH-1:0]  wr_addr_in,\n"
        "output logic [OUTPUT_DATA_WIDTH-1:0] wr_data_out,\n"
        "input  logic [(IN_ROW*IN_COL*DATA_WIDTH)-1:0] image_in,\n")
    names = {p.name for p in ports}
    assert names == {"wr_addr_in", "wr_data_out", "image_in"}
    assert "logic" not in names
    # a LITERAL range still yields the numeric width
    p = SRC.parse_verilog_ports("input logic [7:0] data;")[0]
    assert p.name == "data" and p.width == 8


def test_partial_unclosed_portlist_yields_real_ports_not_prose():
    """A truncated template whose ANSI port list has no closing `);` must still
    yield the real ports — never prose words."""
    txt = (
        "Complete `gray_to_binary`. Gray Input is computed by inverting bits "
        "upon changes.\n\n```\n"
        "module gray_to_binary #(\n"
        "    parameter WIDTH = 4\n"
        ") (\n"
        "    input  logic [WIDTH-1:0] gray_in,\n"
        "    output logic [WIDTH-1:0] binary_out,\n"
        "    output logic             valid\n\n"
        "  logic [WIDTH-1:0] tmp;\n"
        "  always @* begin\n  end\nendmodule\n```\n"
    )
    c = SRC.extract_spec_contract(txt, confirm=False)
    names = {p.name for p in c.ports}
    assert "gray_in" in names and "binary_out" in names and "valid" in names
    for phantom in ("Gray", "is", "by", "upon"):
        assert phantom not in names


def test_prose_scrape_fp_passes(tmp_path):
    """The image_rotate prose-scrape FP: real ANSI ports, prose words gone."""
    prompt = (
        "Design `image_rotate` that rotates an image based on a matrix; "
        "padded matrices are produced.\n\n```\n"
        "module image_rotate #(\n"
        "  parameter IN_ROW = 4,\n"
        "  parameter OUT_ROW = (IN_ROW > 4) ? IN_ROW : 4,\n"
        "  parameter DATA_WIDTH = 8\n"
        ") (\n"
        "  input  logic [1:0] rotation_angle,\n"
        "  input  logic [(IN_ROW*IN_ROW*DATA_WIDTH)-1:0] image_in,\n"
        "  output logic [(OUT_ROW*OUT_ROW*DATA_WIDTH)-1:0] image_out\n"
        ");\nendmodule\n```\n"
    )
    rtl = ("module image_rotate(input [1:0] rotation_angle,\n"
           "input [127:0] image_in, output [127:0] image_out);\n"
           "assign image_out = image_in; endmodule\n")
    tb = ("module tb; reg [1:0] rotation_angle; reg [127:0] image_in;\n"
          "wire [127:0] image_out;\n"
          "image_rotate d(.rotation_angle(rotation_angle), .image_in(image_in),\n"
          " .image_out(image_out));\n"
          "initial begin rotation_angle=0; image_in=1; #5 $finish; end endmodule\n")
    r = _run_sc(tmp_path, prompt, rtl, tb)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "'matrix'" not in r.stdout and "'based'" not in r.stdout


# ── 3 — iface results-table column is not a port ──────────────────────────────
def test_iface_directionless_results_table_not_a_port():
    txt = (
        "The module `square_root_seq` computes a root. I/O ports are described "
        "in prose.\n\n"
        "| WIDTH | Test ID | `num` | `final_root` | `expected_root` | Latency |\n"
        "|-------|---------|-------|--------------|-----------------|---------|\n"
        "| 4     | Max     | 15    | 3            | 3               | 5       |\n"
    )
    # the results-table column names are excluded from the directionless branch
    assert IF._table_ports(txt) == {}
    dl = IF._directionless_table_names(txt)
    assert {"num", "final_root", "expected_root"} <= dl


def test_iface_real_direction_table_still_yields_ports():
    """A genuine port table WITH a Direction column is untouched."""
    txt = (
        "| Signal | Direction | Width | Description |\n"
        "|--------|-----------|-------|-------------|\n"
        "| `clk`  | input     | 1     | clock       |\n"
        "| `dout` | output    | 8     | data out    |\n"
    )
    ports = IF._table_ports(txt)
    assert ports.get("clk") == "input"
    assert ports.get("dout") == "output"


def test_iface_square_root_fp_passes(tmp_path):
    prompt = (
        "The module `square_root` computes a root.\n"
        "- **num**: the unsigned input.\n"
        "- **root**: the output root.\n\n"
        "| WIDTH | Test ID | `num` | `final_root` | `expected_root` | Latency |\n"
        "|-------|---------|-------|--------------|-----------------|---------|\n"
        "| 4     | Max     | 15    | 3            | 3               | 5       |\n"
    )
    rtl = ("module square_root #(parameter WIDTH=16)("
           "input wire [WIDTH-1:0] num, output reg [WIDTH/2-1:0] root);\n"
           "always @* root = 0; endmodule\n")
    r = _run_iface(tmp_path, prompt, rtl)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "expected_root" not in r.stdout or "block-eligible) [strict]" in r.stderr
    # specifically: no BLOCK-eligible expected_root finding
    blocking = [ln for ln in (r.stdout + r.stderr).splitlines()
                if "MISSING-PORT" in ln and "ADVISORY" not in ln]
    assert not any("expected_root" in ln for ln in blocking)


# ── 4 — enum object-governing markers must precede the brace ──────────────────
def test_enum_signal_concat_after_brace_not_value_enum():
    """`{c1,c2,c3}: ... any of the bits` — the membership phrase governs 'the
    bits', not the brace, so the signal concat is NOT a value enum."""
    members = ["c1", "c2", "c3"]
    ctx = "Error Indication by {c1, c2, c3}:\n- Result of 1 in any of the bits"
    pre = "Error Indication by "
    assert SC._is_value_enum("c1, c2, c3", members, ctx, pre) is False


def test_enum_object_governing_pre_brace_is_value_enum():
    members = ["IDLE", "RUN", "DONE"]
    assert SC._is_value_enum("IDLE, RUN, DONE", members,
                             "one of {IDLE, RUN, DONE}", "one of ") is True
    assert SC._is_value_enum("IDLE, RUN, DONE", members,
                             "mode in {IDLE, RUN, DONE}", "mode in ") is True


def test_hamming_concat_fp_passes(tmp_path):
    prompt = (
        "Design `hamming_rx`.\n\n```\n"
        "module hamming_rx (input [7:0] data_in, output [7:0] data_out);\n"
        "endmodule\n```\n\n"
        "The receiver computes three syndrome bits {`c1, c2, c3`}.\n"
        "#### Error Indication by {c1, c2, c3}:\n"
        "- Result of 1 in any of the bits: error.\n"
        "- If {c1, c2, c3} == 3'b000, no error.\n"
    )
    rtl = ("module hamming_rx(input [7:0] data_in, output [7:0] data_out);\n"
           "assign data_out = data_in; endmodule\n")
    tb = ("module tb; reg [7:0] data_in; wire [7:0] data_out;\n"
          "hamming_rx d(.data_in(data_in), .data_out(data_out));\n"
          "initial begin data_in=0; #5 $finish; end endmodule\n")
    r = _run_sc(tmp_path, prompt, rtl, tb)
    assert r.returncode == 0, r.stdout + r.stderr


# ── 5 — byte_order DUT-tie via port-connection alias ──────────────────────────
def test_byte_order_resolves_port_connection_alias():
    tb = (
        "module tb; reg [7:0] expvec; wire c_sd;\n"
        "data_serializer d (.clk(clk), .s_data_o(c_sd));\n"
        "initial for (k=0;k<8;k=k+1) begin\n"
        "  if (c_sd !== expvec[k]) $display(\"FAIL\");\n"
        "end endmodule\n"
    )
    # without alias resolution s_data_o (the DUT port) is not in the operands;
    # the alias c_sd ties it.
    assert SC._tb_exercises_byte_order_region(tb, {"s_data_o", "clk"}) is True
    # control: a TB whose assertion ties NO DUT port (directly or via alias)
    tb2 = ("module tb; reg [7:0] expvec, junk;\n"
           "initial for (k=0;k<8;k=k+1) if (junk[k] !== expvec[k]) ; endmodule\n")
    assert SC._tb_exercises_byte_order_region(tb2, {"s_data_o"}) is False


# ── 6 — rounding covered by ceil-idiom / reference equality, not range model ──
def test_rounding_covered_by_ceil_idiom_and_reference_equality():
    tb = (
        "function [31:0] ref_fee; input [31:0] secs; begin\n"
        "  h = (secs + 32'd3599) / 32'd3600; ref_fee = h * rate; end endfunction\n"
        "initial if (got !== exp) $display(\"FAIL\");\n"
    )
    assert SC._tb_exercises_rounding(tb) is True
    # a TB with neither a ceil/floor idiom nor a reference equality does NOT cover
    tb2 = "initial begin a = 1; b = 2; end\n"
    assert SC._tb_exercises_rounding(tb2) is False


# ── §4.05 NEGATIVES — real requirements still hard-block ──────────────────────
def test_neg_omitted_real_port_still_blocks(tmp_path):
    prompt = (
        "Complete `widget`.\n\n```\n"
        "module widget #(parameter W=8) (\n"
        "  input  logic clk,\n"
        "  input  logic [W-1:0] data_in,\n"
        "  output logic [W-1:0] data_out,\n"
        "  output logic overflow_flag\n"
        ");\nendmodule\n```\n"
    )
    rtl = ("module widget #(parameter W=8)(input logic clk,\n"
           "input logic [W-1:0] data_in, output logic [W-1:0] data_out);\n"
           "always @* data_out = data_in; endmodule\n")
    tb = ("module tb; reg clk; reg [7:0] data_in; wire [7:0] data_out;\n"
          "widget d(.clk(clk), .data_in(data_in), .data_out(data_out));\n"
          "initial begin clk=0; data_in=8'h5A; #5 $finish; end endmodule\n")
    r = _run_sc(tmp_path, prompt, rtl, tb)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "overflow_flag" in r.stdout


def test_neg_real_saturate_overflow_uncovered_still_blocks(tmp_path):
    prompt = (
        "Design `sat_adder`.\n\n```\n"
        "module sat_adder (input logic [7:0] a, input logic [7:0] b,\n"
        " output logic [7:0] sum);\nendmodule\n```\n\n"
        "- The adder must **saturate** on **overflow**: clamp to 8'hFF, never wrap.\n"
    )
    rtl = ("module sat_adder(input [7:0] a, input [7:0] b, output [7:0] sum);\n"
           "wire [8:0] t = a+b; assign sum = t[8]?8'hFF:t[7:0]; endmodule\n")
    # TB drives only tiny values, no range decision, never names the token
    tb = ("module tb; reg [7:0] a, b; wire [7:0] sum;\n"
          "sat_adder d(.a(a), .b(b), .sum(sum));\n"
          "initial begin a=1; b=2; #5 $finish; end endmodule\n")
    r = _run_sc(tmp_path, prompt, rtl, tb)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "overflow" in r.stdout


def test_neg_real_identifier_value_set_uncovered_still_blocks(tmp_path):
    prompt = (
        "Design `fsm_ctl`.\n\n```\n"
        "module fsm_ctl (input logic clk, input logic [1:0] cmd,\n"
        " output logic [2:0] state);\nendmodule\n```\n\n"
        "- The FSM transitions to one of {IDLE, RUN, DONE}. Each of these states "
        "must be handled.\n"
    )
    rtl = ("module fsm_ctl(input clk, input [1:0] cmd, output [2:0] state);\n"
           "reg [2:0] s; always @(posedge clk) s <= {1'b0, cmd};\n"
           "assign state = s; endmodule\n")
    # TB references NONE of IDLE/RUN/DONE
    tb = ("module tb; reg clk; reg [1:0] cmd; wire [2:0] state;\n"
          "fsm_ctl d(.clk(clk), .cmd(cmd), .state(state));\n"
          "initial begin clk=0; cmd=0; #5 $finish; end endmodule\n")
    r = _run_sc(tmp_path, prompt, rtl, tb)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "IDLE" in r.stdout



# ── Step-2.7 §4.05 remediations (PR #27 review) ─────────────────────────────


def test_step27_enum_pre_brace_set_noun_still_demanded():
    """MED #3: `one of the modes {IDLE,RUN,DONE}` / `one of: {…}` are genuine
    pre-brace enums — the over-strict anchor dropped them; they must be enums."""
    assert SC._is_value_enum("", ["IDLE","RUN","DONE"],
        "The mode is one of the modes {IDLE, RUN, DONE}.",
        "The mode is one of the modes ") is True
    assert SC._is_value_enum("", ["LOAD","STORE","JUMP"],
        "field is one of: {LOAD, STORE, JUMP}.", "field is one of: ") is True


def test_step27_enum_post_brace_value_noun_still_demanded():
    """LOW #1: a post-brace enumeration over a VALUE noun (`{RED,GREEN,BLUE} …
    any of the three colors`) is a genuine enum; the structural-noun concat
    (`{c1,c2,c3} … any of the bits`, hamming) is NOT."""
    assert SC._is_value_enum("", ["RED","GREEN","BLUE"],
        "The output color must be {RED, GREEN, BLUE}, and is any of the three colors.",
        "The output color must be ") is True
    assert SC._is_value_enum("", ["c1","c2","c3"],
        "parity bits {c1, c2, c3}: Result of 1 in any of the bits",
        "parity bits ") is False


def test_step27_iface_port_listing_table_header_not_masked():
    """MED #2: a no-Direction table that lists ports as backtick COLUMN HEADERS
    (no test-vector metadata column) is NOT a results table — its header names
    must NOT be excluded, so a genuinely omitted `overflow` still blocks."""
    leak = ("The module computes a sum. The table below lists the ports.\n\n"
            "| `clk` | `rst` | `a` | `b` | `sum` | `overflow` | Notes |\n"
            "|------|------|----|----|------|------------|-------|\n"
            "| 1    | 1    | 8  | 8  | 8    | 1          | wraps |\n")
    # overflow must NOT be excluded (no results-metadata column present)
    assert "overflow" not in IF._directionless_table_names(leak)


def test_step27_iface_results_table_header_still_excluded():
    """A genuine results table (Test ID / Latency / Explanation columns) still
    excludes its quoted column headers (the square_root motivating case)."""
    sqrt = ("Compute the square root.\n\n"
            "| WIDTH | Test ID | `num` | `final_root` | `expected_root` | Latency | Explanation |\n"
            "|-------|---------|------|-------------|----------------|---------|-------------|\n"
            "| 8     | 1       | 16   | 4           | 4              | 3       | exact       |\n")
    excl = IF._directionless_table_names(sqrt)
    assert "expected_root" in excl and "final_root" in excl


def test_step27r2_port_table_meta_col_plus_body_dir_words_not_masked():
    """Round-2 §4.05: a port-listing table that carries a results-meta column
    (`Expected`/`Test ID`) AND direction WORDS in its body rows (`in`/`out`) is a
    PORT table, not a results table — its header names must NOT be excluded, so a
    genuinely omitted `overflow` still blocks. (A header-only Direction-column
    check missed this; the body-direction-word guard catches it.)"""
    leak = ("Module `alu`.\n\n"
            "| `clk` | `rst` | `a` | `b` | `sum` | `overflow` | Expected |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
            "| in | in | in | in | out | out | ok |\n")
    assert "overflow" not in IF._directionless_table_names(leak)
    # the same table with `Test ID` / `#` meta column also stays a port table
    leak2 = leak.replace("Expected", "Test ID")
    assert "overflow" not in IF._directionless_table_names(leak2)

if __name__ == "__main__":
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", __file__, "-v"]))
