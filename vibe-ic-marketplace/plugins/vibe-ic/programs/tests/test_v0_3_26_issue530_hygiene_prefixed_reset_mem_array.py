"""v0.3.26 — ORGANIC #530: two rtl_hygiene_lint chip-AGNOSTIC defects that
combined to BREAK a correct design under the ENFORCED --fix (worse than a
false flag — the v0.1.25 in-gate enforcement core):

  (1) _RESET_NAME_RE only matched tokens STARTING with rst/reset — prefixed
      spellings (w_rst / r_rst / io_rst, standard in cross-domain designs)
      were invisible, so a dual-clock module was falsely reset-less;
  (2) the power-up autofix case (b) (registered RHS of an output assign)
      lacked the memory-array guard case (c) already had — an unpacked
      array RHS got a scalar `initial mem = 0;` which icarus cannot
      elaborate (whole-array assignment).

Field evidence shape: an async FILO completion compiled clean PRE-fix and
died POST-fix at the inserted whole-array assignment.

NEGATIVE no-leak: a genuinely reset-less module still gets the power-up
fix; a non-array registered RHS still goes through case (b).
"""
import subprocess
import shutil
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import rtl_hygiene_lint as H  # noqa: E402

_HAS_IVERILOG = shutil.which("iverilog") is not None


def _fix(path):
    """Run the --fix CLI as a subprocess (main() takes no argv)."""
    subprocess.run([sys.executable, str(PROGRAMS / "rtl_hygiene_lint.py"),
                    "--fix", str(path)], capture_output=True)

FILO = """\
module async_filo #(parameter W=8, D=4)(
  input  wire w_clk, input wire w_rst, input wire w_en,
  input  wire [W-1:0] w_data,
  input  wire r_clk, input wire r_rst, input wire r_en,
  output wire [W-1:0] r_data
);
  reg [W-1:0] mem [0:D-1];
  reg [1:0] r_ptr;
  always @(posedge w_clk) if (w_en) mem[0] <= w_data;
  always @(posedge r_clk or posedge r_rst)
    if (r_rst) r_ptr <= 0; else if (r_en) r_ptr <= r_ptr + 1;
  assign r_data = mem[r_ptr];
endmodule
"""


def test_prefixed_reset_names_recognized():
    for nm in ("w_rst", "r_rst", "io_rst", "sys_reset", "core_rst_n"):
        assert H._RESET_NAME_RE.search(f"input wire {nm}"), nm
    # plain spellings still recognized
    for nm in ("rst", "rst_n", "reset", "areset", "nreset"):
        assert H._RESET_NAME_RE.search(f"input wire {nm}"), nm
    # non-reset tokens must NOT match (boundary safety)
    for nm in ("first", "w_first", "data_burst", "wurst", "thirst"):
        assert not H._RESET_NAME_RE.search(f"input wire {nm}"), nm


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
def test_fix_no_longer_breaks_prefixed_reset_filo(tmp_path):
    # the field repro: PRE-fix compiles → POST-fix must STILL compile and
    # receive no whole-array initial.
    f = tmp_path / "filo.v"
    f.write_text(FILO)
    assert subprocess.run(["iverilog", "-g2012", "-t", "null", str(f)],
                          capture_output=True).returncode == 0
    _fix(f)
    body = f.read_text()
    assert "mem = 0" not in body
    r = subprocess.run(["iverilog", "-g2012", "-t", "null", str(f)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(not _HAS_IVERILOG, reason="iverilog not on this host")
def test_caseb_mem_array_guard_in_truly_resetless_module(tmp_path):
    # defense in depth: a GENUINELY reset-less module whose output assign
    # references an unpacked array must not get the scalar array init —
    # while its scalar regs still do (the no-leak half).
    rtl = """\
module rl(input wire clk, input wire en, input wire [7:0] d,
          output wire [7:0] q);
  reg [7:0] mem [0:3];
  reg [1:0] ptr;
  always @(posedge clk) if (en) begin mem[ptr] <= d; ptr <= ptr + 1; end
  assign q = mem[ptr];
endmodule
"""
    f = tmp_path / "rl.v"
    f.write_text(rtl)
    _fix(f)
    body = f.read_text()
    assert "mem = 0" not in body          # array skipped (case (b) guard)
    assert "ptr = 0" in body              # scalar still fixed (no-leak)
    r = subprocess.run(["iverilog", "-g2012", "-t", "null", str(f)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_negative_truly_resetless_scalar_still_fixed(tmp_path):
    # NEGATIVE no-leak: the classic reset-less power-up case still fires.
    rtl = """\
module pup(input wire clk, output wire q);
  reg st;
  always @(posedge clk) st <= ~st;
  assign q = st;
endmodule
"""
    f = tmp_path / "pup.v"
    f.write_text(rtl)
    _fix(f)
    assert "st = 0" in f.read_text()
