"""#186 part 2 — the register-map TRANSACTION driver, and what it refuses to score.

MEASURED BEFORE (real repo data, `benchmark-data/ic/sha256`, re-run through
`design_one_shot_runner.step_full_stack_tb_gen`):

    functional_coverage = {"scored_with_golden": 0, "placeholder": 8}
    vectors_total = 8, vectors_passed = 0
    bit_level_full_stack_tb_check -> rc=1 FUNCTIONAL_COVERAGE_GAP
        "register-map protocol not yet synthesizable by the TB generator"

The byte-stream skeleton cannot reach this shape by construction: with no inout
pad `drive_byte` is a no-op and with no L3 opcodes there is no stimulus at all,
so the DUT's bus sits at zero for the whole simulation.

MEASURED AFTER (same data, same entry point):

    29 documented addresses probed, 13 of 13 readable registers golden-scored,
    all passing; bit_level_full_stack_tb_check -> rc=0.

WHAT IS SCORED — and why it is not a weakened notion of "functional vector".
Every scored vector compares a REALLY SIMULATED `read_data` against a golden
derived from the design documents' own access column, and every one of them
FAILs for real on an injected RTL defect (proven below and by the RTL mutation
control in the issue thread):

  * `ro_write_ignore`        — a documented read-only register must not change
                               under a write. Stability-probed first, so a
                               hardware-updated status register is reported
                               UNVERIFIED rather than scored against a golden
                               that does not exist.
  * `rw_storage_fixed_point` — the settled read-back of a documented R/W
                               register must be a fixed point of write-then-
                               read. Vacuity-guarded: an address that reads
                               back identically for two different written
                               patterns is UNVERIFIED, never scored.

WHAT IS REFUSED, and stays refused (regression-guarded below):

  * naive whole-register write/read-back (`write V, expect to read V`).
    MEASURED on the real sha256 RTL: a CORRECT control register with
    documented self-clearing command bits and read-as-zero reserved bits
    answers an all-ones write with `0x00000004`. Scoring that would FAIL
    correct silicon.
  * the RESULT oracle of an algorithm-defined operation (load operands, kick a
    command, poll status, read the computed result). The stimulus is
    synthesizable; the expected result is not. That remains the per-IC
    reference-model deferral, and `functional_verified` is NOT claimed.

chip-AGNOSTIC: bus roles come from a closed set of standard interface role
spellings, registers from the project's own documents. No chip/vendor/SKU
literal — the fixtures below are a synthetic register file, not any real IC.
"""
import json
import shutil
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import bit_level_full_stack_tb_check as B  # noqa: E402

_HAVE_IVERILOG = bool(shutil.which("iverilog") and shutil.which("vvp"))


# --------------------------------------------------------------------------
# Fixtures — a synthetic register file (no chip/vendor/SKU literal anywhere)
# --------------------------------------------------------------------------
_RTL_TMPL = """`timescale 1ns/1ps
module dut (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        cs,
    input  wire        we,
    input  wire [7:0]  addr,
    input  wire [31:0] wdata,
    output reg  [31:0] rdata
);
    localparam [7:0] A_ID   = 8'h00;   // documented R
    localparam [7:0] A_CFG  = 8'h04;   // documented R/W (reserved bits read 0)
    localparam [7:0] A_SCR  = 8'h08;   // documented R/W (plain storage)
    localparam [7:0] A_FIFO = 8'h0C;   // documented W
    localparam [7:0] A_CNT  = 8'h10;   // documented R, hardware-updated

    reg [31:0] id_reg, cfg_reg, scr_reg, fifo_reg, cnt_reg;

    always @(posedge clk) begin
        if (!rst_n) begin
            id_reg   <= 32'h0BADC0DE;
            cfg_reg  <= 32'h00000003;
            scr_reg  <= 32'h00000000;
            fifo_reg <= 32'h00000000;
            cnt_reg  <= 32'h00000000;
        end else begin
            cnt_reg <= cnt_reg + 1;
            if (cs && we) begin
                case (addr)
                    A_CFG:  cfg_reg  <= {CFG_STORE};
                    A_SCR:  scr_reg  <= wdata;
                    A_FIFO: fifo_reg <= wdata;
{RO_WRITE_CASE}
                    default: ;
                endcase
            end
        end
    end

    always @(posedge clk) begin
        if (!rst_n) rdata <= 32'h0;
        else if (cs && !we) begin
            case (addr)
                A_ID:   rdata <= id_reg;
                A_CFG:  rdata <= cfg_reg;
                A_SCR:  rdata <= scr_reg;
                A_CNT:  rdata <= cnt_reg;
                default: rdata <= 32'h0;
            endcase
        end
    end
endmodule
"""

_CFG_CLEAN = "wdata & 32'h0000000F"
_CFG_INVERTED = "~(wdata & 32'h0000000F) & 32'h0000000F"
_RO_LEAK = "                    A_ID:   id_reg   <= wdata;"




_L5_MD = """---
layer: L5
---

# L5 — Register Map

| Offset | Name | Access | Width | Description |
|---|---|---|---|---|
| `0x00` | `ID` | R | 32 | identity word |
| `0x04` | `CFG` | R/W | 32 | configuration; reserved bits read 0 |
| `0x08` | `SCRATCH` | R/W | 32 | scratch storage |
| `0x0C` | `FIFO` | W | 32 | write-only data port |
| `0x10` | `UPCNT` | R | 32 | free-running counter |
"""




# --------------------------------------------------------------------------
# 1. documented-register loading
# --------------------------------------------------------------------------








# --------------------------------------------------------------------------
# 2. bus-role detection
# --------------------------------------------------------------------------








# --------------------------------------------------------------------------
# 3. scoring policy — what is scored, what is refused
# --------------------------------------------------------------------------
_RO = {"address_int": 0, "name": "ID", "access": "r", "source": "doc_table"}
_RW = {"address_int": 4, "name": "CFG", "access": "r/w", "source": "doc_table"}
_WO = {"address_int": 12, "name": "FIFO", "access": "w", "source": "doc_table"}






















# --------------------------------------------------------------------------
# 4. end-to-end against a real simulator
# --------------------------------------------------------------------------








# --------------------------------------------------------------------------
# 5. runner + gate integration
# --------------------------------------------------------------------------








def _write_results(tmp_path, coverage, scored):
    sim = tmp_path / "phase2/stage1/sim_full_stack"
    sim.mkdir(parents=True)
    (sim / "results.json").write_text(json.dumps({
        "functional_coverage": {"scored_with_golden": scored,
                                "placeholder": 0},
        "register_map_coverage": coverage}))
    return sim


def test_gate_reports_a_measured_mismatch_as_a_hard_fail(tmp_path):
    sim = _write_results(tmp_path, {
        "registers_documented": 5, "registers_readable": 4,
        "scored_with_golden": 3, "scored_passed": 2, "scored_failed": 1}, 3)
    rmc = B.register_map_transaction_coverage(sim)
    verdict = B._regmap_transaction_verdict({"registers": 5}, rmc)
    assert verdict["pass"] is False
    assert verdict["rule"] == "register_map_transaction_oracle_fail"


def test_gate_pass_reports_the_denominator_and_defers_the_result_oracle(tmp_path):
    sim = _write_results(tmp_path, {
        "registers_documented": 5, "registers_readable": 4,
        "scored_with_golden": 3, "scored_passed": 3, "scored_failed": 0}, 3)
    verdict = B._regmap_transaction_verdict(
        {"registers": 5}, B.register_map_transaction_coverage(sim))
    assert verdict["pass"] is True
    assert verdict["vacuous_pass"] is False
    # the pillar is NOT claimed fully verified while the result oracle defers
    assert verdict["functional_verified"] is False
    assert "3 of 4" in verdict["rationale"]
