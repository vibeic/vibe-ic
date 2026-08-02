#!/usr/bin/env python3
"""Tests for rtl_hygiene_lint.py rule `output-port-reg-redeclared` + its
deterministic `--fix` (ORGANIC-20260803).

An ANSI `output` port declared in the module port list AND re-declared as a
`reg` in the body is a DUPLICATE declaration that hard-ERRORs on every
conforming simulator ("'p' has already been declared in this scope"). The rule
detects it (severity ERROR) and `--fix` repairs it deterministically by
promoting the header entry to `output reg` and deleting the body `reg`
(preserving any power-up initializer as a standalone `initial`).

These tests pin, per the flow-change-acceptance doctrine:
  * the DEFECT fires (bidirectional: the assertion is keyed on the NEW rule name
    / the NEW fix, so it cannot pass against pre-fix code);
  * three PASS cases stay silent — the legal non-ANSI idiom (`output x;`+`reg x;`
    both in body), an already-correct `output reg`, and a net output — proving
    the discriminator is positional and has zero false positives;
  * `--fix` makes the defect COMPILE and is VALUE-IDENTICAL (init preserved).
"""
from __future__ import annotations
import shutil
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "rtl_hygiene_lint.py"
_IV = shutil.which("iverilog")


def _run(args, **kw):
    return subprocess.run([sys.executable, str(PROG)] + args,
                          capture_output=True, text=True, **kw)


def _compiles(fp: Path) -> bool:
    return subprocess.run([_IV, "-g2012", "-o", "/dev/null", str(fp)],
                          capture_output=True).returncode == 0


# --- DEFECT: ANSI output re-declared as reg in body (with an initializer) -----
_DEFECT = """module right_shifter (
    input      clk,
    input      d,
    output [7:0] q
);
    reg [7:0] q = 8'b0;
    always @(posedge clk) begin
        q <= {d, q[7:1]};
    end
endmodule
"""

# --- DEFECT 2: two ANSI outputs, one ranged one scalar, both re-declared ------
_DEFECT2 = """module mul (
    input clk, input reset,
    output [15:0] p,
    output        rdy
);
    reg [15:0] p;
    reg        rdy;
    always @(posedge clk) begin p <= p + 1; rdy <= 1'b1; end
endmodule
"""

# --- PASS 1: legal NON-ANSI (direction in body, separate reg) -> silent -------
_NONANSI = """module m1 (clk, p);
  input clk;
  output [7:0] p;
  reg [7:0] p;
  always @(posedge clk) p <= p + 1;
endmodule
"""

# --- PASS 2: already-correct ANSI `output reg` -> silent ----------------------
_ALREADY = """module m2 (input clk, output reg [7:0] q);
  always @(posedge clk) q <= q + 1;
endmodule
"""

# --- PASS 3: net output (no body reg) -> silent -------------------------------
_NETOUT = """module m3 (input [3:0] a, output [3:0] y);
  assign y = ~a;
endmodule
"""

RULE = "output-port-reg-redeclared"


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return p


def test_defect_fires(tmp_path):
    p = _write(tmp_path, "d.v", _DEFECT)
    r = _run(["--severity", "ERROR", str(p)])
    assert RULE in r.stdout, r.stdout
    assert "[ERROR]" in r.stdout


def test_defect2_fires_both(tmp_path):
    p = _write(tmp_path, "d2.v", _DEFECT2)
    r = _run(["--severity", "ERROR", str(p)])
    # both p and rdy reported
    assert r.stdout.count(RULE) == 2, r.stdout


def test_nonansi_silent(tmp_path):
    p = _write(tmp_path, "n.v", _NONANSI)
    r = _run(["--severity", "INFO", str(p)])
    assert RULE not in r.stdout, r.stdout


def test_already_correct_silent(tmp_path):
    p = _write(tmp_path, "a.v", _ALREADY)
    r = _run(["--severity", "INFO", str(p)])
    assert RULE not in r.stdout, r.stdout


def test_netout_silent(tmp_path):
    p = _write(tmp_path, "y.v", _NETOUT)
    r = _run(["--severity", "INFO", str(p)])
    assert RULE not in r.stdout, r.stdout


def test_fix_makes_it_compile_and_preserves_init(tmp_path):
    p = _write(tmp_path, "d.v", _DEFECT)
    if _IV:
        assert not _compiles(p), "defect must NOT compile before --fix"
    r = _run(["--fix", str(p)])
    assert "promoted 1 duplicate-declared output port" in r.stdout, r.stdout
    fixed = p.read_text()
    assert "output reg [7:0] q" in fixed
    assert "reg [7:0] q = 8'b0;" not in fixed          # body reg gone
    assert "initial q = 8'b0;" in fixed                 # init preserved
    if _IV:
        assert _compiles(p), "must compile after --fix"


def test_fix_two_ports(tmp_path):
    p = _write(tmp_path, "d2.v", _DEFECT2)
    r = _run(["--fix", str(p)])
    assert "promoted 2 duplicate-declared output port" in r.stdout, r.stdout
    fixed = p.read_text()
    assert "output reg [15:0] p" in fixed
    assert "output reg        rdy" in fixed or "output reg rdy" in fixed
    if _IV:
        assert _compiles(p)


def test_fix_noop_on_legal(tmp_path):
    # The NEW rule must promote 0 ports on every legal file. (Orthogonal fixers
    # such as the existing reset-less power-up `initial` insertion MAY still
    # touch a reset-less registered output — that is not this rule, so we assert
    # specifically that no output-port promotion happened, not byte-identity.)
    for name, text in (("n.v", _NONANSI), ("a.v", _ALREADY), ("y.v", _NETOUT)):
        p = _write(tmp_path, name, text)
        r = _run(["--fix", str(p)])
        assert "promoted 0 duplicate-declared output port" in r.stdout, r.stdout
        # non-ANSI m1 keeps its body direction decl; no header promotion.
        if name == "n.v":
            assert "output [7:0] p;" in p.read_text()
        # all legal files still compile after --fix
        if _IV:
            assert _compiles(p), f"{name} must still compile after --fix"


if __name__ == "__main__":
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", "-q", __file__]))
