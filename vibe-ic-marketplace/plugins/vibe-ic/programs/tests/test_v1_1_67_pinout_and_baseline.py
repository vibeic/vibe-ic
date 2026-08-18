"""v1.1.67 — pinout_table_extractor (the universal port artifact) + its wiring into
the dual-pass program baseline. Pinout is present in essentially every spec, so it
is the single highest-coverage deterministic baseline contributor.
"""
import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parents[1]
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))
import pinout_table_extractor as P       # noqa: E402
import spec_artifact_dual_pass as DP       # noqa: E402


def test_bullet_form():
    t = (" - input  clk\n - input  [7:0] data\n - output q (4 bits)\n - inout sda\n")
    pins = P.extract_pinout(t)
    by = {p["name"]: p for p in pins}
    assert by["clk"]["dir"] == "in" and by["clk"]["width"] == 1
    assert by["data"]["width"] == 8
    assert by["q"]["dir"] == "out" and by["q"]["width"] == 4
    assert by["sda"]["dir"] == "inout"


def test_verilog_form():
    t = "module m(input wire clk, input [3:0] a, output reg [1:0] y);"
    by = {p["name"]: p for p in P.extract_pinout(t)}
    assert by["clk"]["dir"] == "in" and by["clk"]["width"] == 1
    assert by["a"]["width"] == 4 and by["y"]["width"] == 2 and by["y"]["dir"] == "out"


def test_pipe_table_form():
    t = ("| Signal | Dir | Width | Description |\n"
         "| clk    | in  | 1     | system clock |\n"
         "| dout   | out | 8     | data out |\n")
    by = {p["name"]: p for p in P.extract_pinout(t)}
    assert by["clk"]["dir"] == "in" and by["dout"]["width"] == 8 and by["dout"]["dir"] == "out"


def test_dedup_and_empty():
    assert P.extract_pinout("no ports here, just prose about a counter.") == []
    t = " - input clk\n - input clk\n"          # duplicate name
    assert len(P.extract_pinout(t)) == 1


def test_pinout_in_dual_pass_baseline():
    t = (" - input  clk\n - input  reset\n - input  in\n - output out\n\n"
         "Moore state machine. Synchronous active high reset to state A.\n\n"
         "  state | next state in=0, next state in=1 | output\n"
         "  A | A, B | 0\n  B | C, B | 0\n  C | A, D | 0\n  D | C, B | 1\n")
    base = DP.program_baseline(t)
    types = [e["element_type"] for e in base]
    assert "fsm_transition_table" in types          # the table artifact
    assert "pinout_table" in types                  # + the universal port baseline
    pinout = next(e for e in base if e["element_type"] == "pinout_table")
    assert len(pinout["data"]["pins"]) == 4
    assert pinout["metadata"]["source"] == "program"
