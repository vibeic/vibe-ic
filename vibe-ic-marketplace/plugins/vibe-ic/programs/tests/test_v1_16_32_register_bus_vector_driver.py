"""The vectors are driven over the bus the design SAYS they are driven over.

opentitan_aes states its own transport in its own brief — "經自建 TB 由 TL-UL
register interface 驅動完整 encrypt/decrypt round-trip" — so the register-write
sequence is not one of two options a tool may pick between. Binding the vectors
to a submodule's data ports instead would be going around the design's own
statement.

Everything the driver emits is DERIVED: the offsets from L4, the control word
from the design's own encoding tables, the start/done bits from the trigger and
status fields, the byte order from a sentence whose subject is the registers,
and the bus field names from the package staged in the design's own RTL.

Bidirectional, and the reverse direction is the one that keeps this honest: a
design that DECLARES the transport but whose register map is missing a piece
must still refuse, never fall back to a guessed address or a fixed wait.
"""
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

BUS_PKG = """package bus_pkg;
  typedef enum logic [2:0] {
    PutFullData = 3'h 0,
    Get         = 3'h 4
  } bus_a_op_e;
  typedef struct packed {
    logic        a_valid;
    bus_a_op_e   a_opcode;
    logic [31:0] a_address;
    logic  [3:0] a_mask;
    logic [31:0] a_data;
    logic        d_ready;
  } bus_h2d_t;
  typedef struct packed {
    logic        d_valid;
    logic [31:0] d_data;
    logic        d_error;
    logic        a_ready;
  } bus_d2h_t;
endpackage
"""

DOCS = {"widget_registers.txt": "All registers are little-endian.\n"}

CASE = {
    "name": "kav_ecb_block",
    "kind": "known_answer_vector",
    "algorithm": "aes",
    "inputs": {"key": "000102030405060708090a0b0c0d0e0f",
               "plaintext": "00112233445566778899aabbccddeeff"},
    "expected_outputs": {"ciphertext": "69c4e0d86a7b0430d8cdb78070b4c55a"},
    "parameters": {"key_len": 128, "mode": "ECB", "operation": "encrypt"},
    "citation": "FIPS-197 Appendix C.1",
    "source": "named_public_standard",
    "evidence": "FIPS-197",
    "transport": {"kind": "register_mapped"},
}


def _reg(name, addr, fields=()):
    return {"name": name, "address": addr,
            "fields": [{"field_name": f, "lsb": b, "msb": b}
                       for f, b in fields]}


def _l4(*, drop=None):
    """A register map in the shape a Comportable document produces."""
    regs = [_reg("CTRL_SHADOWED", "0x74",
                 (("OPERATION", 0), ("MODE", 2), ("KEY_LEN", 8))),
            _reg("TRIGGER", "0x80", (("START", 0),)),
            # The three status bits the design's own programmer's guide makes
            # the sequence wait on. A design that declares fewer simply gets
            # fewer waits — see the control at the bottom of this file.
            _reg("STATUS", "0x84", (("IDLE", 0), ("OUTPUT_VALID", 3),
                                    ("INPUT_READY", 4)))]
    for i in range(8):
        regs.append(_reg(f"KEY_SHARE0_{i}", f"0x{4 + 4 * i:x}"))
    for i in range(4):
        regs.append(_reg(f"DATA_IN_{i}", f"0x{0x54 + 4 * i:x}"))
        regs.append(_reg(f"DATA_OUT_{i}", f"0x{0x64 + 4 * i:x}"))
    if drop:
        regs = [r for r in regs if not str(r["name"]).startswith(drop)]
    return {"registers": regs}


def _l15():
    def t(name, rows):
        return {"name": f"CTRL_SHADOWED . {name}", "rows": rows}
    return {"fields": {"tables": [
        t("MODE", ["0x01 | AES_ECB | Electronic Codebook (ECB) mode."]),
        t("KEY_LEN", ["0x1 | AES_128 | 128-bit key length."]),
        t("OPERATION", ["0x1 | AES_ENC | Encryption."]),
    ]}}


def test_the_plan_is_derived_not_hard_coded():
    """The load-bearing red: every number in the plan comes from the design."""
    import register_bus_driver_gen as D
    plan, why = D.resolve_register_plan(CASE, _l4(), _l15(), DOCS)
    assert plan, why
    # ENC(0x1)<<0 | ECB(0x1)<<2 | AES_128(0x1)<<8
    assert plan["ctrl_value"] == 0x105, hex(plan["ctrl_value"])
    assert plan["endianness"] == "little", plan
    assert plan["start_field"] == "START" and plan["start_bit"] == 0
    assert plan["done_field"] == "OUTPUT_VALID" and plan["done_bit"] == 3
    assert sorted(plan["data_out"]) == [0, 1, 2, 3], plan["data_out"]
    assert plan["data_out"][0] == 0x64


def test_a_missing_register_refuses_rather_than_guessing():
    """The REVERSE control. A design that declares the transport and whose
    register map is missing a piece must fail closed — no guessed address, no
    fixed wait. Each arm names what is missing."""
    import register_bus_driver_gen as D
    for drop, expect in (("DATA_OUT", "no data_out register carries an address"),
                         ("STATUS", "declares no"),
                         ("TRIGGER", "declares no")):
        plan, why = D.resolve_register_plan(CASE, _l4(drop=drop), _l15(), DOCS)
        assert plan is None, f"{drop} was guessed at: {plan}"
        assert expect in why, (drop, why)
    # A control register that declares no MODE field.
    l4 = _l4()
    for r in l4["registers"]:
        if r["name"] == "CTRL_SHADOWED":
            r["fields"] = [f for f in r["fields"]
                           if f["field_name"] != "MODE"]
    plan, why = D.resolve_register_plan(CASE, l4, _l15(), DOCS)
    assert plan is None and "no MODE field" in why, why
    # An encoding table that gives no value for the mode this vector needs.
    l15 = _l15()
    l15["fields"]["tables"] = [t for t in l15["fields"]["tables"]
                               if not t["name"].endswith("MODE")]
    plan, why = D.resolve_register_plan(CASE, _l4(), l15, DOCS)
    assert plan is None and "no value for MODE" in why, why


def test_an_ambiguous_or_absent_byte_order_refuses():
    """Byte order decides what is written to every data register, so it may not
    be assumed. The subject is the REGISTERS: "the increment of the IV in CTR
    mode is big-endian" is a statement about arithmetic and must not settle it.
    """
    import register_bus_driver_gen as D
    order, why = D.register_endianness(
        {"d.txt": "All registers are little-endian. The increment of the IV "
                  "in CTR mode is big-endian."})
    assert order == "little", (order, why)
    order2, why2 = D.register_endianness({"d.txt": "It is a fast core."})
    assert order2 is None and "no sentence" in why2, why2
    order3, why3 = D.register_endianness(
        {"d.txt": "All registers are little-endian.",
         "e.txt": "These registers are big-endian."})
    assert order3 is None and "BOTH byte orders" in why3, why3


def test_the_contract_comes_from_the_staged_package():
    import register_bus_driver_gen as D
    bus, why = D.bus_contract(BUS_PKG)
    assert bus, why
    assert bus["h2d_type"] == "bus_pkg::bus_h2d_t", bus
    assert bus["opcodes"] == {"write": "3'h0", "read": "3'h4"}, bus["opcodes"]
    assert bus["h2d"]["addr"] == "a_address", bus["h2d"]
    empty, why2 = D.bus_contract("package p; endpackage")
    assert empty is None and "struct pair" in why2, why2


def test_the_emitted_tb_waits_on_the_designs_own_done_bit():
    """No fixed settle time: a multi-cycle block does not have one."""
    import register_bus_driver_gen as D
    plan, _ = D.resolve_register_plan(CASE, _l4(), _l15(), DOCS)
    bus, _ = D.bus_contract(BUS_PKG)
    tb = D.emit_sequence_tb(CASE, plan, bus, "dut_mod", "tl_i", "tl_o",
                            "clk_i", "rst_ni")
    body = "\n".join(l for l in tb.splitlines()
                     if not l.strip().startswith("//"))
    # The sequence now waits on the design's own bits through one bounded
    # helper — IDLE before configuration, INPUT_READY before data, and the done
    # bit before the compare — so the poll is asserted by its ARGUMENTS.
    assert "while (!rdata[b])" in body, "the status poll is not bounded"
    assert 'wait_bit(32\'h00000084, 3, "OUTPUT_VALID")' in body, body[:600]
    assert 'wait_bit(32\'h00000084, 0, "IDLE")' in body, body[:600]
    assert 'wait_bit(32\'h00000084, 4, "INPUT_READY")' in body, body[:600]
    assert "$fatal(1)" in body
    assert "errors = errors + 1" in body
    # the expected words are literals, little-endian, from the vector itself
    assert "32'hd8e0c469" in body and "32'h5ac5b470" in body, body[-800:]
    assert "32'h00000105" in body, "the derived control word is not written"


def test_end_to_end_the_generated_tb_runs_and_one_byte_turns_it_red(tmp_path):
    """The forward control, on a real simulator, over the real bus sequence."""
    import pytest
    import shutil
    import register_bus_driver_gen as D
    iverilog, vvp = shutil.which("iverilog"), shutil.which("vvp")
    if not (iverilog and vvp):
        pytest.skip("NOT MEASURED HERE: no iverilog/vvp on PATH")
    # CAPABILITY PROBE, and it is loud on purpose. The simulator on PATH here
    # aborts elaborating a package-scoped enum
    # (`bus_pkg.sv:6: assert: elab_type.cc:86: failed assertion scope`), which
    # is a fact about that binary and not about the generated testbench. The
    # arms below WERE run, in the pinned image; the commit message carries the
    # two exit codes and the two printed lines. Skipping quietly here would be
    # the same shape as the comment this whole capture exists to remove.
    (tmp_path / "probe_pkg.sv").write_text(BUS_PKG)
    (tmp_path / "probe.sv").write_text(
        "module probe; bus_pkg::bus_h2d_t h;\n"
        "initial begin h = '0; $display(\"probe %b\", h.a_valid); $finish;"
        " end endmodule\n")
    probe = subprocess.run(
        [iverilog, "-g2012", "-o", "probe.vvp", "probe_pkg.sv", "probe.sv"],
        cwd=tmp_path, capture_output=True, text=True)
    if probe.returncode != 0:
        pytest.skip("NOT MEASURED HERE: the iverilog on PATH cannot elaborate "
                    "a package-scoped enum (" + (probe.stderr.strip().splitlines()
                    or ["no stderr"])[0][:120] + ") — measured in the pinned "
                    "image instead; see the commit message")
    plan, _ = D.resolve_register_plan(CASE, _l4(), _l15(), DOCS)
    bus, _ = D.bus_contract(BUS_PKG)
    (tmp_path / "bus_pkg.sv").write_text(BUS_PKG)
    (tmp_path / "tb.sv").write_text(
        D.emit_sequence_tb(CASE, plan, bus, "aes_mock", "tl_i", "tl_o",
                           "clk_i", "rst_ni"))
    (tmp_path / "mock.sv").write_text(MOCK)
    out = {}
    for tag, w3 in (("good", "5ac5b470"), ("bad", "5ac5b471")):
        src = (tmp_path / "tb.sv").read_text().replace(
            "aes_mock dut",
            "aes_mock #(.W0(32'hd8e0c469),.W1(32'h30047b6a),"
            f".W2(32'h80b7cdd8),.W3(32'h{w3})) dut")
        (tmp_path / f"tb_{tag}.sv").write_text(src)
        subprocess.run([iverilog, "-g2012", "-o", f"{tag}.vvp",
                        "bus_pkg.sv", "mock.sv", f"tb_{tag}.sv"],
                       cwd=tmp_path, check=True, capture_output=True)
        r = subprocess.run([vvp, f"{tag}.vvp"], cwd=tmp_path,
                           capture_output=True, text=True)
        out[tag] = (r.returncode, r.stdout)
    assert out["good"][0] == 0, out["good"]
    assert "PASS" in out["good"][1], out["good"]
    assert out["bad"][0] != 0, out["bad"]
    assert "FAIL" in out["bad"][1], out["bad"]


MOCK = """
// A minimal register-mapped device model. It is NOT the AES design: it exists
// so the generated driver can be run end to end. It obeys the handshake the
// sequence is built on and nothing more — IDLE and INPUT_READY out of reset, a
// multi-cycle operation started by a COMPLETE input block, and OUTPUT_VALID
// only when that operation has finished. It never asserts a bit the sequence
// is waiting for just because the sequence is waiting for it: an input block
// that is not fully written leaves it idle forever, which is what makes the
// end-to-end arm able to fail.
module aes_mock #(parameter [31:0] W0 = 0, W1 = 0, W2 = 0, W3 = 0) (
  input  logic clk_i,
  input  logic rst_ni,
  input  bus_pkg::bus_h2d_t tl_i,
  output bus_pkg::bus_d2h_t tl_o
);
  localparam [31:0] ADDR_STATUS   = 32'h84;
  localparam [31:0] ADDR_DATA_IN0 = 32'h54;
  localparam [31:0] ADDR_DATA_OUT0 = 32'h64;
  localparam integer LATENCY = 37;

  logic [3:0]  din_written;
  logic        busy;
  logic        out_valid;
  integer      cnt;
  logic [31:0] dout [0:3];

  wire        acc   = tl_i.a_valid & tl_o.a_ready;
  wire        is_wr = tl_i.a_opcode == bus_pkg::PutFullData;
  wire [31:0] addr  = tl_i.a_address;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      din_written <= 4'h0; busy <= 1'b0; out_valid <= 1'b0; cnt <= 0;
      tl_o.d_valid <= 1'b0; tl_o.d_data <= 32'h0;
      tl_o.a_ready <= 1'b1; tl_o.d_error <= 1'b0;
      dout[0] <= W0; dout[1] <= W1; dout[2] <= W2; dout[3] <= W3;
    end else begin
      tl_o.d_valid <= 1'b0;
      // A complete input block starts the operation; a partial one does not.
      if (din_written == 4'hF && !busy && !out_valid) begin
        busy <= 1'b1; cnt <= 0; din_written <= 4'h0;
      end
      if (busy) begin
        cnt <= cnt + 1;
        if (cnt >= LATENCY) begin busy <= 1'b0; out_valid <= 1'b1; end
      end
      if (acc) begin
        if (is_wr) begin
          if (addr >= ADDR_DATA_IN0 && addr < ADDR_DATA_IN0 + 16 && !busy)
            din_written[(addr - ADDR_DATA_IN0) >> 2] <= 1'b1;
        end else begin
          tl_o.d_valid <= 1'b1;
          if (addr == ADDR_STATUS)
            // bit 4 INPUT_READY, bit 3 OUTPUT_VALID, bit 0 IDLE — the bit
            // positions the register map in this file declares.
            tl_o.d_data <= {27'h0, (!busy && !out_valid), out_valid,
                            2'b00, !busy};
          else if (addr >= ADDR_DATA_OUT0 && addr < ADDR_DATA_OUT0 + 16) begin
            tl_o.d_data <= dout[(addr - ADDR_DATA_OUT0) >> 2];
            if (addr == ADDR_DATA_OUT0 + 12) out_valid <= 1'b0;
          end else
            tl_o.d_data <= 32'h0;
        end
      end
    end
  end
endmodule
"""
