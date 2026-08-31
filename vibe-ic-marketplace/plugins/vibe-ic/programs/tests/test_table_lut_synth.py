"""test_table_lut_synth.py — the DETERMINISTIC CVDP TABLE-DRIVEN COMBINATIONAL
solver.

table_lut_synth.solve(record) emits a combinational `case` for a function that
is FULLY specified by an enumerated table in the prompt — a truth table, a code
input->output mapping, a ROM/LUT with stated contents, a seven-segment / code map,
or a stated case/lookup — naming the module per the harness TOPLEVEL (reusing the
shipped record_prompt_context_bridge). It EMITS only a COMPLETE table (every input
combination present, OR the listed codes plus a stated default) and SKIPS (-> None)
every incomplete / ambiguous / sequential / composite shape.

POSITIVE (host-verified via iverilog when available):
  * a real-shaped multi-output combinational TRUTH TABLE (the GP carry-lookahead
    generate/propagate/carry-out table — 3 one-bit inputs, 8 rows = every
    combination) solves and is FUNCTIONALLY correct across the whole input domain;
  * a code -> literal-output MAP with a stated default solves and honors both the
    listed codes and the default for unlisted codes;
  * a single-input full-domain truth table (2-bit selector -> output) solves.

§4.05 PARSE-OR-SKIP / NO-CHEAT NEGATIVES (each MUST SKIP -> None):
  * an INCOMPLETE truth table (missing rows, no stated default);
  * a code -> output map with NO stated default (incomplete — never interpolate);
  * a SEQUENTIAL next-state table (clock-edge / hold-previous flip-flop);
  * a waveform / Expected-vs-Actual test-vector table (TB trace, not the function);
  * a table whose output column is a SYMBOLIC bit-slice expression (a router, not a
    literal LUT);
  * a composite / protocol wrapper;
  * a prose-only function (no enumerated table at all).

CHIP-AGNOSTIC: keyed only on table STRUCTURE + generic role vocabulary, never on a
design name. A renamed positive solves identically and is named per the (renamed)
harness TOPLEVEL.

The iverilog functional check is GATED on the iverilog binary; the structural /
SKIP assertions run anywhere.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import table_lut_synth as S  # noqa: E402
from _hostpaths import require_corpus  # noqa: E402


# --------------------------------------------------------------------------- #
# Real-shaped CVDP v1.1.0 record fixture builder.
# --------------------------------------------------------------------------- #
def _make_record(top, rtl_path, prompt, cocotb_test=""):
    # COMPLIANCE: record_prompt_context_bridge.toplevel_name derives the module name from
    # `input.prompt` + `input.context` ONLY (the harness `.env` TOPLEVEL is an
    # OFF-LIMITS oracle). Some fixture prompts (e.g. GP_PROMPT) describe the block
    # in prose ("Generate/Propagate (GP) module") without a canonical `module `X``
    # designation, so the name must be stated in the prompt itself. Prepend one
    # clean sentence naming the module iff the prompt does not already reference it.
    if f"`{top}`" not in prompt:
        prompt = f"Design the Verilog module `{top}`.\n\n" + prompt
    return {
        "id": f"test_{top}",
        "input": {"prompt": prompt, "context": {}},
        "output": {"response": "", "context": {rtl_path: ""}},
        "harness": {"files": {
            "src/.env": (
                "SIM             = icarus\n"
                "TOPLEVEL_LANG   = verilog\n"
                f"VERILOG_SOURCES = /code/{rtl_path}\n"
                f"TOPLEVEL        = {top}\n"
                f"MODULE          = test_{top}\n"
            ),
            f"src/test_{top}.py": cocotb_test or "import cocotb\n",
        }},
    }


# --------------------------------------------------------------------------- #
# POSITIVE 1 — a faithful multi-output combinational TRUTH TABLE (the real
# cvdp_copilot_Carry_Lookahead_Adder_0001 / GP shape): 3 one-bit inputs, 8 rows =
# every combination, 3 literal output columns. The function is FULLY determined.
# --------------------------------------------------------------------------- #
GP_PROMPT = """Design a Generate/Propagate (GP) module in Verilog for a carry lookahead adder.

## Interface
### Inputs:
- i_A : 1-bit input signal.
- i_B : 1-bit input signal.
- i_Cin : 1-bit carry-in signal.
### Outputs:
- o_generate : 1-bit signal.
- o_propagate : 1-bit signal.
- o_Cout : 1-bit carry-out signal.

## Truth Table:
| i_A | i_B | i_Cin | o_generate | o_propagate | o_Cout |
| --- | --- | --- | --- | --- | --- |
| 0 | 0 | 0 | 0 | 0 | 0 |
| 0 | 0 | 1 | 0 | 0 | 0 |
| 0 | 1 | 0 | 0 | 1 | 0 |
| 0 | 1 | 1 | 0 | 1 | 1 |
| 1 | 0 | 0 | 0 | 1 | 0 |
| 1 | 0 | 1 | 0 | 1 | 1 |
| 1 | 1 | 0 | 1 | 1 | 1 |
| 1 | 1 | 1 | 1 | 1 | 1 |
"""


def _gp_record(top="GP"):
    return _make_record(top, f"rtl/{top}.v", GP_PROMPT)


def test_gp_truth_table_solves_and_names_per_toplevel():
    rec = _gp_record()
    rtl = S.solve(rec)
    assert rtl is not None
    assert re.search(r"\bmodule\s+GP\b", rtl)
    assert S.variant_of(rec) == "truth"
    # the 3-input concat selector + a literal case label per row.
    assert "{i_A, i_B, i_Cin}" in rtl
    assert "3'b110: begin o_generate = 1'd1" in rtl
    # multi-output: all three output columns are reg outputs.
    for o in ("o_generate", "o_propagate", "o_Cout"):
        assert re.search(rf"output reg\s+{o}\b", rtl)


# --------------------------------------------------------------------------- #
# POSITIVE 2 — a code -> literal-output MAP with a STATED DEFAULT. A 4-bit code
# maps 0..3 to outputs; the prose states every other code defaults to 0. Complete
# via the default. (A code-map / LUT shape — 7-seg / control-character family.)
# --------------------------------------------------------------------------- #
MAP_PROMPT = """Design a combinational lookup module `seg_decode` that maps a 4-bit selector
`code` to a 8-bit display output `seg`. For any other / invalid code value the
output `seg` is set to 0.

## Lookup Table
| code  | seg     |
| ----- | ------- |
| 4'h0  | 8'h3F   |
| 4'h1  | 8'h06   |
| 4'h2  | 8'h5B   |
| 4'h3  | 8'h4F   |
"""


def _map_record(top="seg_decode"):
    return _make_record(top, f"rtl/{top}.v", MAP_PROMPT)


def test_code_map_with_stated_default_solves():
    rec = _map_record()
    rtl = S.solve(rec)
    assert rtl is not None
    assert S.variant_of(rec) == "map"
    assert re.search(r"input\s+\[3:0\]\s+code", rtl)
    assert re.search(r"output reg\s+\[7:0\]\s+seg", rtl)
    # the four listed codes are present as decimal case labels...
    assert "4'd0: begin seg = 8'd63" in rtl   # 8'h3F == 63
    assert "4'd3: begin seg = 8'd79" in rtl   # 8'h4F == 79
    # ...and the STATED default (0) covers every unlisted code.
    assert "default: begin seg = 8'd0; end" in rtl


# --------------------------------------------------------------------------- #
# POSITIVE 3 — a single 2-bit selector enumerating its FULL domain (4 rows) -> one
# output. A complete truth table even though it is one input column.
# --------------------------------------------------------------------------- #
SEL_PROMPT = """A combinational module `mux_lut` selects an output `y` from a 2-bit selector
`sel`. The mapping is fully enumerated below.

| sel    | y      |
| ------ | ------ |
| 2'b00  | 4'd5   |
| 2'b01  | 4'd9   |
| 2'b10  | 4'd2   |
| 2'b11  | 4'd7   |
"""


def test_single_input_full_domain_solves():
    rec = _make_record("mux_lut", "rtl/mux_lut.v", SEL_PROMPT)
    rtl = S.solve(rec)
    assert rtl is not None
    # full 2-bit domain => treated as a complete truth table.
    assert S.variant_of(rec) == "truth"
    assert re.search(r"input\s+\[1:0\]\s+sel", rtl)
    assert "2'd2: begin y = 4'd2" in rtl


# --------------------------------------------------------------------------- #
# §4.05 PARSE-OR-SKIP / NO-CHEAT negatives — each MUST return None.
# --------------------------------------------------------------------------- #
# (a) INCOMPLETE truth table: only 5 of 8 rows, no stated default -> SKIP.
INCOMPLETE = """Design a combinational module `partial_tt` with inputs a,b,c and output y.
| a | b | c | y |
|---|---|---|---|
| 0 | 0 | 0 | 0 |
| 0 | 0 | 1 | 1 |
| 0 | 1 | 0 | 1 |
| 1 | 0 | 0 | 1 |
| 1 | 1 | 1 | 0 |
"""

# (b) a code -> output MAP with NO stated default -> incomplete -> SKIP.
MAP_NODEFAULT = """Design a lookup module `lut_nd` mapping a 4-bit `code` to a 8-bit `out`.
| code | out   |
|------|-------|
| 4'h0 | 8'h11 |
| 4'h1 | 8'h22 |
| 4'h5 | 8'h33 |
"""

# (c) a SEQUENTIAL next-state table (clock-edge flip-flop, hold-previous) -> SKIP.
SR_FF = """Complete the Set-Reset (SR) flip-flop. The circuit responds on the rising edge of
the clock. If both inputs are low the flip-flop holds its previous value.
| i_S | i_R | o_Q |
|-----|-----|-----|
| 0   | 0   | 0   |
| 0   | 1   | 0   |
| 1   | 0   | 1   |
| 1   | 1   | 0   |
"""

# (d) a waveform / Expected-vs-Actual TB trace table -> SKIP.
TB_TRACE = """Design `acc`. The testbench drives the following vectors.
| Test case | a    | b    | Expected Sum | Actual Sum |
|-----------|------|------|--------------|------------|
| 1         | 8'h01 | 8'h02 | 8'h03       | 8'h03      |
| 2         | 8'h0F | 8'h01 | 8'h10       | 8'h10      |
| 3         | 8'hFF | 8'h01 | 8'h00       | 8'h00      |
"""

# (e) an output column that is a SYMBOLIC bit-slice expression (a router, not a
# literal LUT) -> a non-literal cell disqualifies -> SKIP.
ROUTER = """Design a decoder `dec` mapping a type field to control + data outputs.
| Type Field | ctrl_out    | data_out                 |
|------------|-------------|--------------------------|
| 0x1E       | 8'b11111111 | {E7, E6, E5, E4}         |
| 0x33       | 8'b00011111 | {D6, D5, D4, S4}         |
| 0x78       | 8'b00000001 | {D6, D5, D4, D3}         |
"""

# (f) a composite / protocol wrapper -> SKIP even if it has a small table.
COMPOSITE = """Design an AXI-Lite register block `axi_reg`. The address map is:
| addr  | reg     |
|-------|---------|
| 4'h0  | 8'h00   |
| 4'h4  | 8'h01   |
| 4'h8  | 8'h02   |
"""

# (g) a prose-only function (no enumerated table at all) -> SKIP.
PROSE_ONLY = """Design a BCD to Excess-3 converter `bcd_to_excess_3` that adds 3 to the 4-bit BCD
input `bcd` to produce the 4-bit `excess3` output, combinationally.
"""


@pytest.mark.parametrize("top,prompt", [
    ("partial_tt", INCOMPLETE),
    ("lut_nd", MAP_NODEFAULT),
    ("SR_flipflop", SR_FF),
    ("acc", TB_TRACE),
    ("dec", ROUTER),
    ("axi_reg", COMPOSITE),
    ("bcd_to_excess_3", PROSE_ONLY),
])
def test_section_4_05_skips(top, prompt):
    rec = _make_record(top, f"rtl/{top}.v", prompt)
    assert S.solve(rec) is None, f"{top} must SKIP (§4.05 parse-or-skip)"
    assert S.variant_of(rec) is None


# A COMPLETE truth table whose prompt states NO module name anywhere (no `module X`,
# no "named/called `X`", no "(ABBR) module", no backtick `X` module reference). The
# table itself is fully determined, so the ONLY reason to SKIP is the genuinely-absent
# module name: record_prompt_context_bridge.toplevel_name -> None (name derives from
# input.prompt + input.context ONLY, and neither states one) -> no emit. (GP_PROMPT
# can NOT be reused here: its prose "Generate/Propagate (GP) module" legitimately
# names the module `GP` via the compliant "(ABBR) module" designation.)
NONAME_TABLE_PROMPT = """Design a combinational Generate/Propagate function for a carry lookahead adder.

## Interface
### Inputs:
- i_A : 1-bit input signal.
- i_B : 1-bit input signal.
- i_Cin : 1-bit carry-in signal.
### Outputs:
- o_generate : 1-bit signal.
- o_propagate : 1-bit signal.
- o_Cout : 1-bit carry-out signal.

## Truth Table:
| i_A | i_B | i_Cin | o_generate | o_propagate | o_Cout |
| --- | --- | --- | --- | --- | --- |
| 0 | 0 | 0 | 0 | 0 | 0 |
| 0 | 0 | 1 | 0 | 0 | 0 |
| 0 | 1 | 0 | 0 | 1 | 0 |
| 0 | 1 | 1 | 0 | 1 | 1 |
| 1 | 0 | 0 | 0 | 1 | 0 |
| 1 | 0 | 1 | 0 | 1 | 1 |
| 1 | 1 | 0 | 1 | 1 | 1 |
| 1 | 1 | 1 | 1 | 1 | 1 |
"""


def test_no_record_no_emit():
    assert S.solve(None) is None
    assert S.solve({}) is None
    # a record whose module name is genuinely absent from prompt+context cannot be
    # named -> SKIP (even though its table is complete and would otherwise emit).
    assert S.solve({"input": {"prompt": NONAME_TABLE_PROMPT}}) is None


# --------------------------------------------------------------------------- #
# CHIP-AGNOSTIC — a renamed positive solves identically (keyed on table structure,
# not the design name) and is named per the renamed harness TOPLEVEL.
# --------------------------------------------------------------------------- #
def test_chip_agnostic_rename_solves_identically():
    base = S.solve(_gp_record("GP"))
    renamed = S.solve(_gp_record("logic_gen_prop_xyz"))
    assert base is not None and renamed is not None
    assert re.search(r"\bmodule\s+logic_gen_prop_xyz\b", renamed)
    # structurally identical apart from the module name.
    assert base.replace("GP", "X") == renamed.replace("logic_gen_prop_xyz", "X")


def test_chip_agnostic_no_design_name_keys_in_source():
    """The solver source must not hard-code any specific CVDP design name."""
    src = (PROG / "table_lut_synth.py").read_text()
    for banned in ("Carry_Lookahead", "cvdp_copilot", "seg_decode", "GP_",
                   "Brent_Kung", "64b66b"):
        assert banned not in src, f"design-name key {banned!r} leaked into the solver"


# --------------------------------------------------------------------------- #
# iverilog functional oracle (GATED on the iverilog binary).
# --------------------------------------------------------------------------- #
_IVERILOG = shutil.which("iverilog")
_VVP = shutil.which("vvp")
_HAVE_SIM = bool(_IVERILOG and _VVP)


def _run_sim(rtl, tb):
    with tempfile.TemporaryDirectory() as d:
        dut = Path(d) / "dut.v"
        tbf = Path(d) / "tb.v"
        sim = Path(d) / "sim"
        dut.write_text(rtl)
        tbf.write_text(tb)
        c = subprocess.run([_IVERILOG, "-g2012", "-o", str(sim), str(dut), str(tbf)],
                           capture_output=True, text=True)
        assert c.returncode == 0, f"iverilog compile failed:\n{c.stderr}"
        r = subprocess.run([_VVP, str(sim)], capture_output=True, text=True)
        return r.stdout


@pytest.mark.skipif(not _HAVE_SIM, reason="iverilog/vvp not installed")
def test_gp_truth_table_functional_oracle():
    """Drive the stated table's OWN 8 rows + a row I pick through the emit, and
    check against the cocotb reference oracle (gen=A&B, prop=A|B,
    Cout=gen|(prop&Cin))."""
    rtl = S.solve(_gp_record())
    tb = """module tb;
  reg i_A,i_B,i_Cin; wire o_generate,o_propagate,o_Cout; integer a,b,c,errs;
  GP u(.i_A(i_A),.i_B(i_B),.i_Cin(i_Cin),.o_generate(o_generate),
       .o_propagate(o_propagate),.o_Cout(o_Cout));
  initial begin errs=0;
    for(a=0;a<2;a=a+1) for(b=0;b<2;b=b+1) for(c=0;c<2;c=c+1) begin
      i_A=a;i_B=b;i_Cin=c;#1;
      if(o_generate!==(a&b)) errs=errs+1;
      if(o_propagate!==(a|b)) errs=errs+1;
      if(o_Cout!==((a&b)|((a|b)&c))) errs=errs+1; end
    // a row I pick that the emit MUST satisfy: A=1,B=0,Cin=1 -> 0,1,1
    i_A=1;i_B=0;i_Cin=1;#1;
    if(!(o_generate===0 && o_propagate===1 && o_Cout===1)) errs=errs+1;
    $display("ERRS %0d", errs); end endmodule"""
    out = _run_sim(rtl, tb)
    m = re.search(r"ERRS (\d+)", out)
    assert m and m.group(1) == "0", f"GP truth-table functional mismatch: {out}"


@pytest.mark.skipif(not _HAVE_SIM, reason="iverilog/vvp not installed")
def test_code_map_functional_oracle():
    """Drive the four stated map rows (boundary) + an UNLISTED code (the default
    boundary) + a row I pick, and check the emit obeys both the table and the
    stated default."""
    rtl = S.solve(_map_record())
    tb = """module tb;
  reg [3:0] code; wire [7:0] seg; integer errs;
  seg_decode u(.code(code),.seg(seg));
  initial begin errs=0;
    code=4'h0;#1; if(seg!==8'h3F) errs=errs+1;
    code=4'h1;#1; if(seg!==8'h06) errs=errs+1;
    code=4'h2;#1; if(seg!==8'h5B) errs=errs+1;   // a row I pick
    code=4'h3;#1; if(seg!==8'h4F) errs=errs+1;
    code=4'hA;#1; if(seg!==8'h00) errs=errs+1;   // unlisted -> stated default 0
    code=4'hF;#1; if(seg!==8'h00) errs=errs+1;   // unlisted -> stated default 0
    $display("ERRS %0d", errs); end endmodule"""
    out = _run_sim(rtl, tb)
    m = re.search(r"ERRS (\d+)", out)
    assert m and m.group(1) == "0", f"code-map functional mismatch: {out}"


@pytest.mark.skipif(not _HAVE_SIM, reason="iverilog/vvp not installed")
def test_real_dataset_record_functional_when_present():
    """If the real CVDP jsonl is present on the host, the one record this solver
    emits for (the GP truth table) must compile and be functionally correct."""
    import json
    ds = require_corpus("_extbench/cvdp_open_v110/"
                        "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")
    if not ds.exists():
        pytest.skip("real CVDP dataset not on host")
    recs = {json.loads(l)["id"]: json.loads(l) for l in ds.open()}
    rid = "cvdp_copilot_Carry_Lookahead_Adder_0001"
    if rid not in recs:
        pytest.skip("target record not in dataset")
    rtl = S.solve(recs[rid])
    assert rtl is not None and re.search(r"\bmodule\s+GP\b", rtl)
    tb = """module tb;
  reg i_A,i_B,i_Cin; wire o_generate,o_propagate,o_Cout; integer a,b,c,errs;
  GP u(.i_A(i_A),.i_B(i_B),.i_Cin(i_Cin),.o_generate(o_generate),
       .o_propagate(o_propagate),.o_Cout(o_Cout));
  initial begin errs=0;
    for(a=0;a<2;a=a+1) for(b=0;b<2;b=b+1) for(c=0;c<2;c=c+1) begin
      i_A=a;i_B=b;i_Cin=c;#1;
      if(o_generate!==(a&b)) errs=errs+1;
      if(o_propagate!==(a|b)) errs=errs+1;
      if(o_Cout!==((a&b)|((a|b)&c))) errs=errs+1; end
    $display("ERRS %0d", errs); end endmodule"""
    out = _run_sim(rtl, tb)
    m = re.search(r"ERRS (\d+)", out)
    assert m and m.group(1) == "0", f"real GP record functional mismatch: {out}"
