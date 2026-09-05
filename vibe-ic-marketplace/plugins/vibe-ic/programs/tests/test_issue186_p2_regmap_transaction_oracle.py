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
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import regmap_transaction_tb_gen as G   # noqa: E402
import bit_level_full_stack_tb_check as B  # noqa: E402
import design_one_shot_runner as R     # noqa: E402

_HAVE_IVERILOG = bool(shutil.which("iverilog") and shutil.which("vvp"))
_needs_sim = pytest.mark.skipif(not _HAVE_IVERILOG,
                                reason="iverilog/vvp not available")


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


def _rtl(cfg_store=_CFG_CLEAN, ro_write_case=""):
    return (_RTL_TMPL.replace("{CFG_STORE}", cfg_store)
                     .replace("{RO_WRITE_CASE}", ro_write_case))


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


def _make_project(tmp_path, *, rtl=None, l5=_L5_MD, with_l9=False,
                  opcodes=None):
    proj = tmp_path / "proj"
    (proj / "phase2/stage1/rtl").mkdir(parents=True)
    (proj / "phase2/stage1/rtl/dut.v").write_text(rtl if rtl else _rtl())
    (proj / "input/docs").mkdir(parents=True)
    if l5 is not None:
        (proj / "input/docs/L5_register_map.md").write_text(l5)
    gd = proj / "phase1/generated_docs"
    gd.mkdir(parents=True)
    if with_l9:
        (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
            "top_module": "dut",
            "top_ports": [
                {"name": "clk", "direction": "input"},
                {"name": "rst_n", "direction": "input"},
                {"name": "cs", "direction": "input"},
                {"name": "we", "direction": "input"},
                {"name": "addr", "direction": "input"},
                {"name": "wdata", "direction": "input"},
                {"name": "rdata", "direction": "output"},
            ]}))
        (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps(
            {"opcodes": opcodes, "no_opcodes_in_input": False} if opcodes
            else {"opcodes": [], "no_opcodes_in_input": True}))
    return proj


# --------------------------------------------------------------------------
# 1. documented-register loading
# --------------------------------------------------------------------------
def test_markdown_register_table_is_parsed_with_range_expansion():
    md = _L5_MD + """
| `0x20-0x23` | `BLOCK0` ~ `BLOCK3` | W | 32 each | block window |
"""
    regs = G.parse_regmap_table(md)
    by_addr = {r["address_int"]: r for r in regs}
    assert by_addr[0x00]["access"] == "r"
    assert by_addr[0x04]["access"] == "r/w"
    assert by_addr[0x0C]["access"] == "w"
    # a hex RANGE expands to one entry per address, indexed from the base name
    assert [by_addr[a]["name"] for a in (0x20, 0x21, 0x22, 0x23)] == \
        ["BLOCK0", "BLOCK1", "BLOCK2", "BLOCK3"]


def test_a_port_table_is_not_mistaken_for_a_register_table():
    """No hex-address cell -> not a register row. Guards against the #186
    part-1 port table (same document family) being read as a register map."""
    port_table = """
| Signal | Width | Direction | Description |
|---|---|---|---|
| `clk` | 1 | input | clock |
| `rdata` | 32 | output | read data |
"""
    assert G.parse_regmap_table(port_table) == []


def test_synthesised_address_range_endpoints_are_excluded(tmp_path):
    """A `kind: indexed_register_address` entry carries a SYNTHESIS-DEFAULT
    access class, not a documented declaration.

    MEASURED why this matters: on real repo data such an endpoint claimed `RO`
    for an address the documents declare write-only. Scoring it read-only
    would have FAILed a correct design."""
    proj = tmp_path / "p"
    (proj / "phase1/generated_docs").mkdir(parents=True)
    (proj / "phase1/generated_docs/L4_REGMAP.json").write_text(json.dumps({
        "registers": [
            {"address": "0x08", "address_int": 8, "name": "CTRL",
             "access": "R/W"},
            {"address": "0x10", "address_int": 16, "name": "MEMMAP_LOW",
             "access": "RO", "kind": "indexed_register_address"},
        ]}))
    got = G._l4_json_registers(proj)
    assert [r["address_int"] for r in got] == [8]


def test_authored_table_overrides_the_downstream_json_extraction(tmp_path):
    proj = _make_project(tmp_path)
    (proj / "phase1/generated_docs/L4_REGMAP.json").write_text(json.dumps({
        "registers": [{"address": "0x0C", "address_int": 12, "name": "FIFO",
                       "access": "RO"}]}))
    regs = {r["address_int"]: r for r in G.load_documented_registers(proj)}
    # the authored L5 table says write-only; the extraction said read-only
    assert regs[0x0C]["access"] == "w"
    assert regs[0x0C]["source"] == "doc_table"


# --------------------------------------------------------------------------
# 2. bus-role detection
# --------------------------------------------------------------------------
def _ports(*spec):
    return [{"name": n, "direction": d, "width": w} for n, d, w in spec]


def test_detect_register_bus_two_component_spellings():
    bus = G.detect_register_bus(_ports(
        ("clk", "input", 1), ("reset_n", "input", 1), ("cs", "input", 1),
        ("we", "input", 1), ("address", "input", 8),
        ("write_data", "input", 32), ("read_data", "output", 32),
        ("error", "output", 1)))
    assert bus["address"] == "address" and bus["read_data"] == "read_data"
    assert bus["write_data"] == "write_data" and bus["we"] == "we"
    assert bus["cs"] == "cs" and bus["reset_active_low"] is True


def test_detect_register_bus_fused_spellings():
    bus = G.detect_register_bus(_ports(
        ("clk", "input", 1), ("rst_n", "input", 1), ("csn", "input", 1),
        ("wen", "input", 1), ("addr", "input", 8), ("wdata", "input", 16),
        ("rdata", "output", 16)))
    assert bus["cs_active_low"] is True and bus["we_active_low"] is True
    assert bus["data_width"] == 16 and bus["address_width"] == 8


def test_detect_register_bus_refuses_a_plain_datapath():
    """NO-LEAK: a design with no address bus is not a register slave, so the
    driver never fires on it and the historical skeleton path is untouched."""
    assert G.detect_register_bus(_ports(
        ("clk", "input", 1), ("rst_n", "input", 1), ("a", "input", 8),
        ("b", "input", 8), ("y", "output", 16))) is None


# --------------------------------------------------------------------------
# 3. scoring policy — what is scored, what is refused
# --------------------------------------------------------------------------
_RO = {"address_int": 0, "name": "ID", "access": "r", "source": "doc_table"}
_RW = {"address_int": 4, "name": "CFG", "access": "r/w", "source": "doc_table"}
_WO = {"address_int": 12, "name": "FIFO", "access": "w", "source": "doc_table"}


def _one(reg, obs, width=32):
    return G.score_transcript([reg], {reg["address_int"]: obs}, width)[0]


def test_read_only_write_ignored_is_scored_pass():
    v = _one(_RO, {"r0": 7, "r1": 7, "p1": 7, "p2": 7, "fp": 7})
    assert v["kind"] == "ro_write_ignore"
    assert (v["expected_bytes"], v["actual_bytes"], v["verdict"]) == \
        ("0x00000007", "0x00000007", "PASS")


def test_read_only_that_absorbs_a_write_is_scored_fail():
    """The write-leak defect: the address decoder routes writes into
    documented read-only space."""
    v = _one(_RO, {"r0": 7, "r1": 7, "p1": 0xFFFFFFF8, "p2": 7, "fp": 7})
    assert v["verdict"] == "FAIL" and v["expected_bytes"] == "0x00000007"


def test_hardware_updated_read_only_register_is_unverified_not_failed():
    """A volatile status/counter register has no stable doc golden. It must be
    reported UNVERIFIED — never scored, and never a FAIL on a correct design."""
    v = _one(_RO, {"r0": 7, "r1": 8, "p1": 9, "p2": 10, "fp": 11})
    assert v["verdict"] == "UNVERIFIED" and v["expected_bytes"] is None
    assert "hardware-updated" in v["source"]


def test_read_write_storage_fixed_point_is_scored_pass():
    v = _one(_RW, {"r0": 3, "r1": 3, "p1": 0xC, "p2": 3, "fp": 3})
    assert v["kind"] == "rw_storage_fixed_point"
    assert (v["expected_bytes"], v["actual_bytes"], v["verdict"]) == \
        ("0x00000003", "0x00000003", "PASS")


def test_read_write_storage_that_is_not_a_fixed_point_is_scored_fail():
    v = _one(_RW, {"r0": 3, "r1": 3, "p1": 0xC, "p2": 3, "fp": 0xC})
    assert v["verdict"] == "FAIL"
    assert (v["expected_bytes"], v["actual_bytes"]) == \
        ("0x00000003", "0x0000000C")


def test_unresponsive_address_is_unverified_not_a_vacuous_pass():
    """Vacuity guard: an address that answers two DIFFERENT written patterns
    identically has no observable storage, so a fixed-point comparison would
    pass for free. It must be UNVERIFIED instead."""
    v = _one(_RW, {"r0": 0, "r1": 0, "p1": 0, "p2": 0, "fp": 0})
    assert v["verdict"] == "UNVERIFIED" and v["expected_bytes"] is None
    assert "no observable storage" in v["source"]


def test_write_only_register_has_no_read_golden():
    v = _one(_WO, {"r0": 0, "r1": 0, "p1": 0, "p2": 0, "fp": 0})
    assert v["kind"] == "write_only" and v["expected_bytes"] is None


def test_naive_write_readback_is_REFUSED_as_an_oracle():
    """REGRESSION GUARD for the refused oracle.

    This transcript is the shape MEASURED on the real sha256 control register:
    an all-ones write to a CORRECT R/W register with self-clearing command bits
    and read-as-zero reserved bits reads back only the mode bit. A naive
    write-V-expect-V oracle would score this FAIL. It must be PASS, and the
    golden must be the SETTLED READ-BACK, never the written pattern."""
    v = _one(_RW, {"r0": 0x4, "r1": 0x4, "p1": 0x0, "p2": 0x4, "fp": 0x4})
    assert v["verdict"] == "PASS"
    assert v["expected_bytes"] == "0x00000004"
    assert v["expected_bytes"] != "0xFFFFFFFF"


def test_missing_observations_are_never_scored():
    v = _one(_RO, {"r0": 1})
    assert v["verdict"] == "UNVERIFIED" and v["expected_bytes"] is None


# --------------------------------------------------------------------------
# 4. end-to-end against a real simulator
# --------------------------------------------------------------------------
@_needs_sim
def test_generate_scores_documented_registers_on_a_clean_design(tmp_path):
    proj = _make_project(tmp_path)
    info = G.generate(proj, "dut")
    assert info["status"] == "scored", info
    assert info["registers_documented"] == 5
    assert info["scored_failed"] == 0
    by_id = {v["register"]: v for v in info["per_vector"]}
    assert by_id["ID"]["verdict"] == "PASS"
    assert by_id["ID"]["expected_bytes"] == "0x0BADC0DE"
    assert by_id["CFG"]["verdict"] == "PASS"
    assert by_id["SCRATCH"]["verdict"] == "PASS"
    # write-only port: no read golden; free-running counter: no stable golden
    assert by_id["FIFO"]["expected_bytes"] is None
    assert by_id["UPCNT"]["expected_bytes"] is None
    # v1.7.2 reclassified the `ro_write_ignore` oracle out of
    # `scored_with_golden`: ID's golden is the DESIGN'S OWN baseline read, so
    # it is a self-consistency check, not a document-derived one. Pinning both
    # halves — the count that moved AND where it moved to — so this records the
    # reclassification instead of merely tolerating it.
    assert info["scored_with_golden"] == 2
    assert info["scored_self_referential"] == 1
    assert by_id["ID"]["kind"] == "ro_write_ignore"
    assert by_id["ID"]["self_referential_golden"] is True
    assert by_id["CFG"]["self_referential_golden"] is False


@_needs_sim
def test_generate_catches_a_write_into_read_only_space(tmp_path):
    """MUTATION CONTROL — inject the defect the ro_write_ignore golden exists
    to catch and the very same vector must flip to FAIL."""
    proj = _make_project(tmp_path, rtl=_rtl(ro_write_case=_RO_LEAK))
    info = G.generate(proj, "dut")
    assert info["status"] == "scored"
    bad = [v for v in info["per_vector"] if v["verdict"] == "FAIL"]
    assert [v["register"] for v in bad] == ["ID"]
    assert bad[0]["kind"] == "ro_write_ignore"


@_needs_sim
def test_generate_catches_a_register_that_is_not_a_fixed_point(tmp_path):
    """MUTATION CONTROL for the second oracle class."""
    proj = _make_project(tmp_path, rtl=_rtl(cfg_store=_CFG_INVERTED))
    info = G.generate(proj, "dut")
    bad = [v for v in info["per_vector"] if v["verdict"] == "FAIL"]
    assert [v["register"] for v in bad] == ["CFG"]
    assert bad[0]["kind"] == "rw_storage_fixed_point"


@_needs_sim
def test_no_documented_register_map_means_no_driver(tmp_path):
    """NO-LEAK: without a documented register map there is no golden source,
    so the driver declines instead of inventing one."""
    proj = _make_project(tmp_path, l5=None)
    assert G.generate(proj, "dut")["status"] == "skipped"


# --------------------------------------------------------------------------
# 5. runner + gate integration
# --------------------------------------------------------------------------
@_needs_sim
def test_full_stack_step_publishes_real_scored_vectors(tmp_path):
    proj = _make_project(tmp_path, with_l9=True)
    res = R.step_full_stack_tb_gen(proj, "dut")
    rj = json.loads((proj / "phase2/stage1/sim_full_stack/results.json"
                     ).read_text())
    # THE TWO BLOCKS MUST AGREE. Before this was fixed the same file stated
    # `functional_coverage.scored_with_golden = 3` beside
    # `register_map_coverage.scored_with_golden = 2`, and the first is the one
    # `benchmark_verify_report` reads as the headline honesty number.
    assert rj["functional_coverage"]["scored_with_golden"] == 2
    assert rj["functional_coverage"]["self_referential"] == 1
    rmc = rj["register_map_coverage"]
    assert rmc["scored_with_golden"] == rj["functional_coverage"][
        "scored_with_golden"]
    assert (rmc["registers_documented"], rmc["registers_readable"]) == (5, 4)
    assert rmc["scored_passed"] == 2 and rmc["scored_failed"] == 0
    # the algorithmic RESULT oracle is still deferred -> no blanket PASS
    assert rj["functional_verified"] is False
    assert rmc["result_oracle_deferred"] is True
    assert res.status == "SKIP"
    assert "golden-scored 2 of 4" in res.detail


@_needs_sim
def test_full_stack_step_fails_when_a_golden_mismatches(tmp_path):
    proj = _make_project(tmp_path, with_l9=True,
                         rtl=_rtl(ro_write_case=_RO_LEAK))
    res = R.step_full_stack_tb_gen(proj, "dut")
    assert res.status == "FAIL"
    rj = json.loads((proj / "phase2/stage1/sim_full_stack/results.json"
                     ).read_text())
    # The RO-leak is caught by the `ro_write_ignore` oracle, which v1.7.2
    # moved to its own counter. The DETECTION is unchanged — the step still
    # FAILs — only the name of the counter it lands in.
    assert rj["register_map_coverage"]["self_referential_failed"] == 1
    assert rj["register_map_coverage"]["scored_failed"] == 0


@_needs_sim
def test_an_ic_with_a_command_protocol_keeps_the_byte_stream_path(tmp_path):
    """NO-LEAK: the driver is restricted to the shape #186 is about — an L3
    that honestly declares NO command protocol. An IC with real opcodes keeps
    the byte-stream vector schema verbatim even though its L3 here supplies no
    response templates (so the skeleton carries no golden either)."""
    proj = _make_project(tmp_path, with_l9=True,
                         opcodes=[{"hex": "0x70"}, {"hex": "0x72"},
                                  {"hex": "0x74"}])
    R.step_full_stack_tb_gen(proj, "dut")
    rj = json.loads((proj / "phase2/stage1/sim_full_stack/results.json"
                     ).read_text())
    assert "register_map_coverage" not in rj
    assert [v["vector_id"] for v in rj["per_vector"][:3]] == \
        ["vec_0x70_happy", "vec_0x72_happy", "vec_0x74_happy"]


def test_step_is_unchanged_when_the_driver_declines(tmp_path, monkeypatch):
    """NO-LEAK: when no register-map evidence is available the step emits the
    connectivity-only skeleton and nothing from the register-map path.

    THE EXPECTED POPULATION CHANGED, AND THAT CHANGE IS THE POINT. This used
    to assert `placeholder: 8` / `vectors_total: 8` for a fixture whose inputs
    justify ZERO vectors: all eight were `vec_brk_*` entries the producer
    appended in a `while len(...) < 8` loop whose own comment named the reason,
    "so MIN_VECTORS_FAIL=8 passes". Asserting that count pinned the padding in
    place. Nothing outside the producer ever read those entries — no program in
    the tree references `vec_brk_` or `bring_up_pad`; only test fixtures
    construct them — so removing them removes no information from any consumer.

    What this test is FOR is unchanged and still asserted: the register-map
    driver declining must leave the byte-stream path untouched. The population
    assertions are kept, corrected to the honest number, and the shortfall the
    padding used to hide is asserted too, so a future re-pad cannot pass here.
    """
    proj = _make_project(tmp_path, l5=None, with_l9=True)
    monkeypatch.setattr(R, "_v186_regmap_transaction_vectors",
                        lambda project, top: None)
    res = R.step_full_stack_tb_gen(proj, "dut")
    rj = json.loads((proj / "phase2/stage1/sim_full_stack/results.json"
                     ).read_text())
    # `self_referential` is emitted even at zero — a count that appears only
    # when non-zero cannot be used to show there were none.
    assert rj["functional_coverage"] == {"scored_with_golden": 0,
                                         "self_referential": 0,
                                         "placeholder": 0}
    assert rj["vectors_total"] == 0
    assert not any(str(v.get("vector_id", "")).startswith("vec_brk_")
                   for v in rj["per_vector"]), "the padding is back"
    # The shortfall is STATED rather than covered, and the record may not head
    # itself PASS over it.
    assert rj["oracle_scored_vectors"] == 0
    assert rj["functional_verified"] is False
    assert rj["verdict"] != "PASS" and rj["pass"] is not True
    assert "register_map_coverage" not in rj
    assert res.status == "SKIP" and "CONNECTIVITY-ONLY" in res.detail


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


@_needs_sim
def test_gate_no_longer_calls_a_scored_register_map_run_not_applicable(tmp_path):
    """The pre-fix fall-through said 'no L4/L5 register-map protocol' and
    returned a VACUOUS_PASS. With real scored transactions on disk that claim
    is false, so the gate must report the measured result instead."""
    proj = _make_project(tmp_path, with_l9=True)
    R.step_full_stack_tb_gen(proj, "dut")
    out = subprocess.run(
        [sys.executable, str(PLUGIN / "programs"
                             / "bit_level_full_stack_tb_check.py"), str(proj)],
        capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    got = json.loads(out.stdout)
    assert got["rule"] == "register_map_transaction_oracle_pass"
    assert got.get("vacuous_pass") is False
