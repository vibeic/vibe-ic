"""tests for mux_compare_synth.py — the CVDP MUX/DEMUX + COMPARATOR/MIN-MAX
deterministic family solver.

COMPLIANCE (CVDP official rule, arXiv:2506.14074 §2 + README_NON_AGENTIC): the model
sees ONLY `input.prompt` + `input.context`. Every record here states its module NAME
(`module `X``) and its port INTERFACE (a `### Inputs:`/`### Outputs:` block with
adjacent prose widths) in the PROMPT — the solver sources both from
`cvdp_atomic_bridge` (prompt+context only). The harness `.env`/cocotb + `output`
golden are RETAINED on each record as an OFF-LIMITS DECOY the solver must ignore.

Coverage:
  * POSITIVE emit + iverilog functional check for each datapath shape
    (N:1 mux, 1:N demux, signed/unsigned/mode comparator, signed/unsigned min/max),
    driven by a parsed truth/vector table — proving the emitted RTL is FUNCTIONALLY
    correct from a PROMPT-ONLY record, not just syntactically present.
  * The real CVDP record `cvdp_copilot_comparator_0001` states its name as
    `**Module Name:** `X`` and its ports in a Signal/Direction table — shapes the
    shared bridge does not yet parse prompt-side — so the solver HONESTLY SKIPs; the
    test pins that the result is INVARIANT to the OFF-LIMITS oracle (the compliance
    guarantee), gated on the dataset being present.
  * §4.05 NEGATIVES: ambiguous signed-ness, clocked / CDC, protocol / composite,
    sort / area-opt, clamp / saturate / correlator (the incidental-keyword traps),
    unstated/over-wide select default, and a needs-named-submodule design all SKIP.
    The interface-resolving negatives assert the interface DID resolve, so the SKIP
    is for the intended semantic reason, not an unresolved interface.
  * chip-AGNOSTIC: the solver carries no design-name key — a renamed-port synthetic
    record solves identically; a NAME-keyed shortcut would be caught here.

All synthetic records (no dataset access) except the gated real-data test, which
`pytest.skip`s when the dataset is absent; the iverilog checks skip without iverilog.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
for _p in (str(_PROGRAMS), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import mux_compare_synth as S  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_HAS_IVERILOG = shutil.which("iverilog") is not None and shutil.which("vvp") is not None
_DATASET = corpus_path("_extbench/cvdp_open_v110/"
                       "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")


# --------------------------------------------------------------------------- #
# helpers — build a synthetic CVDP record + run an iverilog vector check
# --------------------------------------------------------------------------- #
def _rec(top: str, prompt: str, *, skeleton_ports: str = "", test_py: str = "") -> dict:
    """A CVDP-COMPLIANT record. The module NAME and the port INTERFACE both live in
    `input.prompt` (the ONLY model-visible surface — the solver sources name+iface
    from `cvdp_atomic_bridge`, which reads `input.prompt`+`input.context` only). The
    harness `.env` TOPLEVEL, the cocotb testbench, and any `output.context` skeleton
    are RETAINED as OFF-LIMITS oracle the solver must never read — a DECOY that proves
    the emit is invariant to their presence. Each caller's `prompt` names the module
    (`module `X``) and states its ports in a `### Inputs:`/`### Outputs:` block with
    adjacent prose widths (`name [W-1:0]`)."""
    files = {"src/.env": f"TOPLEVEL = {top}\nMODULE = test_{top}\n"}
    if test_py:
        files[f"src/test_{top}.py"] = test_py
    oc = {f"rtl/{top}.sv": skeleton_ports} if skeleton_ports else {f"rtl/{top}.sv": ""}
    return {"id": f"synthetic_{top}",
            "input": {"prompt": prompt, "context": {}},
            "output": {"response": "", "context": oc},
            "harness": {"files": files}}


def _mask(v: int, w: int) -> int:
    return v & ((1 << w) - 1)


def _iverilog_check(rtl: str, top: str, vectors, drivers, params: str = "") -> None:
    """Compile `rtl` and drive `vectors` = list of (assign_dict, out_name, expected).
    `drivers` maps each input port -> its declared bit width (for 2's-complement
    masking of negative literals). Asserts each output equals expected."""
    assert _HAS_IVERILOG, "iverilog required"
    # build a flat TB: one initial block, sequential #1 steps per vector.
    in_decls = "".join(
        f"  reg [{w-1}:0] {n};\n" if w > 1 else f"  reg {n};\n"
        for n, w in drivers.items())
    out_names = sorted({o for _, o, _ in vectors})
    out_decls = "".join(f"  wire {o};\n" for o in out_names)
    conn = ", ".join(f".{n}({n})" for n in list(drivers) + out_names)
    body = []
    for st, o, exp in vectors:
        for n, val in st.items():
            if n in drivers:
                body.append(f"    {n} = {_mask(val, drivers[n])};")
        body.append("    #1;")
        body.append(
            f'    if ({o} !== 1\'b{exp}) begin $display("FAIL %0d: {o}=%b exp {exp}'
            f' @ {st}", errors); errors = errors + 1; end')
    pstr = ""
    if params:
        # params="WIDTH=5" -> Verilog instance-param syntax "#(.WIDTH(5))"
        items = ", ".join(f".{k.strip()}({v.strip()})"
                          for k, v in (p.split("=") for p in params.split(",")))
        pstr = f"#({items}) "
    tb = f"""
`timescale 1ns/1ps
module tb;
{in_decls}{out_decls}  integer errors = 0;
  {top} {pstr}dut ({conn});
  initial begin
{chr(10).join(body)}
    if (errors == 0) $display("ALL_PASS");
    else $display("FAILURES=%0d", errors);
    $finish;
  end
endmodule
"""
    with tempfile.TemporaryDirectory() as d:
        dut = Path(d) / "dut.v"
        tbf = Path(d) / "tb.v"
        out = Path(d) / "a.out"
        dut.write_text(rtl + "\n")
        tbf.write_text(tb)
        cp = subprocess.run(["iverilog", "-g2012", "-o", str(out), str(dut), str(tbf)],
                            capture_output=True, text=True)
        assert cp.returncode == 0, f"compile failed:\n{cp.stderr}\n---RTL---\n{rtl}\n---TB---\n{tb}"
        rp = subprocess.run(["vvp", str(out)], capture_output=True, text=True)
        assert "ALL_PASS" in rp.stdout, f"sim mismatch:\n{rp.stdout}\n{rp.stderr}\n---RTL---\n{rtl}"


# =========================================================================== #
# POSITIVE — COMPARATOR (mode-select signed/magnitude)
# =========================================================================== #
_CMP_PROMPT = """Design the Verilog module `cmp3`, a parameterized comparator that
compares two integers of parameterized bit width and outputs greater/less/equal. It
operates in two modes: signed mode and magnitude mode.

Operands i_A [4:0] and i_B [4:0]. Parameter WIDTH default value: 5. The i_enable
input activates the comparison (when low all outputs are 0). The i_mode input is
high for signed mode, low for magnitude mode. Signed mode interprets the MSB as the
sign; magnitude mode treats inputs as unsigned. Purely combinational, no clock.

### Inputs:
- `i_A`
- `i_B`
- `i_enable`
- `i_mode`

### Outputs:
- `o_greater`
- `o_less`
- `o_equal`
"""


def test_comparator_mode_emits_and_verifies():
    rec = _rec("cmp3", _CMP_PROMPT)
    rtl = S.solve(rec)
    assert rtl and "module cmp3" in rtl
    assert "i_mode ?" in rtl  # the mode-select is present
    if not _HAS_IVERILOG:
        pytest.skip("iverilog absent")
    # WIDTH=5: magnitude mode (i_mode=0) and signed mode (i_mode=1)
    W = 5
    vecs = [
        ({"i_A": 5, "i_B": 3, "i_enable": 1, "i_mode": 0}, "o_greater", 1),
        ({"i_A": 5, "i_B": 3, "i_enable": 1, "i_mode": 0}, "o_less", 0),
        ({"i_A": 3, "i_B": 5, "i_enable": 1, "i_mode": 0}, "o_less", 1),
        ({"i_A": 5, "i_B": 5, "i_enable": 1, "i_mode": 0}, "o_equal", 1),
        ({"i_A": 5, "i_B": 3, "i_enable": 0, "i_mode": 0}, "o_greater", 0),  # disabled
        ({"i_A": -3, "i_B": -5, "i_enable": 1, "i_mode": 1}, "o_greater", 1),  # signed
        ({"i_A": -5, "i_B": -3, "i_enable": 1, "i_mode": 1}, "o_less", 1),
        ({"i_A": -5, "i_B": -5, "i_enable": 1, "i_mode": 1}, "o_equal", 1),
    ]
    drivers = {"i_A": W, "i_B": W, "i_enable": 1, "i_mode": 1}
    _iverilog_check(rtl, "cmp3", vecs, drivers, params=f"WIDTH={W}")


def test_comparator_signed_only():
    p = """Design the Verilog module `scmp`, a signed comparator of two signed 4-bit
values a and b. Outputs gt (a>b), lt (a<b), eq (a==b). Combinational. Signed
interpretation.

Port widths: a [3:0], b [3:0].

### Inputs:
- `a`
- `b`

### Outputs:
- `gt`
- `lt`
- `eq`
"""
    rtl = S.solve(_rec("scmp", p))
    assert rtl and "wire signed" in rtl and "i_mode" not in rtl
    if not _HAS_IVERILOG:
        pytest.skip("iverilog absent")
    vecs = [
        ({"a": -1, "b": 1}, "lt", 1),
        ({"a": -1, "b": 1}, "gt", 0),
        ({"a": 7, "b": -8}, "gt", 1),
        ({"a": 3, "b": 3}, "eq", 1),
    ]
    _iverilog_check(rtl, "scmp", vecs, {"a": 4, "b": 4})


def test_comparator_unsigned_only():
    p = """Design the Verilog module `ucmp`, an unsigned comparator of two unsigned 4-bit
values a and b. Outputs gt, lt, eq. Combinational, unsigned.

Port widths: a [3:0], b [3:0].

### Inputs:
- `a`
- `b`

### Outputs:
- `gt`
- `lt`
- `eq`
"""
    rtl = S.solve(_rec("ucmp", p))
    assert rtl and "wire signed" not in rtl
    if not _HAS_IVERILOG:
        pytest.skip("iverilog absent")
    vecs = [
        ({"a": 15, "b": 1}, "gt", 1),   # 1111 > 0001 unsigned (would be < if signed)
        ({"a": 1, "b": 15}, "lt", 1),
        ({"a": 8, "b": 8}, "eq", 1),
    ]
    _iverilog_check(rtl, "ucmp", vecs, {"a": 4, "b": 4})


# =========================================================================== #
# POSITIVE — MUX (4:1 individual-port)
# =========================================================================== #
def test_mux_4to1_emits_and_verifies():
    p = """Design the Verilog module `mux4`, a 4-to-1 multiplexer selecting one of
four 8-bit data inputs d0, d1, d2, d3 by a 2-bit select onto y. sel=0 picks d0
(ascending).

Port widths: d0 [7:0], d1 [7:0], d2 [7:0], d3 [7:0], sel [1:0], y [7:0].

### Inputs:
- `d0`
- `d1`
- `d2`
- `d3`
- `sel`

### Outputs:
- `y`
"""
    rtl = S.solve(_rec("mux4", p))
    assert rtl and "module mux4" in rtl and "case" in rtl
    if not _HAS_IVERILOG:
        pytest.skip("iverilog absent")
    # functional check via a bit-equality probe: drive sel and check y==dX
    vecs = []
    # use a single output bit comparison: drive distinct values, check LSB pattern
    W = 8
    drivers = {"d0": W, "d1": W, "d2": W, "d3": W, "sel": 2}
    # check the LSB of y matches the selected source LSB for each sel
    for sel, lsb in [(0, 1), (1, 0), (2, 1), (3, 0)]:
        st = {"d0": 0b0001, "d1": 0b0000, "d2": 0b0101, "d3": 0b0010, "sel": sel}
        vecs.append((st, "y_lsb", lsb))
    # wrap: add a 1-bit probe wire to the RTL via a tiny shim TB (re-declare y as bus)
    out_decls = "  wire [7:0] y;\n  wire y_lsb = y[0];\n"
    in_decls = "".join(f"  reg [{w-1}:0] {n};\n" if w > 1 else f"  reg {n};\n"
                       for n, w in drivers.items())
    body = []
    for st, _o, exp in vecs:
        for n, val in st.items():
            body.append(f"    {n} = {_mask(val, drivers[n])};")
        body.append("    #1;")
        body.append(f'    if (y_lsb !== 1\'b{exp}) begin $display("FAIL sel=%0d y=%b", sel, y); errors=errors+1; end')
    conn = ", ".join(f".{n}({n})" for n in list(drivers) + ["y"])
    tb = (f"`timescale 1ns/1ps\nmodule tb;\n{in_decls}{out_decls}  integer errors=0;\n"
          f"  mux4 dut ({conn});\n  initial begin\n" + "\n".join(body) +
          "\n    if (errors==0) $display(\"ALL_PASS\"); $finish;\n  end\nendmodule\n")
    with tempfile.TemporaryDirectory() as d:
        Path(d, "dut.v").write_text(rtl + "\n")
        Path(d, "tb.v").write_text(tb)
        cp = subprocess.run(["iverilog", "-g2012", "-o", str(Path(d, "a.out")),
                             str(Path(d, "dut.v")), str(Path(d, "tb.v"))],
                            capture_output=True, text=True)
        assert cp.returncode == 0, cp.stderr
        rp = subprocess.run(["vvp", str(Path(d, "a.out"))], capture_output=True, text=True)
        assert "ALL_PASS" in rp.stdout, rp.stdout + rp.stderr


# =========================================================================== #
# POSITIVE — DEMUX (1:4)
# =========================================================================== #
def test_demux_1to4_emits_and_verifies():
    p = """Design the Verilog module `demux4`, a 1-to-4 demultiplexer that routes the
single input din (4-bit) to one of four 4-bit outputs y0, y1, y2, y3 by the 2-bit
select; the non-selected outputs are driven to 0.

Port widths: din [3:0], sel [1:0], y0 [3:0], y1 [3:0], y2 [3:0], y3 [3:0].

### Inputs:
- `din`
- `sel`

### Outputs:
- `y0`
- `y1`
- `y2`
- `y3`
"""
    rtl = S.solve(_rec("demux4", p))
    assert rtl and "module demux4" in rtl
    if not _HAS_IVERILOG:
        pytest.skip("iverilog absent")
    drivers = {"din": 4, "sel": 2}
    out_decls = "".join(f"  wire [3:0] y{i};\n" for i in range(4))
    in_decls = "  reg [3:0] din;\n  reg [1:0] sel;\n"
    body = []
    for sel in range(4):
        body.append(f"    din = 4'hA; sel = {sel}; #1;")
        for i in range(4):
            exp = "4'hA" if i == sel else "4'h0"
            body.append(f'    if (y{i} !== {exp}) begin $display("FAIL sel=%0d y{i}=%h", sel, y{i}); errors=errors+1; end')
    conn = ".din(din), .sel(sel), " + ", ".join(f".y{i}(y{i})" for i in range(4))
    tb = (f"`timescale 1ns/1ps\nmodule tb;\n{in_decls}{out_decls}  integer errors=0;\n"
          f"  demux4 dut ({conn});\n  initial begin\n" + "\n".join(body) +
          "\n    if (errors==0) $display(\"ALL_PASS\"); $finish;\n  end\nendmodule\n")
    with tempfile.TemporaryDirectory() as d:
        Path(d, "dut.v").write_text(rtl + "\n")
        Path(d, "tb.v").write_text(tb)
        cp = subprocess.run(["iverilog", "-g2012", "-o", str(Path(d, "a.out")),
                             str(Path(d, "dut.v")), str(Path(d, "tb.v"))],
                            capture_output=True, text=True)
        assert cp.returncode == 0, cp.stderr
        rp = subprocess.run(["vvp", str(Path(d, "a.out"))], capture_output=True, text=True)
        assert "ALL_PASS" in rp.stdout, rp.stdout + rp.stderr


# =========================================================================== #
# POSITIVE — MIN / MAX (4-input)
# =========================================================================== #
def test_max_4input_unsigned_verifies():
    p = """Design the Verilog module `max4`, a combinational module that outputs the
maximum of four unsigned 8-bit inputs a, b, c, d. Find the maximum among the inputs.

Port widths: a [7:0], b [7:0], c [7:0], d [7:0], y [7:0].

### Inputs:
- `a`
- `b`
- `c`
- `d`

### Outputs:
- `y`
"""
    rtl = S.solve(_rec("max4", p))
    assert rtl and "module max4" in rtl
    if not _HAS_IVERILOG:
        pytest.skip("iverilog absent")
    drivers = {"a": 8, "b": 8, "c": 8, "d": 8}
    in_decls = "".join(f"  reg [7:0] {n};\n" for n in "abcd")
    body = [
        "    a=8'd10; b=8'd200; c=8'd55; d=8'd3; #1;",
        '    if (y !== 8\'d200) begin $display("FAIL1 y=%0d", y); errors=errors+1; end',
        "    a=8'd255; b=8'd0; c=8'd128; d=8'd254; #1;",
        '    if (y !== 8\'d255) begin $display("FAIL2 y=%0d", y); errors=errors+1; end',
    ]
    conn = ".a(a), .b(b), .c(c), .d(d), .y(y)"
    tb = (f"`timescale 1ns/1ps\nmodule tb;\n{in_decls}  wire [7:0] y;\n  integer errors=0;\n"
          f"  max4 dut ({conn});\n  initial begin\n" + "\n".join(body) +
          "\n    if (errors==0) $display(\"ALL_PASS\"); $finish;\n  end\nendmodule\n")
    with tempfile.TemporaryDirectory() as d:
        Path(d, "dut.v").write_text(rtl + "\n")
        Path(d, "tb.v").write_text(tb)
        cp = subprocess.run(["iverilog", "-g2012", "-o", str(Path(d, "a.out")),
                             str(Path(d, "dut.v")), str(Path(d, "tb.v"))],
                            capture_output=True, text=True)
        assert cp.returncode == 0, cp.stderr
        rp = subprocess.run(["vvp", str(Path(d, "a.out"))], capture_output=True, text=True)
        assert "ALL_PASS" in rp.stdout, rp.stdout + rp.stderr


def test_min_2input_signed_verifies():
    p = """Design the Verilog module `min2`, a combinational module that outputs the
minimum of two signed 8-bit inputs x and y. Select the smallest of the inputs.
Signed comparison.

Port widths: x [7:0], y [7:0], m [7:0].

### Inputs:
- `x`
- `y`

### Outputs:
- `m`
"""
    rtl = S.solve(_rec("min2", p))
    assert rtl and "module min2" in rtl and "wire signed" in rtl
    if not _HAS_IVERILOG:
        pytest.skip("iverilog absent")
    in_decls = "  reg [7:0] x;\n  reg [7:0] y;\n"
    body = [
        "    x=8'sd5; y=8'shFB; #1;",  # y = -5
        '    if (m !== 8\'hFB) begin $display("FAIL1 m=%h", m); errors=errors+1; end',
        "    x=8'sd1; y=8'sd2; #1;",
        '    if (m !== 8\'d1) begin $display("FAIL2 m=%h", m); errors=errors+1; end',
    ]
    tb = (f"`timescale 1ns/1ps\nmodule tb;\n{in_decls}  wire [7:0] m;\n  integer errors=0;\n"
          f"  min2 dut (.x(x), .y(y), .m(m));\n  initial begin\n" + "\n".join(body) +
          "\n    if (errors==0) $display(\"ALL_PASS\"); $finish;\n  end\nendmodule\n")
    with tempfile.TemporaryDirectory() as d:
        Path(d, "dut.v").write_text(rtl + "\n")
        Path(d, "tb.v").write_text(tb)
        cp = subprocess.run(["iverilog", "-g2012", "-o", str(Path(d, "a.out")),
                             str(Path(d, "dut.v")), str(Path(d, "tb.v"))],
                            capture_output=True, text=True)
        assert cp.returncode == 0, cp.stderr
        rp = subprocess.run(["vvp", str(Path(d, "a.out"))], capture_output=True, text=True)
        assert "ALL_PASS" in rp.stdout, rp.stdout + rp.stderr


# =========================================================================== #
# §4.05 NEGATIVES — must SKIP (return None)
# =========================================================================== #
def test_skip_ambiguous_signedness():
    """A comparator that mentions BOTH signed and unsigned with no mode select is
    ambiguous -> SKIP (never silently pick one)."""
    p = """Design the Verilog module `acmp`, a comparator of a and b (8-bit) producing
gt/lt/eq. It may be used in signed or unsigned contexts.

Port widths: a [7:0], b [7:0].

### Inputs:
- `a`
- `b`

### Outputs:
- `gt`
- `lt`
- `eq`
"""
    # the interface DOES resolve (name + ports from the prompt) — the SKIP is for
    # the intended reason (ambiguous signed-ness), not an unresolved interface.
    assert S._extract_interface(_rec("acmp", p), "acmp") is not None
    assert S.solve(_rec("acmp", p)) is None


def test_skip_clocked_comparator():
    p = """A registered comparator `rcmp`: on the rising edge of clk, compare signed
a and b and register gt/lt/eq.

| Signal | Direction | Bit Width |
|--------|-----------|-----------|
| `clk`  | Input     | 1         |
| `a`    | Input     | [7:0]     |
| `b`    | Input     | [7:0]     |
| `gt`   | Output    | 1         |
| `lt`   | Output    | 1         |
| `eq`   | Output    | 1         |
"""
    assert S.solve(_rec("rcmp", p)) is None


def test_skip_protocol_axis_mux():
    p = """An AXI Stream multiplexer `axis_mux` selecting one of NUM_INPUTS input
AXI streams (tvalid/tdata/tready) onto a single output stream based on sel."""
    assert S.solve(_rec("axis_mux", p)) is None


def test_skip_cdc_mux_synchronizer():
    p = """A Mux Synchronizer `mux_synch` that synchronizes a data path between two
asynchronous clock domains using a two-flop synchronizer; the multiplexer select is
the synchronized req. Active-low asynchronous reset."""
    assert S.solve(_rec("mux_synch", p)) is None


def test_skip_sort_engine():
    p = """A `sorting_engine` that arranges the elements of the input array in
ascending order using the bubble sort algorithm. Perform an area optimization;
the minimum reduction threshold must be 28%."""
    assert S.solve(_rec("sorting_engine", p)) is None


def test_skip_clamp_correlator():
    """The incidental-'maximum' trap: a clamped/saturating correlator that merely
    mentions the 'maximum value representable' must NOT be taken for a min/max."""
    p = """The Signal Correlator `sc` computes a 4-bit correlation_output from two
8-bit inputs, where each matching bit contributes +2 to the summation, with the
output clamped at the maximum value representable by a 4-bit output. On reset the
output is 0."""
    assert S.solve(_rec("sc", p)) is None


def test_skip_flattened_tree_max():
    p = """The `prim_max_find` module determines the maximum value and index among
NumSrc inputs using a binary tree over a flattened vector values_i. clk_i rising
edge, rst_ni active-low. $clog2(NumSrc) levels."""
    assert S.solve(_rec("prim_max_find", p)) is None


def test_skip_named_submodule_reduction():
    p = """Complete the combinational `Data_Reduction` module using a hierarchical
design with `Bitwise_Reduction` sub-modules to reduce multiple inputs by a Boolean
operation across corresponding bits."""
    assert S.solve(_rec("Data_Reduction", p)) is None


def test_skip_mux_overwide_select_unstated_default():
    """A 6:1 mux with a 3-bit select (2**3=8 > 6) needs a stated out-of-range
    default; without one, SKIP."""
    p = """Design the Verilog module `mux6`, a 6-to-1 multiplexer selecting one of six
8-bit inputs d0, d1, d2, d3, d4, d5 by a 3-bit select onto y.

Port widths: d0 [7:0], d1 [7:0], d2 [7:0], d3 [7:0], d4 [7:0], d5 [7:0], sel [2:0], y [7:0].

### Inputs:
- `d0`
- `d1`
- `d2`
- `d3`
- `d4`
- `d5`
- `sel`

### Outputs:
- `y`
"""
    # the interface resolves (2**3=8 > 6): the SKIP is the over-wide-select guard,
    # not an unresolved interface.
    assert S._extract_interface(_rec("mux6", p), "mux6") is not None
    assert S.solve(_rec("mux6", p)) is None


def test_skip_no_toplevel():
    rec = {"input": {"prompt": "A 4-to-1 multiplexer."}, "harness": {"files": {}}}
    assert S.solve(rec) is None


def test_skip_empty_and_garbage():
    assert S.solve({}) is None
    assert S.solve({"input": {"prompt": ""}}) is None
    assert S.solve(None) is None  # type: ignore[arg-type]


# =========================================================================== #
# chip-AGNOSTIC — a renamed-port comparator solves identically (no name key)
# =========================================================================== #
def test_chip_agnostic_renamed_ports():
    # rename the module + ports (keeping ROLE-bearing tokens a generic classifier
    # reads: greater/less/equal, a mode/sel control). The solver must behave
    # identically — proving it carries no design-NAME table.
    base = _CMP_PROMPT
    renamed = (base.replace("cmp3", "totally_different_top")
                   .replace("i_A", "alpha").replace("i_B", "beta")
                   .replace("o_greater", "greater_o").replace("o_less", "less_o")
                   .replace("o_equal", "equal_o").replace("i_mode", "mode_sel")
                   .replace("i_enable", "en"))
    rtl = S.solve(_rec("totally_different_top", renamed))
    assert rtl and "module totally_different_top" in rtl
    assert "alpha" in rtl and "greater_o" in rtl and "mode_sel ?" in rtl
    # the solver has no design-name table: source carries no record-id / top-name key
    src = (Path(S.__file__)).read_text()
    assert "signed_unsigned_comparator" not in src
    assert "cvdp_copilot" not in src


# =========================================================================== #
# REAL DATA — prompt+context-ONLY compliance on the real CVDP comparator record
# =========================================================================== #
def _load_real(rid: str):
    if not _DATASET.exists():
        pytest.skip("CVDP dataset not present")
    for line in _DATASET.open():
        r = json.loads(line)
        if r.get("id") == rid:
            return r
    pytest.skip(f"record {rid} not in dataset")


def _strip_oracle(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if k not in ("harness", "output")}


def test_real_comparator_is_prompt_only_and_oracle_invariant():
    """`cvdp_copilot_comparator_0001` states its module name as `**Module Name:**
    `signed_unsigned_comparator`` and its ports in a `| Signal | Direction | Bit
    Width |` table. The shared `cvdp_atomic_bridge` now parses BOTH shapes from the
    PROMPT (the model-visible surface only), so this solver EMITS a compliant result
    recovered from `input.prompt` — never the harness.

    The load-bearing COMPLIANCE assertion: the result is IDENTICAL with and without
    the OFF-LIMITS oracle (`record["harness"]` cocotb/.env + `record["output"]`
    golden). Before this cleanup the solver "solved" this record ONLY by reading the
    harness `.env` TOPLEVEL (name) + the cocotb `dut.<sig>` test (interface); now the
    name comes from the `**Module Name:**` label and the interface from the
    Signal/Direction/Bit-Width table — both prompt-visible — so the emit is
    oracle-invariant."""
    rec = _load_real("cvdp_copilot_comparator_0001")
    with_oracle = S.solve(rec)
    without = S.solve(_strip_oracle(rec))
    assert with_oracle == without, "solve() must be invariant to harness/output presence"
    # name + interface are now recovered from the PROMPT (Module Name: label + the
    # Signal/Direction/Bit-Width table) — a compliant emit, not a harness peek.
    assert S._toplevel_name(rec) == "signed_unsigned_comparator"
    assert with_oracle is not None
    assert "signed_unsigned_comparator" in with_oracle


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
