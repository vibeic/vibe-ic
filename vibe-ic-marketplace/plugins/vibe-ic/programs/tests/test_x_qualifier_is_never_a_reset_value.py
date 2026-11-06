#!/usr/bin/env python3
"""FULLSTACKTB final review — a reset-value sentence is not a validity qualifier.

The false PASS (review_wave58, measured with iverilog on 8HD-4): the
R-0929-X-QUALIFIED parser took ANY 1-bit port bound to a level under a
condition word as a qualifier, the reset port included. The port-table row
"Output flag, cleared to 0 when rst_n is low" became {qualifier: rst_n,
active: 0}; after the glitch was released rst_n === 1 read "known and
inactive", so an output the RTL leaves UNRESET printed X_EXEMPT and the case
PASSED — the exact defect the post-release X check exists to catch.

The rule now (R-0929-X-QUALIFIED as written):
  * the ports the testbench drives as CLOCK and RESET are never a qualifier;
  * the clause must state VALIDITY (valid / sampled / qualified / captured /
    有效 / 取樣), not a bare condition ("o_done is high when o_busy is low");
  * the qualified output is a DATA output (multi-bit, or its own description
    declares a data role).
chip-AGNOSTIC: every fixture is synthetic.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reset_invariant_oracle_tb_gen as riv  # noqa: E402

_IN = [("clk", ""), ("rst_n", ""), ("d", "[7:0]")]
_OUT = [("o_q", ""), ("o_data", "[7:0]"), ("o_we", ""), ("o_cyc", ""),
        ("o_done", ""), ("o_busy", "")]
_CASE = {"name": "rst_glitch", "stimulus": "rst_n glitch 不應導致 bus race",
         "expected": "holds"}

RESET_VALUE_ROWS = [
    {"name": "o_q", "direction": "output", "width": 1,
     "description": "Output flag, cleared to 0 when rst_n is low"},
    {"name": "o_data", "direction": "output", "width": 8,
     "description": "reset to 0 when rst_n = 0"},
]
RESET_VALUE_PROSE = "All outputs (o_q, o_data) are driven to 0 while rst_n is low."


def _l9(tmp_path, ports, notes=None):
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    doc = {"top_ports": ports}
    if notes:
        doc["notes"] = notes
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps(doc))
    return tmp_path


def test_a_reset_value_sentence_declares_no_qualifier(tmp_path):
    proj = _l9(tmp_path, RESET_VALUE_ROWS, RESET_VALUE_PROSE)
    assert riv.declared_output_qualifiers(proj, _OUT, _IN) == {}


def test_the_reset_port_is_never_a_qualifier_even_under_a_validity_word(
        tmp_path):
    proj = _l9(tmp_path, [{"name": "o_data", "direction": "output",
                           "width": 8,
                           "description": "valid when rst_n = 1"}])
    assert riv.declared_output_qualifiers(proj, _OUT, _IN) == {}
    # nor the clock
    proj2 = _l9(tmp_path / "b", [{"name": "o_data", "direction": "output",
                                  "width": 8,
                                  "description": "sampled when clk = 1"}])
    assert riv.declared_output_qualifiers(proj2, _OUT, _IN) == {}


def test_a_bare_condition_is_not_validity():
    assert riv.qualifiers_from_statements(
        [(None, "o_done is high when o_busy is low")], _OUT, _IN) == {}
    # a validity word in ANOTHER clause does not lend its meaning
    assert riv.qualifiers_from_statements(
        [("o_data", "valid output data; o_busy = 1 while computing")],
        _OUT, _IN) == {}


def test_only_a_data_output_is_qualified():
    # a 1-bit output with no declared data role is a control output
    assert riv.qualifiers_from_statements(
        [("o_q", "valid when o_we = 1")], _OUT, _IN) == {}
    # ... unless its own description makes it data
    assert riv.qualifiers_from_statements(
        [("o_q", "serial write data, valid when o_we = 1")], _OUT, _IN,
        data_outputs=["o_q"])["o_q"][0]["qualifier"] == "o_we"


def test_the_validity_qualifier_still_works(tmp_path):
    """KNOWN-POSITIVE: the rule the ruling states is untouched."""
    proj = _l9(tmp_path, [
        {"name": "o_data", "direction": "output", "width": 8,
         "description": "write data, valid when o_we = 1"},
        {"name": "o_q", "direction": "output", "width": 1,
         "description": "serial data, sampled when o_cyc = 1"}])
    # R-0929-X-QUALIFIED-4 (migrated): a sentence is not a declaration the
    # oracle reads; the D1-signed structured field is
    assert riv.declared_output_qualifiers(proj, _OUT, _IN) == {}
    import sys as _s
    _s.path.insert(0, str(Path(__file__).resolve().parent))
    from _qualified_by_fixture import (INPUT_DOC, stage_field,
                                       write_expectation)
    lines = ["| `o_data` | 8-bit | output | write data |",
             "| `o_we` | 1-bit | output | write enable |",
             "| `o_q` | 1-bit | output | serial data |",
             "| `o_cyc` | 1-bit | output | cycle |"]
    basis = lambda i, j: [{"file": INPUT_DOC, "line": 5 + i, "quote": lines[i]},
                          {"file": INPUT_DOC, "line": 5 + j, "quote": lines[j]}]
    stage_field(proj, "o_data", "o_we", "high", quote_lines=lines,
                basis=basis(0, 1))
    # a signed field on a 1-bit output is still ignored: control/strobe
    # outputs must be known after release
    stage_field(proj, "o_q", "o_cyc", "high", quote_lines=lines,
                basis=basis(2, 3), row_width=1)
    write_expectation(proj, "o_data", "o_we", "high")
    write_expectation(proj, "o_q", "o_cyc", "high")
    q = riv.declared_output_qualifiers(proj, _OUT, _IN)
    assert [r["qualifier"] for r in q["o_data"]] == ["o_we"]
    assert "o_q" not in q


def test_active_low_is_not_validity():
    assert riv.qualifiers_from_statements(
        [("o_data", "寫入資料, o_we 為 0 時清除 (o_we 低有效)")],
        _OUT, _IN) == {}


def _tb(proj):
    return riv.emit_case_oracle_from_ports(
        _CASE, "dut", _IN, _OUT, [],
        qualifiers=riv.declared_output_qualifiers(proj, _OUT, _IN))


def test_the_reset_value_tb_checks_the_unreset_output(tmp_path):
    tb = _tb(_l9(tmp_path, RESET_VALUE_ROWS, RESET_VALUE_PROSE))
    assert "X_EXEMPT" not in tb
    for n in ("o_q", "o_data"):
        assert re.search(rf"if \(\^\({n}\) === 1'bx\) begin\s+errors = "
                         rf"errors \+ 1;", tb), n


# ── the reviewer's measurement, as a test: iverilog on an UNRESET output ─────
UNRESET_DUT = """module dut(input clk, input rst_n, input [7:0] d,
  output reg o_q, output [7:0] o_data, output o_we, output o_cyc,
  output o_done, output o_busy);
  // o_q is NEVER reset: X until the first write the design never makes
  always @(posedge clk) if (1'b0) o_q <= 1'b1;
  assign o_data = 8'h00; assign o_we = 1'b0; assign o_cyc = 1'b0;
  assign o_done = 1'b0; assign o_busy = 1'b0;
endmodule
"""


def _require_simulator():
    path = os.pathsep.join(("/foss/tools/bin", os.environ.get("PATH", "")))
    for tool in ("iverilog", "vvp"):
        if shutil.which(tool, path=path) is None:
            pytest.fail(f"{tool}: command not found — this arm simulates the "
                        f"generated testbench and this host has no {tool}")
    return path


def test_the_unreset_output_fails_in_simulation(tmp_path):
    path = _require_simulator()
    tb = _tb(_l9(tmp_path, RESET_VALUE_ROWS, RESET_VALUE_PROSE))
    (tmp_path / "tb.v").write_text(tb)
    (tmp_path / "dut.v").write_text(UNRESET_DUT)
    env = dict(os.environ, PATH=path)
    b = subprocess.run(["iverilog", "-g2012", "-s", _CASE["name"], "-o",
                        str(tmp_path / "s.vvp"), str(tmp_path / "dut.v"),
                        str(tmp_path / "tb.v")], capture_output=True,
                       text=True, env=env)
    assert b.returncode == 0, b.stderr
    r = subprocess.run(["vvp", "-n", str(tmp_path / "s.vvp")],
                       capture_output=True, text=True, env=env)
    out = r.stdout + r.stderr
    assert "output 'o_q' is X/Z" in out, out
    assert "X_EXEMPT" not in out
    assert f"[TB {_CASE['name']}] PASS" not in out
