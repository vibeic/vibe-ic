"""v1.1.74 — directive-3 ②->① : a shared port_parser reads BOTH the bullet form
and the Verilog module-header form. The structural artifact (truth table / FSM /
K-map) is identical between the VerilogEval-v2 (bullet) and VerilogEval-human
(module-header) twins; the solvers' bullet-only parser silently SKIPped every
module-header prompt. With the shared parser, 7 VE-human twins (Prob069/056/079/
100/109/121/138 — already ① in v2) now fire + host-score PASS.
"""
import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parents[1]
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))
import port_parser as PP                  # noqa: E402
import oracle_table_synth as OT           # noqa: E402
import full_moore_fsm_synth as FM          # noqa: E402


def test_bullet_form():
    t = " - input  clk\n - input  y (3 bits)\n - output  Y1\n"
    ins, outs = PP.parse_ports(t)
    assert ("clk", 1) in ins and ("y", 3) in ins and ("Y1", 1) in outs


def test_verilog_module_header():
    t = "module TopModule (\n  input clk,\n  input [7:0] data,\n  output reg [1:0] q\n);"
    ins, outs = PP.parse_ports(t)
    by_i = dict(ins)
    assert by_i["clk"] == 1 and by_i["data"] == 8 and dict(outs)["q"] == 2


def test_prose_input_is_not_a_phantom_port():
    # 'input' in prose (outside a module header) must NOT become a port
    t = "The input signal a changes slowly. There is no module header here."
    assert PP.parse_ports(t) == ([], [])


def test_bullet_wins_when_both_present():
    t = (" - input clk\n - output q\n\nmodule TopModule(input clk, input extra, output q);")
    ins, outs = PP.parse_ports(t)
    assert dict(ins) == {"clk": 1} and dict(outs) == {"q": 1}    # bullet form, not 'extra'


def test_oracle_fires_on_module_header_truth_table():
    # the VE-human Prob069 shape: truth table + module header (no bullets)
    p = ("Create a combinational circuit that implements the truth table.\n\n"
         "  x3 | x2 | x1 | f\n  0 | 0 | 0 | 0\n  0 | 0 | 1 | 0\n  0 | 1 | 0 | 1\n"
         "  0 | 1 | 1 | 1\n  1 | 0 | 0 | 0\n  1 | 0 | 1 | 1\n  1 | 1 | 0 | 0\n  1 | 1 | 1 | 1\n\n"
         "module TopModule (\n  input x3,\n  input x2,\n  input x1,\n  output f\n);\n")
    rtl = OT.synth(p, "TopModule")
    assert rtl and "module TopModule" in rtl


def test_fsm_fires_on_module_header():
    p = ("Moore state machine. Synchronous active high reset to state A.\n\n"
         "  state | next state in=0, next state in=1 | output\n"
         "  A | A, B | 0\n  B | C, B | 0\n  C | A, D | 0\n  D | C, B | 1\n\n"
         "module TopModule (\n  input clk,\n  input reset,\n  input in,\n  output out\n);\n")
    assert FM.synth(p, "TopModule") is not None
