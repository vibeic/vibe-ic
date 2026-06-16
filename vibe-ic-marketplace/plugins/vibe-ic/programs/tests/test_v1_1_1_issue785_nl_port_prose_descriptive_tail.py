"""ORGANIC #785 [R9C1] — _specrtl_common._nl_port_is_prose missed the
DESCRIPTIVE-NOUN-TAIL / NOUN-BEFORE-COPULA prose shape, so _parse_nl_ports
harvested phantom ports named 'data'/'average' from datasheet prose sub-bullets,
which spec_coverage_check --strict (and spec_conformance_check) then hard-blocked
as UNCOVERED / missing STRUCTURAL ports — a CONSUMER false-positive that
hard-BLOCKed correct, simulation-PASS RTL (rc!=0).

ROOT CAUSE (instrumented on shipped 1.0.95, reproduced on 1.1.0): `_NL_PORT`
matches a prose bullet like
    - Input data stream.
    - Output average over the window.
    - Input data elements are divided into pairs before summation.
as a port because the common noun ('data'/'average') is deliberately NOT in
`_NL_PORT_PROSE_NAMES` (they are legitimate real port names elsewhere), the tail
carries no ':' heading, and the '^'-anchored `_NL_PORT_COPULA_RE` misses both a
noun-before-copula tail ("data elements ARE ...") and a copula-free noun tail
("stream.").

FIX (chip-AGNOSTIC, pure English grammar — no chip/vendor/SKU literal): extend
`_nl_port_is_prose` with a descriptive-noun-tail guard. When a bullet carries NO
width anchor and the tail (after an optional leading [range], no ':') begins with
a lowercase descriptive English word (not an `_`/digit identifier, not a kept
function word) AND EITHER ends in a sentence period '.' OR contains a copula
anywhere, treat it as prose and skip it.

§4.05 NO-LEAK (load-bearing half) — a genuine defect of the SAME class must STILL
hard-block after the fix:
  * a genuine missing width-anchored spec port  → coverage GAP / port-missing → BLOCK
  * a genuine uncovered registered/1-cycle latency requirement → coverage GAP → BLOCK
and every preserved real-port bullet shape stays harvested
  (width-anchored '- input enable (1 bit)', single-letter '- input a (8 bits)',
   bare trailing-description '- input clk system clock').
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN_ROOT = _PROGRAMS.parent
sys.path.insert(0, str(_PROGRAMS))
import _specrtl_common as SRC  # noqa: E402

_COVERAGE = _PROGRAMS / "spec_coverage_check.py"
_CONFORM = _PROGRAMS / "spec_conformance_check.py"


def _nl_port_names(line: str):
    return [p.name for p in SRC._parse_nl_ports(line)]


def _contract_port_names(spec: str):
    return [p.name for p in SRC.extract_spec_contract(spec, confirm=False).ports]


# ───────────────────────── POSITIVE (FP now passes) ─────────────────────────

@pytest.mark.parametrize("line", [
    "- Input data stream.",                                    # copula-free noun tail
    "- Output average over the window.",                       # copula-free noun tail
    "- Input data elements are divided into pairs before summation.",  # noun-before-copula
])
def test_descriptive_noun_tail_prose_is_not_a_port(line):
    """The issue's verbatim prose bullets must NOT be harvested as ports."""
    assert _nl_port_names(line) == [], _nl_port_names(line)


def test_phantom_data_average_not_in_contract():
    """The end-to-end contract used by spec_coverage / spec_conformance must
    contain ONLY the real width-anchored ports — no 'data'/'average' phantom."""
    spec = (
        "# Module: averager\n\n"
        "## Inputs and Outputs\n"
        "- input clk_in (1 bits)\n"
        "- input rst_n (1 bits)\n"
        "- input data_in (8 bits)\n"
        "- output data_out (8 bits)\n\n"
        "## Behavior\n"
        "- Input data stream.\n"
        "- Output average over the window.\n"
        "- Input data elements are divided into pairs before summation.\n"
    )
    names = _contract_port_names(spec)
    assert "data" not in names, names
    assert "average" not in names, names
    assert set(names) == {"clk_in", "rst_n", "data_in", "data_out"}, names


def test_spec_coverage_strict_passes_on_prose_bullets(tmp_path: Path):
    """End-to-end: the AFFECTED shape flips from hard-BLOCK to PASS (rc=0)."""
    prompt = tmp_path / "prompt.md"
    prompt.write_text(
        "# Module: averager\n\n"
        "## Inputs and Outputs\n"
        "- input clk_in (1 bits)\n"
        "- input rst_n (1 bits)\n"
        "- input data_in (8 bits)\n"
        "- output data_out (8 bits)\n\n"
        "## Behavior\n"
        "- Input data stream.\n"
        "- Output average over the window.\n"
        "- Input data elements are divided into pairs before summation.\n"
    )
    dut = tmp_path / "dut.v"
    dut.write_text(
        "module averager(input clk_in, input rst_n,\n"
        "  input [7:0] data_in, output reg [7:0] data_out);\n"
        "  always @(posedge clk_in or negedge rst_n)\n"
        "    if (!rst_n) data_out <= 8'd0; else data_out <= data_in;\n"
        "endmodule\n"
    )
    tb = tmp_path / "tb.v"
    tb.write_text(
        "module tb;\n reg clk_in=0,rst_n=0; reg [7:0] data_in=0; wire [7:0] data_out;\n"
        " averager dut(.clk_in(clk_in),.rst_n(rst_n),.data_in(data_in),.data_out(data_out));\n"
        " always #5 clk_in=~clk_in;\n"
        " initial begin rst_n=0; #12 rst_n=1; data_in=8'h11; #10; data_in=8'h22; #10; $finish; end\n"
        "endmodule\n"
    )
    r = subprocess.run(
        [sys.executable, str(_COVERAGE), "--prompt", str(prompt),
         "--rtl", str(dut), "--tb", str(tb), "--strict"],
        capture_output=True, text=True, cwd=str(_PLUGIN_ROOT))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "'data' is input" not in r.stdout, r.stdout
    assert "'average' is output" not in r.stdout, r.stdout


# ───────────────────── PRESERVE: real port bullets kept ─────────────────────

@pytest.mark.parametrize("line,expect", [
    ("- input enable (1 bit)", "enable"),       # width-anchored
    ("- input a (8 bits)", "a"),                # single-letter, width-anchored
    ("- output data_out (8 bits)", "data_out"), # real identifier port
    ("- input clk system clock", "clk"),        # bare identifier + trailing desc (no period)
])
def test_real_port_bullets_still_harvested(line, expect):
    names = _nl_port_names(line)
    assert names == [expect], (line, names)


def test_descriptive_tail_with_width_anchor_is_kept():
    """A genuine described port that ALSO carries a width anchor is NOT dropped
    by the new descriptive-noun guard (the guard is gated on NO width anchor)."""
    # '(8 bits)' is consumed by the regex width group, so has_width=True.
    assert _nl_port_names("- input data (8 bits) the input data stream") == ["data"]


# ──────────────────── §4.05 NO-LEAK (genuine defect blocks) ─────────────────

def test_no_leak_missing_width_anchored_port_still_blocks_coverage(tmp_path: Path):
    """A genuine missing width-anchored spec port still hard-BLOCKs (rc=1) — the
    prose-drop does not weaken the real port-coverage gate."""
    prompt = tmp_path / "prompt.md"
    prompt.write_text(
        "# Module: averager\n\n"
        "## Inputs and Outputs\n"
        "- input clk_in (1 bits)\n"
        "- input rst_n (1 bits)\n"
        "- input data_in (8 bits)\n"
        "- input enable_in (1 bits)\n"
        "- output data_out (8 bits)\n\n"
        "## Behavior\n"
        "- Input data stream.\n"
        "- Output average over the window.\n"
    )
    # RTL DROPS the real enable_in port (a defect of exactly this class).
    dut = tmp_path / "dut.v"
    dut.write_text(
        "module averager(input clk_in, input rst_n,\n"
        "  input [7:0] data_in, output reg [7:0] data_out);\n"
        "  always @(posedge clk_in or negedge rst_n)\n"
        "    if (!rst_n) data_out <= 8'd0; else data_out <= data_in;\n"
        "endmodule\n"
    )
    tb = tmp_path / "tb.v"
    tb.write_text(
        "module tb;\n reg clk_in=0,rst_n=0; reg [7:0] data_in=0; wire [7:0] data_out;\n"
        " averager dut(.clk_in(clk_in),.rst_n(rst_n),.data_in(data_in),.data_out(data_out));\n"
        " always #5 clk_in=~clk_in;\n"
        " initial begin rst_n=0; #12 rst_n=1; data_in=8'h11; #10; $finish; end\n"
        "endmodule\n"
    )
    r = subprocess.run(
        [sys.executable, str(_COVERAGE), "--prompt", str(prompt),
         "--rtl", str(dut), "--tb", str(tb), "--strict"],
        capture_output=True, text=True, cwd=str(_PLUGIN_ROOT))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "enable_in" in r.stdout, r.stdout
    assert "BLOCK" in r.stdout, r.stdout
    # and the prose phantoms are gone from the gap list
    assert "'data' is input" not in r.stdout, r.stdout


def test_no_leak_missing_port_still_blocks_conformance(tmp_path: Path):
    """spec_conformance_check (the other consumer) still emits a port-missing
    ERROR (rc=1) for a real omitted width-anchored port — and the phantom
    'data'/'average' ports do NOT inflate the spec-port set."""
    spec = tmp_path / "spec.md"
    spec.write_text(
        "# Module: averager\n\n"
        "## Inputs and Outputs\n"
        "- input clk_in (1 bits)\n"
        "- input rst_n (1 bits)\n"
        "- input data_in (8 bits)\n"
        "- input enable_in (1 bits)\n"
        "- output data_out (8 bits)\n\n"
        "## Behavior\n"
        "- Input data stream.\n"
        "- Output average over the window.\n"
        "- Input data elements are divided into pairs before summation.\n"
    )
    dut = tmp_path / "dut.v"
    dut.write_text(
        "module averager(input clk_in, input rst_n,\n"
        "  input [7:0] data_in, output reg [7:0] data_out);\n"
        "  always @(posedge clk_in or negedge rst_n)\n"
        "    if (!rst_n) data_out <= 8'd0; else data_out <= data_in;\n"
        "endmodule\n"
    )
    r = subprocess.run(
        [sys.executable, str(_CONFORM), "--spec", str(spec), str(dut)],
        capture_output=True, text=True, cwd=str(_PLUGIN_ROOT))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "port-missing" in r.stdout and "enable_in" in r.stdout, r.stdout
    # the phantom prose nouns must NOT appear as missing spec ports
    assert "port 'data'" not in r.stdout, r.stdout
    assert "port 'average'" not in r.stdout, r.stdout


def test_no_leak_uncovered_latency_still_blocks_coverage(tmp_path: Path):
    """A genuine registered/1-cycle latency requirement that the TB does NOT
    cover still hard-BLOCKs (rc=1)."""
    prompt = tmp_path / "prompt.md"
    prompt.write_text(
        "# Module: passt\n\n"
        "## Inputs and Outputs\n"
        "- input clk_in (1 bits)\n"
        "- input data_in (8 bits)\n"
        "- output data_out (8 bits)\n\n"
        "## Behavior\n"
        "- Output data stream.\n"
        "- Output latency is 1 clock cycle (the output is registered).\n"
    )
    dut = tmp_path / "dut.v"
    dut.write_text(
        "module passt(input clk_in, input [7:0] data_in, output reg [7:0] data_out);\n"
        "  always @(posedge clk_in) data_out <= data_in;\n"
        "endmodule\n"
    )
    tb = tmp_path / "tb.v"   # never checks the 1-cycle latency
    tb.write_text(
        "module tb;\n reg clk_in=0; reg [7:0] data_in=0; wire [7:0] data_out;\n"
        " passt dut(.clk_in(clk_in),.data_in(data_in),.data_out(data_out));\n"
        " always #5 clk_in=~clk_in;\n"
        " initial begin data_in=8'h11; #10; $finish; end\n"
        "endmodule\n"
    )
    r = subprocess.run(
        [sys.executable, str(_COVERAGE), "--prompt", str(prompt),
         "--rtl", str(dut), "--tb", str(tb), "--strict"],
        capture_output=True, text=True, cwd=str(_PLUGIN_ROOT))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "latency" in r.stdout and "BLOCK" in r.stdout, r.stdout


def test_other_prose_guards_unaffected():
    """The pre-existing prose guards (heading colon, prose-name set, anchored
    copula, function-word) still fire — the new guard is purely additive."""
    assert _nl_port_names("- Input ports:") == []                 # heading colon
    assert _nl_port_names("- Output latency is 1 cycle.") == []   # anchored copula / prose name
    assert _nl_port_names(
        "- Input and output AXI Stream signals adhere to the protocol.") == []  # function word
