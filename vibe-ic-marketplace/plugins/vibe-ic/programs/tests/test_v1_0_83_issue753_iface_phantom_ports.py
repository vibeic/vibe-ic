#!/usr/bin/env python3
"""ORGANIC #753 [P2, chip-AGNOSTIC] — iface_conformance_v2 manufactures phantom
MISSING-PORT / PORT-DIRECTION findings on correct, spec-faithful RTL via FOUR
distinct prompt-parse defects, all fixed program-first.

Round-5 of the CVDP cvdp-open convergence campaign reproduced four FP classes
on independently-confirmed-correct RTL (the RTL elaborates clean and declares
every flagged port with the spec's directions). The four defects:

  (1) MODULE-SELECTION / PORT-PARSE — `_MODULE_HDR_RE` balanced only ONE level
      of nested parens in its `#(params)` sub-pattern, so a parameter default
      with a nested-paren expression (`$clog2(MSHR_SIZE)`,
      `(CS_LINE_ADDR_WIDTH + $clog2(WORD_SIZE) + WORD_SEL_WIDTH)`) made the
      whole `cache_mshr` header un-matchable; the parse fell through to the
      next sub-module `leading_zero_cnt`, so ALL real top ports looked missing.
      FIX: a paren-DEPTH-aware scan (`_find_module_headers` / `_scan_balanced`)
      returning a duck-typed `_HdrMatch`, used by parse_rtl + parse_all_rtl.
  (2) DESC-TABLE FIRST-COL — `_table_ports` harvested first-column backtick
      names from ANY 2-column markdown table incl. State / Field / Entry /
      Signal-DESCRIPTION tables (no Direction column) → FSM-state labels
      (IDLE/LOAD/SHIFT/LATCH) + internal entry fields fabricated as ports.
      FIX: `_desc_table_firstcol_names` excludes them from the no-direction
      branch (a table with a Direction column is still harvested as a port
      table).
  (3) GIVEN-CODE INTERNAL NAMES — the prompt's own given-code internal
      `logic`/`wire`/`reg` body decls + localparam/parameter names were never
      collected for exclusion → a prose mention was charged as MISSING-PORT.
      FIX: `given_code_internal_names` collects them WITH a never-mask guard
      that re-admits any name the given-code header declares as a real port.
  (4) COPULAR / TRAILING-NOUN PROSE — `_DIR_NEAR_BEFORE_RE` matched the copular
      value-assignment "the output clock should be `clk2`" (clk2 is the VALUE,
      not a direction) and `_DIR_NEAR_AFTER_RE` matched the trailing NOUN "the
      input" ("`sync_header` is the first 2 bits of the input"). FIX: a
      `_COPULAR_GAP_RE` guard (should be / is / equals / =) on BEFORE and a
      trailing-`the`-noun guard (`_NOUN_THE_TAIL_RE`) on AFTER.

§4.05 NO-LEAK: SIX authored negatives must STILL be caught (EXIT 1 under
--strict): a genuine missing port, a real direction flip, a module-name-case
mismatch, a nested-paren-header-WITH-real-missing-port, a dual-table name, and
a given-internal-name-that-IS-also-a-port. The genuine IIR_filter
MODULE-NAME-CASE flag is preserved.

chip-AGNOSTIC: pure prompt-prose + RTL structure; no chip / vendor / SKU literal.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
PROG = PROGRAMS / "iface_conformance_v2.py"
sys.path.insert(0, str(PROGRAMS))
import iface_conformance_v2 as M  # noqa: E402


def _kinds(rid, prompt, rtl, context=None):
    fs = M.check_conformance(rid, prompt, rtl, context)
    return {f.kind for f in fs}


def _run_cli(tmp_path, rtl, prompt, rid=None, strict=False, context=None):
    rp = tmp_path / "c.sv"
    pp = tmp_path / "p.txt"
    rp.write_text(rtl)
    pp.write_text(prompt)
    cmd = [sys.executable, str(PROG), "--prompt", str(pp), "--rtl", str(rp)]
    if rid is not None:
        cmd += ["--id", rid]
    if strict:
        cmd += ["--strict"]
    for i, ctx in enumerate(context or []):
        cp = tmp_path / f"ctx{i}.sv"
        cp.write_text(ctx)
        cmd += ["--context", str(cp)]
    return subprocess.run(cmd, capture_output=True, text=True)


# ── the real round-5 shapes, embedded VERBATIM ──────────────────────────────

# MSHR_0008 / MSHR_0001: a `cache_mshr` top whose #(params) defaults carry
# nested-paren expressions ($clog2(...), a sum-of-clog2 expr), followed by a
# `leading_zero_cnt` sub-module the parser used to (wrongly) fall through to.
_MSHR_RTL = r"""
module cache_mshr #(
    parameter MSHR_SIZE          = 8,
    parameter WORD_SIZE          = 4,
    parameter WORD_SEL_WIDTH     = 2,
    parameter CS_LINE_ADDR_WIDTH = 24,
    parameter PTR_W              = $clog2(MSHR_SIZE),
    parameter ADDR_W             = (CS_LINE_ADDR_WIDTH + $clog2(WORD_SIZE) + WORD_SEL_WIDTH)
)(
    input  wire              clk,
    input  wire              rst_n,
    input  wire              alloc_req,
    input  wire [ADDR_W-1:0] alloc_addr,
    output wire              alloc_ready,
    output wire [PTR_W-1:0]  alloc_id,
    input  wire              free_req,
    input  wire [PTR_W-1:0]  free_id,
    output wire              full,
    output wire              empty,
    output wire [PTR_W-1:0]  count
);
endmodule

module leading_zero_cnt #(parameter DATA_WIDTH = 8) (
    input  wire [DATA_WIDTH-1:0]      data,
    output wire [$clog2(DATA_WIDTH):0] leading_zeros,
    output wire                        all_zeros
);
endmodule
"""

_MSHR_REAL_PORTS = [
    "clk", "rst_n", "alloc_req", "alloc_addr", "alloc_ready", "alloc_id",
    "free_req", "free_id", "full", "empty", "count",
]

# Attenuator_0001 FSM-state-description table (State|Description, NO Direction).
_ATTENUATOR_PROMPT = """
The controller is a Moore FSM with the following states:

| State   | Description                       |
|---------|-----------------------------------|
| `IDLE`  | waiting for a new attenuation cmd |
| `LOAD`  | latch the requested gain code     |
| `SHIFT` | shift the code into the ladder    |
| `LATCH` | drive the final attenuation value |
"""

# MSHR entry-metadata table (Field|Description, NO Direction).
_MSHR_FIELD_PROMPT = """
Each MSHR entry carries the following fields:

| Field            | Description                          |
|------------------|--------------------------------------|
| `valid`          | the entry is occupied                |
| `cache_line_addr`| the line address being fetched       |
| `write`          | the request is a write               |
| `next`           | pointer to the next entry            |
| `next_index`     | index of the next free slot          |
"""

# GFCM_0001: the copular value-assignment phrasing.
_GFCM_PROMPT = (
    "The module is a 2-to-1 glitch-free clock mux. When `sel` is high, "
    "the output clock should be `clk2`; otherwise the output is `clk1`."
)

# 64b66b_decoder_0011: trailing-noun "the input" + given-code internal decls.
# Both `sync_header` and `Dx` precede the trailing-noun phrase "the input"
# (the AFTER rule), so the trailing-`the`-noun guard must suppress both.
_DECODER_PROMPT = (
    "The `sync_header` carries the first 2 bits of the input.\n"
    "Each `Dx` data symbol is extracted from the input.\n"
    "```systemverilog\n"
    "module decoder_64b66b(\n"
    "    input  wire        clk,\n"
    "    input  wire [65:0] blk_in,\n"
    "    output wire [63:0] data_out\n"
    ");\n"
    "    logic [1:0] sync_header;\n"
    "    reg   [7:0] type_field;\n"
    "    localparam PIPE_DEPTH = 4;\n"
    "endmodule\n"
    "```\n"
)


# ── (1) nested-paren module header is parsed as the TOP ──────────────────────
def test_nested_paren_header_parses_correct_top():
    iface = M.parse_rtl(_MSHR_RTL)
    assert iface.module_name == "cache_mshr", (
        f"nested-paren #(params) made the top un-matchable → parser fell "
        f"through to '{iface.module_name}'")
    for p in _MSHR_REAL_PORTS:
        assert p in iface.ports, f"real top port '{p}' lost in the fall-through"


def test_nested_paren_no_phantom_missing():
    """A spec table that names the 11 real cache_mshr ports must NOT produce
    any phantom MISSING-PORT now that the right module is parsed."""
    rows = "\n".join(f"| `{p}` | input |" for p in _MSHR_REAL_PORTS)
    prompt = "| Signal | Direction |\n|---|---|\n" + rows + "\n"
    assert "MISSING-PORT" not in _kinds(None, prompt, _MSHR_RTL)


def test_scan_balanced_arbitrary_depth():
    s = "(a + $clog2(b) + (c + $clog2(d)))xyz"
    end = M._scan_balanced(s, 0)
    assert s[end:] == "xyz"
    assert M._scan_balanced("(unbalanced", 0) == -1


# ── (2) State/Field description tables are NOT harvested as ports ─────────────
def test_fsm_state_table_not_ports():
    desc = M._desc_table_firstcol_names(_ATTENUATOR_PROMPT)
    assert desc == {"IDLE", "LOAD", "SHIFT", "LATCH"}
    tp = M._table_ports(_ATTENUATOR_PROMPT)
    for s in ("IDLE", "LOAD", "SHIFT", "LATCH"):
        assert s not in tp
    assert "MISSING-PORT" not in _kinds(
        None, _ATTENUATOR_PROMPT, "module attn(input clk); endmodule")


def test_entry_field_table_not_ports():
    desc = M._desc_table_firstcol_names(_MSHR_FIELD_PROMPT)
    assert {"valid", "cache_line_addr", "write", "next", "next_index"} <= desc
    tp = M._table_ports(_MSHR_FIELD_PROMPT)
    for f in ("valid", "cache_line_addr", "next", "next_index"):
        assert f not in tp


def test_direction_table_still_harvested():
    """A genuine 2-column table WITH a Direction column is still a port table."""
    p = "| Signal | Direction |\n|---|---|\n| `wr_en` | input |\n"
    assert M._table_ports(p).get("wr_en") == "input"
    assert "wr_en" not in M._desc_table_firstcol_names(p)


# ── (3) given-code internal names excluded; never-mask preserved ─────────────
def test_given_internal_names_excluded():
    gi = M.given_code_internal_names(_DECODER_PROMPT)
    assert {"sync_header", "type_field", "pipe_depth"} <= gi
    # a prose mention of these internal/param names must NOT be charged MISSING
    rtl = ("module decoder_64b66b(input wire clk, input wire [65:0] blk_in, "
           "output wire [63:0] data_out); endmodule")
    fs = M.check_conformance(None, _DECODER_PROMPT, rtl)
    missing = {f.message for f in fs if f.kind == "MISSING-PORT"}
    for nm in ("sync_header", "type_field", "PIPE_DEPTH"):
        assert not any(nm in msg for msg in missing), (
            f"given-internal '{nm}' wrongly charged MISSING-PORT")


def test_given_internal_never_mask_header_port():
    """A name declared BOTH as a given-code header PORT and as an internal body
    decl is re-admitted as a port (dropped from the internal set)."""
    p = ("```\nmodule top(input logic sync_header, input clk);\n"
         "  logic [1:0] sync_header;\nendmodule\n```")
    assert "sync_header" not in M.given_code_internal_names(p)


# ── (4) copular + trailing-noun prose guards ─────────────────────────────────
def test_copular_value_assignment_not_a_port():
    pif = M.extract_prompt_iface(_GFCM_PROMPT)
    assert "clk2" not in pif.ports, "copular 'should be `clk2`' fabricated a port"
    # the same RTL must not be charged a phantom missing-port for clk2
    rtl = "module mux(input clk1, input clk2, input sel, output clk_out); endmodule"
    assert "MISSING-PORT" not in _kinds(None, _GFCM_PROMPT, rtl)


def test_trailing_the_input_noun_not_a_port_direction():
    p = "The `sync_header` is the first 2 bits of the input."
    pif = M.extract_prompt_iface(p)
    # 'the input' is the data-word noun, not a port direction tag
    assert pif.ports.get("sync_header", "") == ""


def test_is_an_output_still_recognised():
    """The guard must NOT break the legitimate 'is an output' port phrasing."""
    pif = M.extract_prompt_iface("The signal `s_ready` is an output.")
    assert pif.ports.get("s_ready") == "output"


def test_input_register_addr_before_still_recognised():
    pif = M.extract_prompt_iface("The bus exposes input `register_addr_i`.")
    assert pif.ports.get("register_addr_i") == "input"


# ── full-shape: the four affected shapes produce NO phantom finding ──────────
def test_decoder_shape_no_phantom(tmp_path):
    rtl = ("module decoder_64b66b(input wire clk, input wire [65:0] blk_in, "
           "output wire [63:0] data_out); endmodule")
    r = _run_cli(tmp_path, rtl, _DECODER_PROMPT,
                 rid="cvdp_copilot_64b66b_decoder_0011", strict=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_gfcm_shape_no_phantom(tmp_path):
    rtl = "module mux(input clk1, input clk2, input sel, output clk_out); endmodule"
    r = _run_cli(tmp_path, rtl, _GFCM_PROMPT,
                 rid="cvdp_copilot_GFCM_0001", strict=True)
    assert r.returncode == 0, r.stdout + r.stderr


# ── §4.05 NO-LEAK: six genuine defects STILL caught (EXIT 1 strict) ──────────
def test_noleak_genuine_missing_port(tmp_path):
    p = "| Signal | Direction |\n|---|---|\n| `data_in` | input |\n| `valid_o` | output |\n"
    r = _run_cli(tmp_path, "module foo(input data_in); endmodule", p, strict=True)
    assert r.returncode == 1 and "MISSING-PORT" in r.stdout


def test_noleak_real_direction_flip(tmp_path):
    p = "| Signal | Direction |\n|---|---|\n| `ready` | input |\n"
    r = _run_cli(tmp_path, "module foo(output ready); endmodule", p, strict=True)
    assert r.returncode == 1 and "PORT-DIRECTION" in r.stdout


def test_noleak_module_name_case_iir_preserved(tmp_path):
    r = _run_cli(tmp_path, "module IIR_FILTER(input clk); endmodule",
                 "Design an IIR filter.", rid="cvdp_copilot_iir_filter_0001",
                 strict=True)
    assert r.returncode == 1 and "MODULE-NAME-CASE" in r.stdout


def test_noleak_nested_paren_with_real_missing_port(tmp_path):
    """Depth-scan must STILL parse the nested-paren header AND flag a real
    missing top-port (no over-suppression)."""
    p = "| Signal | Direction |\n|---|---|\n| `clk` | input |\n| `bonus_missing` | input |\n"
    rtl = "module cache_mshr #(parameter W = $clog2(8))(input clk); endmodule"
    r = _run_cli(tmp_path, rtl, p, strict=True)
    assert r.returncode == 1 and "MISSING-PORT" in r.stdout
    assert "bonus_missing" in r.stdout


def test_noleak_dual_table_name(tmp_path):
    """A name that appears in a DESCRIPTION table AND in a DIRECTION table is a
    real port (the dir table wins) — a missing such port is still flagged."""
    p = ("| State | Description |\n|---|---|\n| `LOAD` | x |\n\n"
         "| Signal | Direction |\n|---|---|\n| `LOAD` | input |\n")
    r = _run_cli(tmp_path, "module foo(input clk); endmodule", p, strict=True)
    assert r.returncode == 1 and "MISSING-PORT" in r.stdout


def test_noleak_given_internal_also_a_port(tmp_path):
    """sync_header is declared as a given-code header PORT (and also has an
    internal body decl) — never-mask re-admits it, so RTL omitting it is
    flagged MISSING."""
    p = ("```\nmodule top(input logic sync_header, input clk);\n"
         "  logic [1:0] sync_header;\nendmodule\n```")
    r = _run_cli(tmp_path, "module top(input clk); endmodule", p, strict=True)
    assert r.returncode == 1 and "MISSING-PORT" in r.stdout
    assert "sync_header" in r.stdout


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
