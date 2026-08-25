"""prose_interface_bridge_md — a GENERAL CVDP-markdown port reader bridging CVDP's
section-scoped interface form to the bullet form `port_parser.parse_ports` reads
(the same role prose_port_block_read plays for RTLLM's prose form).

Characterized gap (Shape-D CVDP enhancement, owner directive 2026-06-23
"program-first PARSING on CVDP"): `port_parser.parse_ports` understood the
VerilogEval bullet form and the Verilog module-header form, but NOT CVDP's
markdown interface family (`### Inputs` section + `- [7:0] in:` range-prefix
bullets / `- **`data_in`** (8-bits, [7:0]):` bold-paren bullets). So it returned
([],[]) on the spec-to-RTL prompts and the dual_pass interface extraction was
empty/wrong for these forms.

These tests pin:
  1. the section-scoped reader over the CVDP bullet forms (range-prefix bullet,
     bold-`name`-paren bullet, backtick-`input [hi:lo] name` decl bullet, bullet
     section headers `- Inputs:`/`- Output:`);
  2. the §4.05 no-misfire / no-leak envelope — a bold-WITHOUT-backtick prose phrase
     (**OUTPUT state**) is NOT a port; a Verilog value literal (`14'b001..`/`0x1234`)
     mid-bullet is NOT a port name; a parameter-expression width (`N*IN_WIDTH`,
     `BINARY_WIDTH`) DROPs the port (never fabricated);
  3. after bridging, the SHARED `port_parser.parse_ports` round-trips the emitted
     bullets exactly (the integration guarantee feeding registry / dual_pass).

The bridge is a GENERAL FORMAT READER, not keyed to any CVDP design name.
"""
import sys
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parents[1]
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))
import prose_interface_bridge_md as C               # noqa: E402
import port_parser as PP                  # noqa: E402


# --------------------------------------------------------------------------- #
# 1. the CVDP bullet/section forms
# --------------------------------------------------------------------------- #
def test_range_prefix_bullet_under_bullet_section_header():
    # form seen in 8x3_priority_encoder: "- Inputs:" header + "  - [7:0] in: ..."
    t = ("- Inputs:\n"
         "    - [7:0] in: An 8-bit input vector.\n"
         "- Output:\n"
         "    - [2:0] out: A 3-bit output vector.\n")
    ins, outs = C.parse_md_table_ports(t)
    assert ins == [("in", 8)]
    assert outs == [("out", 3)]


def test_bold_name_width_paren_and_range():
    # form seen in barrel_shifter: "- **`data_in`** (8-bits, [7:0]): ..."
    t = ("### Inputs\n"
         "- **`data_in`** (8-bits, [7:0]): The 8-bit input data.\n"
         "- **`shift_bits`** (3-bits, [2:0]): Shift amount.\n"
         "- **`left_right`** (1-bit): Direction.\n"
         "### Outputs\n"
         "- **`data_out`** (8-bits, [7:0]): The shifted result.\n")
    ins, outs = C.parse_md_table_ports(t)
    assert ins == [("data_in", 8), ("shift_bits", 3), ("left_right", 1)]
    assert outs == [("data_out", 8)]


def test_backtick_verilog_decl_with_inline_direction():
    # form seen in reverse_bits: "- **`input [31:0] num_in`**: ..."  (direction
    # keyword leads the backtick; the real name is num_in, width from the range).
    t = ("### Inputs\n"
         "- **`input [31:0] num_in`**: The 32-bit unsigned number.\n"
         "### Outputs\n"
         "- **`output [31:0] num_out`**: The bit-reversed number.\n")
    ins, outs = C.parse_md_table_ports(t)
    assert ins == [("num_in", 32)]
    assert outs == [("num_out", 32)]


def test_markdown_heading_section_scopes_direction():
    t = ("#### Inputs:\n"
         "- `clk` (1-bit): Clock.\n"
         "- `rst` (1-bit): Reset.\n"
         "#### Outputs:\n"
         "- `q` (4-bit): Result.\n")
    ins, outs = C.parse_md_table_ports(t)
    assert ins == [("clk", 1), ("rst", 1)]
    assert outs == [("q", 4)]


# --------------------------------------------------------------------------- #
# 2. §4.05 no-misfire / no-leak envelope
# --------------------------------------------------------------------------- #
def test_no_interface_section_is_noop():
    t = "Design a module that adds two numbers and outputs the sum.\n"
    assert C.parse_md_table_ports(t) == ([], [])
    assert C.bridge_prompt(t) == t          # unchanged -> downstream behaves as before


def test_bold_without_backtick_prose_is_not_a_port():
    # the dot_product_0002 false-positive: a "- **Input**:" header followed by a
    # behavioral bullet "**OUTPUT state**, the computed 32-bit ..." must NOT become
    # a port named OUTPUT/state with width 32.
    t = ("- **Input**:\n"
         "   - In the **OUTPUT state**, the computed 32-bit dot product is assigned.\n")
    ins, outs = C.parse_md_table_ports(t)
    assert ins == [] and outs == []


def test_value_literal_backtick_is_not_a_port_name():
    # gf_multiplier_0021: "- **a**: `14'b00100100001100` (lower 14 bits of `0x1234`)"
    # the bold name has no backtick; the only backticks are VALUE literals -> drop.
    t = ("### Inputs\n"
         "- **a**: `14'b00100100001100` (lower 14 bits of `0x1234`).\n")
    ins, outs = C.parse_md_table_ports(t)
    assert ins == [] and outs == []


def test_parameter_expression_width_is_dropped():
    # 16qam_mapper / binary_to_one_hot_decoder: width is a parameter expression, not
    # a single integer -> the port is DROPPED (never fabricate a width).
    t = ("### Inputs\n"
         "- `bits` (`N*IN_WIDTH`): Packed input bits.\n"
         "- `binary_in` (`BINARY_WIDTH` bits): Binary input.\n"
         "### Outputs\n"
         "- `one_hot_out` (`OUTPUT_WIDTH` bits): One-hot output.\n")
    ins, outs = C.parse_md_table_ports(t)
    assert ins == [] and outs == []


def test_contradictory_width_tokens_drop_the_port():
    t = ("### Inputs\n"
         "- `x` (8-bits, [3:0]): contradictory range vs token.\n")
    ins, outs = C.parse_md_table_ports(t)
    # range says 4, token says 8 -> ambiguous -> drop
    assert ("x", 8) not in ins and ("x", 4) not in ins


def test_table_header_words_never_become_ports():
    t = ("### Inputs\n"
         "- `Name`: the name column.\n"
         "- `Width`: the width column.\n")
    ins, outs = C.parse_md_table_ports(t)
    assert ins == [] and outs == []


def test_other_heading_closes_section_scope():
    t = ("### Inputs\n"
         "- `a` (4-bit): operand.\n"
         "### Behavioral Definition\n"
         "- `tmp` (8-bit): internal helper not a port.\n")
    ins, outs = C.parse_md_table_ports(t)
    assert ins == [("a", 4)]
    assert outs == []
    assert ("tmp", 8) not in ins and ("tmp", 8) not in outs


# --------------------------------------------------------------------------- #
# 3. integration: bridged bullets round-trip through the SHARED parse_ports
# --------------------------------------------------------------------------- #
def test_bridge_round_trips_through_shared_port_parser():
    t = ("### Inputs\n"
         "- **`data_in`** (8-bits, [7:0]): data.\n"
         "- **`left_right`** (1-bit): direction.\n"
         "### Outputs\n"
         "- **`data_out`** (8-bits, [7:0]): result.\n")
    bi, bo = C.parse_md_table_ports(t)
    pi, po = PP.parse_ports(C.bridge_prompt(t))
    assert pi == bi and po == bo
    assert ("data_in", 8) in pi and ("data_out", 8) in po


def test_interface_json_shape():
    t = ("### Inputs\n- `a` (4-bit): x.\n### Outputs\n- `y` (4-bit): z.\n")
    j = C.interface_json(t)
    assert j == {"inputs": [{"name": "a", "width": 4}],
                 "outputs": [{"name": "y", "width": 4}]}
