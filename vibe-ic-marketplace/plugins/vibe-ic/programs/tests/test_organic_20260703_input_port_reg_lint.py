#!/usr/bin/env python3
r"""test_organic_20260703_input_port_reg_lint.py

ORGANIC-20260703-cvdp-lesson-input-port-cannot-be-reg.

An `input`/`inout` port is a NET and can never be `reg`; `input reg <p>` /
`inout reg <p>` ELAB_ERRORs on the official CVDP icarus-13 scorer even though
some lax host simulators accept it. `rtl_hygiene_lint`:
  * flags `input reg`/`inout reg` as a WARN finding (`input-port-reg`);
  * `--fix` rewrites it to `input`/`inout` (the `reg` on a net is always
    removable without semantic change).

Run: python3 -m pytest programs/tests/test_organic_20260703_input_port_reg_lint.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import rtl_hygiene_lint as L          # noqa: E402


_BAD = """\
module m (
    input reg [7:0] data_in,
    inout reg sda,
    input clk,
    output reg [7:0] data_out
);
    always @(posedge clk) data_out <= data_in;
endmodule
"""


def test_rule_flags_input_and_inout_reg_only():
    findings = L.rule_input_port_reg(L.strip_comments(_BAD), "m.v")
    dirs = sorted(f.symbol for f in findings)
    # exactly the `input reg` and the `inout reg` are flagged (output reg is not)
    assert dirs == ["inout", "input"]
    for f in findings:
        assert f.rule == "input-port-reg"
        assert f.severity == "WARN"
    # the legal `output reg` is NOT flagged
    assert all(f.symbol != "output" for f in findings)


def test_output_reg_and_comment_not_flagged():
    src = ("module m (input clk, output reg q);\n"
           "  // input reg is illegal — but this is a comment\n"
           "  always @(posedge clk) q <= ~q;\n"
           "endmodule\n")
    findings = L.rule_input_port_reg(L.strip_comments(src), "m.v")
    assert findings == []


def test_autofix_removes_reg_from_input_and_inout(tmp_path):
    p = tmp_path / "m.v"
    p.write_text(_BAD)
    count, dirs = L.autofix_input_reg_port(p)
    assert count == 2
    assert sorted(dirs) == ["inout", "input"]
    fixed = p.read_text()
    assert "input reg" not in fixed and "inout reg" not in fixed
    # width + name preserved on the repaired input
    assert "input [7:0] data_in" in fixed
    assert "inout sda" in fixed
    # the legal output reg is untouched
    assert "output reg [7:0] data_out" in fixed


def test_autofix_skips_line_comment(tmp_path):
    p = tmp_path / "m.v"
    p.write_text("module m (input clk); // input reg mention\nendmodule\n")
    count, dirs = L.autofix_input_reg_port(p)
    assert count == 0
    assert "// input reg mention" in p.read_text()


def test_autofix_is_idempotent(tmp_path):
    p = tmp_path / "m.v"
    p.write_text(_BAD)
    L.autofix_input_reg_port(p)
    once = p.read_text()
    count2, _ = L.autofix_input_reg_port(p)
    assert count2 == 0
    assert p.read_text() == once


def test_repaired_rtl_elaborates_on_strict_iverilog(tmp_path):
    # icarus-13 rejects `input reg`; after --fix it must elaborate. Skipped when
    # iverilog is unavailable (the strict-elab check needs it).
    from shutil import which
    if not which("iverilog"):
        import pytest
        pytest.skip("iverilog not on PATH")
    import subprocess
    p = tmp_path / "m.v"
    p.write_text(_BAD)
    L.autofix_input_reg_port(p)
    r = subprocess.run(["iverilog", "-g2012", "-t", "null", str(p)],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert r.returncode == 0, r.stdout.decode("utf-8", "replace")


def test_lesson_present_in_ic_expert_agent():
    md = (_PROGRAMS.parent / "agents" / "ic-expert-agent.md").read_text()
    assert "never declare it `reg`" in md
    assert "only `output` ports may be `reg`".lower() in md.lower()
