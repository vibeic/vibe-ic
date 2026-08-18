"""ORGANIC #546 — sv2v_mixed_driver_fixup: detect and remove mixed-driver
continuous assigns so iverilog -g2012 accepts the converted file.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import sv2v_mixed_driver_fixup as F  # noqa: E402


_MIXED_DRIVER_SRC = """\
module hw2reg_regs(input clk, input rst_n, output reg status_q);
  // sv2v-generated continuous default (mixed driver)
  assign status_q = 1'b0;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) status_q <= 1'b0;
    else        status_q <= 1'b1;
  end
endmodule
"""

_SINGLE_DRIVER_SRC = """\
module clean(input clk, output reg data_o);
  assign data_o = 1'b0;  // only assign, no always for this net
  always @(posedge clk) begin
    data_o <= 1'b1;  // wait — this IS also a mixed-driver!  rename for test:
  end
endmodule
"""

_CLEAN_SRC = """\
module clean(input clk, output wire data_o, output reg ctl_o);
  assign data_o = 1'b0;           // continuous only
  always @(posedge clk) begin
    ctl_o <= 1'b1;                // procedural only (different net)
  end
endmodule
"""


def test_546_detects_mixed_driver():
    nets = F.mixed_driver_nets(_MIXED_DRIVER_SRC)
    assert "status_q" in nets


def test_546_fixup_removes_mixed_assign():
    fixed = F.fixup(_MIXED_DRIVER_SRC)
    # The offending assign must be gone
    assert "assign status_q" not in fixed
    # The always block must remain intact
    assert "always @(posedge clk" in fixed


def test_546_single_driver_file_byte_identical():
    # A file with no mixed drivers must come back byte-identical
    fixed = F.fixup(_CLEAN_SRC)
    assert fixed == _CLEAN_SRC


def test_546_file_roundtrip(tmp_path):
    p = tmp_path / "hw2reg.v"
    p.write_text(_MIXED_DRIVER_SRC)
    changed = F.fixup_file(p)
    assert changed is True
    content = p.read_text()
    assert "assign status_q" not in content
    assert "always @(posedge clk" in content


def test_546_clean_file_not_modified(tmp_path):
    p = tmp_path / "clean.v"
    p.write_text(_CLEAN_SRC)
    changed = F.fixup_file(p)
    assert changed is False
    assert p.read_text() == _CLEAN_SRC


def test_546_multiple_mixed_nets():
    src = """\
module m(input clk, output reg a, output reg b);
  assign a = 0;
  assign b = 0;
  always @(posedge clk) begin
    a <= 1;
    b <= 1;
  end
endmodule
"""
    nets = F.mixed_driver_nets(src)
    assert "a" in nets and "b" in nets
    fixed = F.fixup(src)
    assert "assign a" not in fixed
    assert "assign b" not in fixed


# ─── #200 — module scoping ────────────────────────────────────────────
# sv2v flattens every module into ONE file.  A net name that is
# `output reg` (procedural) in module A and `assign`-driven in a DIFFERENT
# module B is TWO different nets — B's continuous assign is its ONLY, legal
# driver and must survive.  Only a net driven both ways INSIDE THE SAME
# module is a real mixed-driver.  These fixtures are the production shape
# (multi-module) that the original single-module fixtures never exercised.

# `shared_o`: procedural (output reg) in module `a`, assign-only in module
# `b`  -> NOT a mixed driver in either scope; module b's assign must survive.
# `genuine_q`: BOTH assign + procedural inside module `a`  -> a real
# same-scope mixed driver that must still be removed.
_MULTI_MODULE_SRC = """\
module a(input clk, input rst_n, output reg shared_o, output reg genuine_q);
  assign genuine_q = 1'b0;              // same-scope mixed driver -> remove
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      shared_o  <= 1'b0;
      genuine_q <= 1'b0;
    end else begin
      shared_o  <= 1'b1;
      genuine_q <= 1'b1;
    end
  end
endmodule

module b(input a_i, output shared_o);
  assign shared_o = ~a_i;              // ONLY, legal driver in module b
endmodule
"""


def test_200_cross_module_same_name_is_not_mixed():
    # `shared_o` appears as output reg in `a` and assign-driven in `b`, but
    # never both-ways in the SAME module -> must not be flagged mixed.
    nets = F.mixed_driver_nets(_MULTI_MODULE_SRC)
    assert "shared_o" not in nets
    # The genuine same-scope mixed net IS still detected.
    assert "genuine_q" in nets


def test_200_cross_module_assign_survives():
    fixed = F.fixup(_MULTI_MODULE_SRC)
    # Module b's legitimate sole driver MUST survive (the ibex regression).
    assert "assign shared_o = ~a_i" in fixed
    # The genuine same-scope mixed driver in module a IS still removed.
    assert "assign genuine_q" not in fixed
    # Both modules and the procedural block stay intact.
    assert "module a(" in fixed and "module b(" in fixed
    assert "always @(posedge clk" in fixed


def test_200_scoped_fixup_elaborates_and_keeps_driver(tmp_path):
    # End-to-end: the scoped fixup output still elaborates and module b's
    # continuous driver for shared_o survives (skipped if iverilog absent).
    import shutil
    import subprocess
    iverilog = shutil.which("iverilog")
    if not iverilog:
        import pytest
        pytest.skip("iverilog not available")
    fixed = F.fixup(_MULTI_MODULE_SRC)
    assert "assign shared_o = ~a_i" in fixed
    src = tmp_path / "multi.v"
    src.write_text(fixed)
    out = tmp_path / "multi.out"
    r = subprocess.run(
        [iverilog, "-g2012", "-o", str(out), str(src)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"iverilog failed: {r.stderr}"
