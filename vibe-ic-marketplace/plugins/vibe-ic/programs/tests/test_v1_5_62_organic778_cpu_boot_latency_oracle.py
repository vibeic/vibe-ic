"""ORGANIC #778 companion — cpu_boot_latency_oracle_tb_gen.py.

The audited gap: subservient x sky130A / subservient x gf180mcuD's L10 case
`reset_n_cycle_instruction` ("Reset 解除後 N cycle 內取得第一條 instruction",
expected "N ≤ ... 典型 < 10 cycle") had NO real golden — testbench_gen only
ships the universal substance floor (no-X-after-reset) for a case with no
recognised oracle, and arith_oracle_tb_gen only recognises the closed-form
DATAPATH convention. Neither covers a reset-to-first-bus-activity LATENCY
case (a CPU-core / any-clocked-core convention).

This generator recognises the shape purely from (a) the case's own
stimulus+expected TEXT GRAMMAR (a reset-release reference + a first-activity
reference + an explicit "N cycle" bound) and (b) the DUT's own port surface
(a generic Wishbone-family bus-activity OUTPUT — cyc/stb/req/valid), and
emits a REAL, falsifiable TB. §4.05 FAIL-CLOSED: absent either signal it
returns None so the caller keeps the honest substance-floor scaffold.

Verified against the REAL subservient RTL (compiled + simulated with
iverilog/vvp, out of band from this suite): the generated TB genuinely PASSes
(first bus-activity at cycle 3, <= the declared max of 10) and genuinely
FAILs when the declared bound is tightened below the true latency — this
suite covers the PURE-PYTHON shape/emission logic (testable without
iverilog), mirroring arith_oracle_tb_gen's own test convention.
"""
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "cpu_boot_latency_oracle_tb_gen.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import cpu_boot_latency_oracle_tb_gen as G  # noqa: E402


_RESET_CASE = {
    "name": "reset_n_cycle_instruction",
    "kind": "functional_vector",
    "stimulus": "Reset 解除後 N cycle 內取得第一條 instruction",
    "expected": "N ≤ SERV-MINI 策略決定的最大 boot latency(典型 < 10 cycle)",
}

_INPUTS = [("i_clk", ""), ("i_rst", ""), ("i_gpio", ""),
          ("i_sram_data", "[7:0]"), ("i_sram_rdata", "[7:0]")]
_OUTPUTS = [("o_gpio", ""), ("o_sram_addr", "[9:0]"), ("o_sram_data", "[7:0]"),
           ("o_sram_we", ""), ("o_sram_cyc", ""), ("o_sram_wdata", "[7:0]")]


# ---------------------------------------------------------------------------
# shape detection
# ---------------------------------------------------------------------------
def test_is_boot_latency_case_true_for_real_case_shape():
    assert G.is_boot_latency_case(_RESET_CASE) is True


def test_is_boot_latency_case_false_without_cycle_bound():
    case = {"stimulus": "Reset 解除後取得第一條 instruction",
            "expected": "很快"}
    assert G.is_boot_latency_case(case) is False


def test_is_boot_latency_case_false_without_first_activity_reference():
    case = {"stimulus": "Reset 解除後正常運作", "expected": "N <= 10 cycle"}
    assert G.is_boot_latency_case(case) is False


def test_is_boot_latency_case_false_for_unrelated_case():
    case = {"stimulus": "(若 Plugin 選 M) Mul/Div 指令", "expected": "PASS"}
    assert G.is_boot_latency_case(case) is False


def test_extract_cycle_bound_parses_declared_number():
    assert G.extract_cycle_bound(_RESET_CASE) == 10


def test_extract_cycle_bound_none_when_absent():
    assert G.extract_cycle_bound({"stimulus": "x", "expected": "y"}) is None


# ---------------------------------------------------------------------------
# bus-activity output detection (Wishbone-family vocabulary, chip-AGNOSTIC)
# ---------------------------------------------------------------------------
def test_pick_bus_activity_output_matches_cyc_suffix():
    assert G._pick_bus_activity_output(_OUTPUTS) == "o_sram_cyc"


def test_pick_bus_activity_output_none_when_absent():
    outs = [("o_gpio", ""), ("o_data", "[7:0]")]
    assert G._pick_bus_activity_output(outs) is None


def test_pick_bus_activity_output_matches_alternate_vocabulary_tokens():
    for name in ("o_stb", "bus_req", "wb_valid", "m_strobe"):
        assert G._pick_bus_activity_output([(name, "")]) == name


# ---------------------------------------------------------------------------
# emission — real oracle TB text
# ---------------------------------------------------------------------------
def test_emit_case_oracle_from_ports_produces_real_tb():
    text = G.emit_case_oracle_from_ports(
        _RESET_CASE, "subservient", _INPUTS, _OUTPUTS, [])
    assert text is not None
    assert "module reset_n_cycle_instruction;" in text
    assert "subservient u_dut (" in text
    assert "o_sram_cyc" in text
    assert "max_cycles=10" in text
    assert "VIBEIC_TB_ORACLE: NONE" not in text   # a REAL oracle, not a stub
    assert "$fatal(1);" in text                    # genuinely falsifiable


def test_emit_case_oracle_from_ports_none_when_no_clock():
    inputs_no_clk = [("i_rst", ""), ("i_gpio", "")]
    text = G.emit_case_oracle_from_ports(
        _RESET_CASE, "subservient", inputs_no_clk, _OUTPUTS, [])
    assert text is None


def test_emit_case_oracle_from_ports_none_when_no_bus_activity_output():
    outs_no_activity = [("o_gpio", ""), ("o_data", "[7:0]")]
    text = G.emit_case_oracle_from_ports(
        _RESET_CASE, "subservient", _INPUTS, outs_no_activity, [])
    assert text is None


def test_emit_case_oracle_from_ports_none_for_non_boot_latency_case():
    other_case = {"name": "plugin_m_mul_div", "kind": "functional_vector",
                 "stimulus": "(若 Plugin 選 M) Mul/Div 指令", "expected": "PASS"}
    text = G.emit_case_oracle_from_ports(
        other_case, "subservient", _INPUTS, _OUTPUTS, [])
    assert text is None


def test_emit_case_oracle_from_ports_none_without_declared_bound():
    case_no_bound = {
        "name": "reset_n_cycle_instruction", "kind": "functional_vector",
        "stimulus": "Reset 解除後取得第一條 instruction",
        "expected": "很快",
    }
    text = G.emit_case_oracle_from_ports(
        case_no_bound, "subservient", _INPUTS, _OUTPUTS, [])
    assert text is None
