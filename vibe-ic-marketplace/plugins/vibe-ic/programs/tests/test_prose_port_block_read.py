"""prose_port_block_read — a GENERAL prose-port reader bridging RTLLM's "Input ports:/
Output ports:" prose form to the bullet form `port_parser.parse_ports` already reads.

Characterized gap (Shape-B RTLLM enhancement): `port_parser.parse_ports` understood
the VerilogEval bullet form and the VerilogEval-human module-header form, but NOT
RTLLM's prose port block — so it returned ([],[]) on every RTLLM prompt and every
registry deterministic solver SKIPped RTLLM at the port gate.

These tests pin:
  1. the bridge reads the three RTLLM width sources (explicit [hi:lo], "N-bit" desc
     token, implicit-1) and the full-width-colon variant;
  2. the §4.05 no-misfire / no-leak envelope (no port block -> no-op; contradictory
     widths -> DROP that port; prose outside the block is not captured);
  3. after bridging, `port_parser.parse_ports` reads the ports (the gate opens), and
     the bridged prompt is feedable straight into the registry solver chain.

The bridge is a GENERAL FORMAT READER, not keyed to any RTLLM design name.
"""
import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parents[1]
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))
import prose_port_block_read as BR          # noqa: E402
import port_parser as PP                # noqa: E402


# --------------------------------------------------------------------------- #
# 1. width sources
# --------------------------------------------------------------------------- #
def test_explicit_bus_range():
    t = ("Input ports:\n"
         "    a [7:0]: 8-bit input operand A.\n"
         "    cin: Carry-in input.\n"
         "Output ports:\n"
         "    sum [7:0]: 8-bit sum.\n"
         "    cout: Carry-out output.\n"
         "Implementation:\n")
    ins, outs = BR.parse_rtllm_ports(t)
    assert ins == [("a", 8), ("cin", 1)]
    assert outs == [("sum", 8), ("cout", 1)]


def test_width_from_description_token():
    t = ("Input ports:\n"
         "    data_in: 8-bit input data to be converted.\n"
         "Output ports:\n"
         "    data_out: 16-bit output data.\n"
         "Implementation:\n")
    ins, outs = BR.parse_rtllm_ports(t)
    assert ins == [("data_in", 8)] and outs == [("data_out", 16)]


def test_one_bit_and_fullwidth_colon():
    # RTLLM has both ASCII ':' and CJK full-width '：' (e.g. pulse_detect prompt).
    t = ("Input ports：\n"
         "    clk: Clock signal.\n"
         "    d: One-bit data input.\n"
         "Output ports：\n"
         "    q: single bit out.\n"
         "Implementation：\n")
    ins, outs = BR.parse_rtllm_ports(t)
    assert ins == [("clk", 1), ("d", 1)] and outs == [("q", 1)]


# --------------------------------------------------------------------------- #
# 2. §4.05 no-misfire / no-leak envelope
# --------------------------------------------------------------------------- #
def test_no_port_block_is_noop():
    t = "Please act as a verilog designer. Implement an adder. Give me code."
    assert BR.parse_rtllm_ports(t) == ([], [])
    assert BR.bridge_prompt(t) == t          # no-op bridge


def test_contradictory_widths_drop_the_port():
    # range says 8 bits, description says 4 bits -> ambiguous -> DROP x (never guess);
    # the unambiguous y is still kept.
    t = ("Input ports:\n"
         "    x [7:0]: a single 4-bit value here.\n"
         "Output ports:\n"
         "    y: 8-bit output.\n"
         "Implementation:\n")
    ins, outs = BR.parse_rtllm_ports(t)
    assert not any(n == "x" for n, _ in ins)   # dropped -> downstream solver SKIPs
    assert outs == [("y", 8)]


def test_prose_outside_block_not_captured():
    t = ("The input signal a drives the output. 8-bit values flow through.\n"
         "Input ports:\n"
         "    real_in [3:0]: 4-bit operand.\n"
         "Output ports:\n"
         "    real_out: result.\n"
         "Implementation:\n")
    ins, outs = BR.parse_rtllm_ports(t)
    assert ins == [("real_in", 4)] and outs == [("real_out", 1)]


def test_two_different_nbit_tokens_in_desc_drop():
    t = ("Input ports:\n"
         "    z: an 8-bit then 4-bit field.\n"
         "Output ports:\n"
         "    w: 2-bit output.\n")
    ins, outs = BR.parse_rtllm_ports(t)
    assert not any(n == "z" for n, _ in ins)   # contradictory -> dropped
    assert outs == [("w", 2)]


# --------------------------------------------------------------------------- #
# 3. the gate opens: port_parser reads the bridged prompt
# --------------------------------------------------------------------------- #
def test_bridge_opens_the_port_gate():
    rtllm = ("Implement an 8-bit adder.\n"
             "Input ports:\n"
             "    a [7:0]: 8-bit operand.\n"
             "    b [7:0]: 8-bit operand.\n"
             "    cin: carry in.\n"
             "Output ports:\n"
             "    sum [7:0]: 8-bit sum.\n"
             "    cout: carry out.\n"
             "Implementation:\n")
    # before: port_parser cannot read RTLLM prose -> empty (the characterized gap)
    assert PP.parse_ports(rtllm) == ([], [])
    # after: bridged bullets are read by the unchanged port_parser
    bridged = BR.bridge_prompt(rtllm)
    bi, bo = PP.parse_ports(bridged)
    assert dict(bi) == {"a": 8, "b": 8, "cin": 1}
    assert dict(bo) == {"sum": 8, "cout": 1}
    # the original prose is preserved after the bullet block (solvers still see it)
    assert "Implement an 8-bit adder." in bridged
