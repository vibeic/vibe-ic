"""GENERAL FRONT DOOR for the parameter-bound width contract (#2035 family 3).

A fix that only fires for an evaluation input is not a capability. This builds an
ORDINARY Phase-2 project on disk — a plain peripheral of the author's own
invention, its own module name, its own register offsets, its own bus package,
its own design notes — with NO harness, NO scorer, NO benchmark name and NO
design id anywhere, and drives the normal entry point
`known_answer_vector_tb_gen.emit_case_register_bus`.

The design declares a 12-bit address bus. Before this change the emitted driver
addressed it as 32 bits, which is not a neutral default: the transaction is
accepted and the upper bits are dropped. The design says 12, so the driver must
say 12 — reached automatically, with nobody remembering to apply a lesson.
"""
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import known_answer_vector_tb_gen as K       # noqa: E402

# A bus package of this design's own, addressed with 12 bits.
PKG = """package fabric_pkg;
  typedef enum logic [2:0] { PutFullData = 3'h 0, Get = 3'h 4 } fabric_a_op_e;
  typedef struct packed {
    logic            a_valid;
    fabric_a_op_e    a_opcode;
    logic [ADDR_W-1:0] a_address;
    logic      [3:0] a_mask;
    logic [DATA_W-1:0] a_data;
    logic            d_ready;
  } fabric_h2d_t;
  typedef struct packed {
    logic            d_valid;
    logic [DATA_W-1:0] d_data;
    logic            d_error;
    logic            a_ready;
  } fabric_d2h_t;
endpackage
"""

DUT = """module block_cipher_core #(
    parameter int ADDR_W = 12,
    parameter int DATA_W = 32
) (
  input  clk_i,
  input  rst_ni,
  input  fabric_pkg::fabric_h2d_t bus_i,
  output fabric_pkg::fabric_d2h_t bus_o
);
endmodule
"""

PORTS = [("input", "", "clk_i"), ("input", "", "rst_ni"),
         ("input", "", "bus_i"), ("output", "", "bus_o")]

NOTES = ("The gain block's registers are little-endian.\n"
         "Program the control word first, then the key, then the data.\n")


def _reg(name, addr, fields=()):
    return {"name": name, "address": addr,
            "fields": [{"field_name": f, "lsb": b, "msb": b} for f, b in fields]}


def _l4():
    regs = [_reg("CTRL", "0x20", (("OPERATION", 0), ("MODE", 2), ("KEY_LEN", 8))),
            _reg("TRIGGER", "0x30", (("START", 0),)),
            _reg("STATUS", "0x34", (("IDLE", 0), ("OUTPUT_VALID", 3)))]
    for i in range(4):
        regs.append(_reg(f"KEY_SHARE0_{i}", f"0x{0x40 + 4 * i:x}"))
        regs.append(_reg(f"DATA_IN_{i}", f"0x{0x60 + 4 * i:x}"))
        regs.append(_reg(f"DATA_OUT_{i}", f"0x{0x70 + 4 * i:x}"))
    return {"registers": regs}


def _l15():
    def t(n, rows):
        return {"name": f"CTRL . {n}", "rows": rows}
    return {"fields": {"tables": [
        t("MODE", ["0x01 | AES_ECB | Electronic Codebook (ECB) mode."]),
        t("KEY_LEN", ["0x1 | AES_128 | 128-bit key length."]),
        t("OPERATION", ["0x1 | AES_ENC | Encryption."]),
    ]}}


CASE = {
    "name": "kav_block_0", "kind": "known_answer_vector", "algorithm": "aes",
    "inputs": {"key": "000102030405060708090a0b0c0d0e0f",
               "plaintext": "00112233445566778899aabbccddeeff"},
    "expected_outputs": {"ciphertext": "69c4e0d86a7b0430d8cdb78070b4c55a"},
    "parameters": {"key_len": 128, "mode": "ECB", "operation": "encrypt"},
    "citation": "FIPS-197 Appendix C.1", "source": "named_public_standard",
    "evidence": "FIPS-197", "transport": {"kind": "register_mapped"},
}


def _project(tmp_path, dut_text=DUT, top=None):
    """An ordinary Phase-2 project tree. Nothing here is a harness."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "fabric_pkg.sv").write_text(PKG)
    (rtl / "block_cipher_core.sv").write_text(dut_text)
    if top:
        (rtl / "soc_top.sv").write_text(top)
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L4_REGMAP.json").write_text(json.dumps(_l4()))
    (gd / "L15_ENCODING_TABLES.json").write_text(json.dumps(_l15()))
    doc = tmp_path / "phase1" / "input_doc"
    doc.mkdir(parents=True)
    (doc / "programmers_guide.md").write_text(NOTES)
    return tmp_path


def test_plain_design_gets_its_declared_address_width(tmp_path):
    tb, why = K.emit_case_register_bus(_project(tmp_path), CASE,
                                       "block_cipher_core", PORTS)
    assert tb is not None, why
    assert "bus widths: addr=12 data=32" in why, why
    # the design says 12 bits, so the driver says 12 bits
    assert "task automatic bus_write(input [11:0] addr," in tb
    assert "task automatic bus_read(input [11:0] addr," in tb
    assert "12'h020" in tb, "the control register is not addressed at 12 bits"
    assert "32'h00000020" not in tb, "a 32-bit address literal survived"


def test_plain_design_also_gets_reset_under_active_controls(tmp_path):
    tb, why = K.emit_case_register_bus(_project(tmp_path), CASE,
                                       "block_cipher_core", PORTS)
    assert tb is not None, why
    assert "// --- reset asserted WHILE the controls are active ---" in tb
    assert "after reset under active controls" in tb


def test_an_instantiation_override_in_the_same_project_wins(tmp_path):
    """ALTERNATIVE ARCHITECTURE: the same design built with a wider data bus is
    driven at ITS width, not corrected back to the module default."""
    top = ("module soc_top;\n"
           "  block_cipher_core #(.DATA_W(64)) u_core "
           "(.clk_i(c), .rst_ni(r), .bus_i(a), .bus_o(b));\n"
           "endmodule\n")
    tb, why = K.emit_case_register_bus(_project(tmp_path, top=top), CASE,
                                       "block_cipher_core", PORTS)
    assert tb is not None, why
    assert "bus widths: addr=12 data=64" in why, why
    assert "reg [63:0] rdata;" in tb


def test_a_design_that_does_not_resolve_is_driven_exactly_as_before(tmp_path):
    """The refusal control: the width becomes unreadable, so the emission falls
    back to what it always was and the reason string NAMES what blocked it."""
    unresolved = DUT.replace("parameter int ADDR_W = 12,", "")
    tb, why = K.emit_case_register_bus(_project(tmp_path, dut_text=unresolved),
                                       CASE, "block_cipher_core", PORTS)
    assert tb is not None, why
    assert "address width unresolved" in why and "ADDR_W" in why
    assert "task automatic bus_write(input [31:0] addr," in tb
    assert "// --- reset asserted WHILE the controls are active ---" not in tb


# --------------------------------------------------------------------------
# The CANONICAL-FLOW chain, pinned link by link.
#
# The test above proves the fix fires for an ordinary project. This proves the
# flow actually WALKS here, so nobody has to remember to call it:
#
#   flow/phase1_phase2_phase3.yaml            step `testbench_gen`
#     -> design_one_shot_runner               runs the producer (ORGANIC #797)
#       -> testbench_gen._emit_case_known_answer_vector
#         -> known_answer_vector_tb_gen.emit_case_register_bus
#           -> register_bus_driver_gen.resolve_bus_widths + emit_sequence_tb
#
# These are WIRING PINS, not evidence the change did work: they are green
# against the base tree too, because they assert structure I did not modify.
# Their job is to fail LATER, if a link is removed out from under the
# front-door claim. Labelled here so no reader counts them as a red-turned-green.
# --------------------------------------------------------------------------
PLUGIN = PROGRAMS.parent


def test_the_flow_declares_the_testbench_gen_step():
    flow = (PLUGIN / "flow" / "phase1_phase2_phase3.yaml").read_text()
    assert "- testbench_gen" in flow, "the canonical flow no longer runs testbench_gen"


def test_testbench_gen_routes_a_bus_transport_case_to_the_register_bus_emitter():
    src = (PROGRAMS / "testbench_gen.py").read_text()
    assert "emit_case_register_bus(" in src, \
        "testbench_gen no longer reaches the register-bus emitter"


def test_the_runner_runs_the_testbench_gen_producer():
    src = (PROGRAMS / "design_one_shot_runner.py").read_text()
    assert "import testbench_gen" in src, \
        "the one-shot runner no longer runs the testbench_gen producer"


def test_the_register_bus_emitter_binds_the_width_contract():
    """The last link: the emitter resolves widths and hands them to the driver."""
    src = (PROGRAMS / "known_answer_vector_tb_gen.py").read_text()
    assert "resolve_bus_widths(" in src and "widths=_widths" in src
