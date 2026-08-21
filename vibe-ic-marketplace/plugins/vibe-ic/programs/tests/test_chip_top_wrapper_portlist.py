#!/usr/bin/env python3
"""Regression tests for the chip_top auto-emit port-list extraction
(design_one_shot_runner, v0.1.62).

Root cause pinned: the spm benchmark (doc→GDS Shape A) FAILed phase2 yosys_synth
because the auto-emitted chip_top wrapper had a truncated, unclosed port list.
The DUT port `input wire y,  // serial multiplier (LSB-first)` carries a `(` and
`)` inside the comment; the old paren walker counted them (comment-blind) and,
with an off-by-one depth after skipping the `#(parameter …)` block, mistook the
`)` in `(LSB-first)` for the port-list close — producing
`module chip_top (… y,);` with no closing `)` → yosys syntax error.

Fix: comment-masked scanning + separate param/port extraction.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path
import pytest

PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))
import design_one_shot_runner as P  # noqa: E402


def _extract(src: str):
    scan = P._chip_top_mask_comments(src)
    m = re.compile(r"module\s+(\w+)\s*[(#]").search(scan)
    assert m, "no module decl found"
    return P._chip_top_extract_param_and_ports(scan, m.end() - 1)


SPM = """module spm #(
    parameter size = 32
) (
    input  wire             clk,
    input  wire             rst,   // synchronous, active-high
    input  wire [size-1:0]  x,     // parallel multiplicand
    input  wire             y,     // serial multiplier (LSB-first)
    output reg              p      // serial product   (LSB-first)
);
endmodule"""


# ---- _chip_top_mask_comments ------------------------------------------------
def test_mask_preserves_length_and_newlines():
    s = "a // c(x)\nb /* d) */ e\n"
    m = P._chip_top_mask_comments(s)
    assert len(m) == len(s)
    assert m.count("\n") == s.count("\n")
    assert "(" not in m and ")" not in m  # comment parens gone


def test_mask_keeps_code_parens():
    s = "module m(input a); // (note)\n"
    m = P._chip_top_mask_comments(s)
    assert m.count("(") == 1 and m.count(")") == 1  # only the code paren


# ---- _chip_top_match_paren --------------------------------------------------
def test_match_paren_nested():
    s = "( a (b) c )"
    assert P._chip_top_match_paren(s, 0) == len(s) - 1


def test_match_paren_unbalanced_returns_minus1():
    assert P._chip_top_match_paren("( a (b)", 0) == -1


# ---- _chip_top_extract_param_and_ports — the spm regression -----------------
def test_spm_shape_full_portlist_not_truncated():
    param, ports = _extract(SPM)
    assert ports is not None
    assert ports.count("(") == ports.count(")"), "unbalanced port block"
    assert ports.rstrip().endswith(")"), "port list not closed"
    for p in ("clk", "rst", "x", "y", "p"):
        assert p in ports, f"port {p} missing (truncation regression)"
    # the comment-paren must not have leaked into the (masked) port block
    assert "LSB" not in ports


def test_spm_param_block_captured_separately():
    param, ports = _extract(SPM)
    assert "parameter" in param and "size" in param
    # params must NOT bleed into the port block
    assert "parameter" not in ports


def test_nonparam_module_with_comment_parens():
    src = ("module foo (\n"
           "  input  a,   // enable (active-high)\n"
           "  output b    // result (registered)\n"
           ");\nendmodule")
    param, ports = _extract(src)
    assert param == ""
    assert ports.count("(") == ports.count(")")
    assert "a" in ports and "b" in ports


def test_no_ports_module_returns_block():
    # `module bar #(parameter W=1) ();` — empty port list is still bounded
    src = "module bar #(parameter W=1) ();\nendmodule"
    param, ports = _extract(src)
    assert "W" in param
    assert ports == "()"


# ---- end-to-end: emitted wrapper is iverilog-parseable ----------------------
def _emit_wrapper(rtl_dir: Path, synth_top: str, dut_src: str, dut_name: str):
    """Replicate the wrapper string the runner emits, using the SAME helpers,
    so the test fails if the emission logic regresses."""
    (rtl_dir / f"{dut_name}.v").write_text(dut_src)
    scan = P._chip_top_mask_comments(dut_src)
    m = re.compile(r"module\s+(\w+)\s*[(#]").search(scan)
    param_block, port_block = P._chip_top_extract_param_and_ports(scan, m.end() - 1)
    inner = port_block.strip()[1:-1]
    kw = {"input", "output", "inout", "wire", "reg", "logic", "signed",
          "unsigned", "var"}
    names = []
    for chunk in inner.split(","):
        ids = [t for t in re.findall(r"[A-Za-z_]\w*", chunk) if t not in kw]
        if ids:
            names.append(ids[-1])
    connects = ",\n    ".join(f".{n}({n})" for n in names)
    param_header = f" {param_block.strip()}" if param_block.strip() else ""
    inst_params = ""
    if param_block.strip():
        pn = []
        for pm in re.finditer(r"\b(?:parameter|localparam)\b[^=,()]*?([A-Za-z_]\w*)\s*=",
                              param_block):
            if pm.group(1) not in pn:
                pn.append(pm.group(1))
        if pn:
            inst_params = " #(" + ", ".join(f".{p}({p})" for p in pn) + ")"
    return (f"`default_nettype none\n"
            f"module {synth_top}{param_header} {port_block};\n"
            f"  {dut_name}{inst_params} u_dut (\n    {connects}\n  );\n"
            f"endmodule\n`default_nettype wire\n")


def test_emitted_wrapper_balanced_and_connects_only_real_ports(tmp_path):
    w = _emit_wrapper(tmp_path, "chip_top", SPM, "spm")
    assert w.count("(") == w.count(")")
    assert "module chip_top #(" in w
    assert "spm #(.size(size)) u_dut" in w
    for c in (".clk(clk)", ".rst(rst)", ".x(x)", ".y(y)", ".p(p)"):
        assert c in w
    # phantom ports must NOT appear
    assert ".synchronous(" not in w and ".first(" not in w


def test_emitted_wrapper_iverilog_compiles(tmp_path):
    import shutil
    import subprocess
    if not shutil.which("iverilog"):
        pytest.skip("iverilog not available")
    (tmp_path / "spm.v").write_text(SPM.replace("endmodule",
        "  always @(posedge clk) p <= y;\nendmodule"))
    w = _emit_wrapper(tmp_path, "chip_top", SPM, "spm")
    # rewrite spm.v with a body so it elaborates
    (tmp_path / "spm.v").write_text(
        SPM[:-len("endmodule")] + "  always @(posedge clk) p <= y;\nendmodule")
    (tmp_path / "chip_top.v").write_text(w)
    r = subprocess.run(["iverilog", "-g2012", "-o", str(tmp_path / "a.out"),
                        "-s", "chip_top",
                        str(tmp_path / "chip_top.v"), str(tmp_path / "spm.v")],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"iverilog failed: {r.stderr}"
