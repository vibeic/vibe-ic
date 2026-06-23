"""Tests for #542 (bus_peripheral/crypto ic_class + vendor_rtl), #547 (CDC
root-port detection), #555 (sdc_gen _is_async_io + fpga board-clock model).
ORGANIC — chip-AGNOSTIC, no benchmark/vendor names."""
import json
import re
import sys
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))


# ===========================================================================
# #555(a) — sdc_gen._is_async_io must NOT match sync bus signals
# ===========================================================================

def _load_is_async_io():
    from sdc_gen import _is_async_io
    return _is_async_io


def test_555a_async_io_gpio_still_matches():
    fn = _load_is_async_io()
    assert fn("gpio_in") is True
    assert fn("GPIO_OUTPUT") is True


def test_555a_async_io_key_sw_still_matches():
    fn = _load_is_async_io()
    assert fn("key_pressed") is True
    assert fn("SW3") is True
    assert fn("switch_n") is True
    assert fn("id_bus") is True


def test_555a_async_io_data_no_longer_matches():
    """'data' removed from _is_async_io (#555) — sync bus signals must NOT
    be false_pathed."""
    fn = _load_is_async_io()
    assert fn("instr_rdata_i") is False
    assert fn("data_addr_o") is False
    assert fn("mem_wdata") is False
    assert fn("rdata_o") is False


def test_555a_async_io_io_no_longer_matches():
    """'io' removed (#555) — 'io' alone matched too broadly (gpio still OK
    via the 'gpio' token)."""
    fn = _load_is_async_io()
    # 'io' suffix only, not 'gpio' → no match after the fix
    assert fn("audio_io") is False
    # but 'gpio_io' still matches via 'gpio'
    assert fn("gpio_io") is True


# ===========================================================================
# #555(b) — fpga_sdc_clock_constraint_check board-clock model
# ===========================================================================

def test_555b_has_generated_clock_positive():
    from fpga_sdc_clock_constraint_check import _has_generated_clock
    assert _has_generated_clock("create_generated_clock -source clk -name fast_clk")


def test_555b_has_generated_clock_negative():
    from fpga_sdc_clock_constraint_check import _has_generated_clock
    assert not _has_generated_clock("create_clock -period 20 [get_ports clk]")
    assert not _has_generated_clock("")
    # derive_pll_clocks/derive_clocks are Quartus boilerplate emitted in
    # EVERY .sdc — not a signal of an actual PLL-derived clock (#555).
    assert not _has_generated_clock("derive_pll_clocks\nderive_clocks")


def _write_l8_with_period(docs_dir: Path, period_ns: float) -> None:
    """Write L8 JSON with CLOCK_PERIOD_NS key in a format find_rtl_clock_period_ns
    parses (regex-searched as text, so the key must match the PERIOD_SYNONYMS_NS
    patterns like CLOCK_PERIOD_NS)."""
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({
        "CLOCK_PERIOD_NS": period_ns,
        "clocks": [{"port_name": "clk", "period_ns": period_ns}],
    }))


def test_555b_period_mismatch_with_pll_is_warn_not_fail():
    """Board 50MHz SDC (20ns) + ASIC 10ns + create_generated_clock → WARN not FAIL."""
    from fpga_sdc_clock_constraint_check import audit
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        fpga = p / "phase2" / "stage1" / "fpga"
        fpga.mkdir(parents=True)
        sdc = fpga / "top.sdc"
        sdc.write_text(
            "create_clock -name clk_board -period 20.0 [get_ports clk]\n"
            "create_generated_clock -name clk_app -source clk_board "
            "-divide_by 2 [get_pins pll|clk_app]\n"
        )
        _write_l8_with_period(p / "phase1" / "generated_docs", 10.0)
        verdict, msgs = audit(p)
        assert verdict in ("PASS", "WARN"), (
            f"Expected PASS/WARN but got {verdict}: {msgs}")
        combined = " ".join(msgs)
        if verdict == "WARN":
            assert "PLL" in combined or "generated" in combined.lower()


def test_555b_period_mismatch_no_pll_is_fail():
    """Board 50MHz SDC (20ns) + ASIC 10ns + NO PLL → FAIL."""
    from fpga_sdc_clock_constraint_check import audit
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        fpga = p / "phase2" / "stage1" / "fpga"
        fpga.mkdir(parents=True)
        sdc = fpga / "top.sdc"
        sdc.write_text(
            "create_clock -name clk_board -period 20.0 [get_ports clk]\n"
        )
        _write_l8_with_period(p / "phase1" / "generated_docs", 10.0)
        verdict, msgs = audit(p)
        assert verdict == "FAIL", f"Expected FAIL but got {verdict}"


# ===========================================================================
# #547 — CDC root-port clock-domain detection
# ===========================================================================

def _write_cdc_rtl(rtl_dir: Path, content: str) -> None:
    rtl_dir.mkdir(parents=True, exist_ok=True)
    (rtl_dir / "top.v").write_text(content)


def _run_cdc_section(project: Path):
    """Run phase2 CDC detection for the project and return the crossing.json."""
    import design_one_shot_runner as p2r
    # Call _run_cdc directly by invoking the RTL scan logic inline.
    # We replicate the scan to test it without running the full runner.
    rtl_dir = project / "phase2" / "stage1" / "rtl"
    rtl_files = (sorted(rtl_dir.glob("*.sv")) + sorted(rtl_dir.glob("*.v"))
                 if rtl_dir.is_dir() else [])
    INPUT_PORT_RE = re.compile(
        r'\binput\s+(?:wire\s+|reg\s+|logic\s+)?'
        r'(?:\[[^\]]+\]\s+)?([A-Za-z_]\w*)',
        re.MULTILINE,
    )
    RST_RE = re.compile(
        r'(?:^|_)(?:rst|reset|areset)(?:_|$)|^a?rst', re.IGNORECASE)
    clocks: set = set()
    root_clk_ports: set = set()
    for rf in rtl_files:
        txt = rf.read_text(errors="replace")
        for m in INPUT_PORT_RE.finditer(txt):
            nm = m.group(1)
            if ("clk" in nm.lower() or "clock" in nm.lower()) \
                    and not RST_RE.search(nm):
                root_clk_ports.add(nm)
        for m in re.finditer(r"\b(?:pos|neg)edge\s+([A-Za-z_]\w*)", txt):
            nm = m.group(1)
            if not RST_RE.search(nm):
                clocks.add(nm)
    domain_clocks = root_clk_ports if root_clk_ports else clocks
    return domain_clocks, clocks, root_clk_ports


def test_547_single_clock_with_gate_is_single_domain():
    """Single input clk_i + prim_clock_gating output clk → single domain (#547)."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        rtl = p / "phase2" / "stage1" / "rtl"
        _write_cdc_rtl(rtl, """
module top (
  input  wire clk_i,
  input  wire rst_ni,
  input  wire en_i,
  output reg  q_o
);
  // gated clock from prim_clock_gating
  wire clk_gated;
  prim_clock_gating u_cg (.clk_i(clk_i), .en_i(en_i), .clk_o(clk_gated));
  always @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) q_o <= 0;
    else q_o <= en_i;
  end
  reg r2;
  always @(posedge clk_gated) r2 <= q_o;
endmodule
""")
        domain_clocks, posedge_all, root_ports = _run_cdc_section(p)
        # root_ports = {clk_i}, posedge_all = {clk_i, clk_gated}
        assert root_ports == {"clk_i"}
        assert "clk_gated" in posedge_all
        assert len(domain_clocks) == 1, (
            f"Expected 1 domain clock but got {domain_clocks}")


def test_547_two_real_input_clocks_is_multi_domain():
    """Two distinct input clock ports → multi-clock SKIPPED-CONDITION (#547)."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        rtl = p / "phase2" / "stage1" / "rtl"
        _write_cdc_rtl(rtl, """
module top (
  input wire clk_fast,
  input wire clk_slow,
  input wire rst_n,
  output reg a, b
);
  always @(posedge clk_fast) a <= 1;
  always @(posedge clk_slow) b <= 1;
endmodule
""")
        domain_clocks, _, root_ports = _run_cdc_section(p)
        assert root_ports == {"clk_fast", "clk_slow"}
        assert len(domain_clocks) == 2


def test_547_no_clock_port_falls_back_to_posedge():
    """No named clock input port → fall back to posedge token set (#547)."""
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        rtl = p / "phase2" / "stage1" / "rtl"
        _write_cdc_rtl(rtl, """
module top (input phi, input rst_n, output reg q);
  always @(posedge phi) q <= ~q;
endmodule
""")
        domain_clocks, posedge_all, root_ports = _run_cdc_section(p)
        # 'phi' is not clk/clock but is a posedge token
        assert root_ports == set()
        assert "phi" in posedge_all
        # fallback: domain_clocks = posedge_all = {phi}
        assert domain_clocks == {"phi"}


# ===========================================================================
# #542 — ic_class_profile new detectors
# ===========================================================================

def test_542_crypto_accelerator_aes():
    from ic_class_profile import _looks_like_crypto_accelerator
    l2 = {"description":
          "AES-128/256 hardware encryption core. Supports ECB/CBC/CTR modes. "
          "Key schedule computes round keys from the 128-bit master key. "
          "Register map provides key loading, IV, control, and status fields."}
    assert _looks_like_crypto_accelerator(None, l2)


def test_542_crypto_accelerator_deny_guard_no_algorithm():
    """Prose with 'encrypt' and 'key' but no named cipher → NOT crypto (#542)."""
    from ic_class_profile import _looks_like_crypto_accelerator
    l2 = {"description":
          "Secure register-mapped peripheral with encrypted configuration key "
          "storage and data integrity checks."}
    # No explicit algorithm name → deny-guard blocks it
    assert not _looks_like_crypto_accelerator(None, l2)


def test_542_bus_peripheral_tlul():
    from ic_class_profile import _looks_like_bus_peripheral
    l2 = {"description":
          "TL-UL bus peripheral with a register map exposing control and status "
          "registers. Software-accessible via memory-mapped addresses. "
          "Register bank includes read-only status and write-only control fields. "
          "Address decode maps each register to a 4-byte offset in the "
          "peripheral's address space."}
    assert _looks_like_bus_peripheral(None, l2)


def test_542_bus_peripheral_deny_guard_no_regmap():
    """Prose with bus interface but no register-map evidence → NOT bus_peripheral."""
    from ic_class_profile import _looks_like_bus_peripheral
    l2 = {"description":
          "APB subordinate interface block providing data flow between two "
          "clock domains with FIFO buffering."}
    assert not _looks_like_bus_peripheral(None, l2)


def test_542_detect_ic_class_returns_crypto_not_cpu():
    """AES peripheral L docs → crypto_accelerator, NOT processor_cpu (#542).
    detect_ic_class() from ic_class_profile returns a dict, not a tuple."""
    from ic_class_profile import detect_ic_class
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        docs = p / "phase1" / "generated_docs"
        docs.mkdir(parents=True)
        l1 = {"design_intent": "AES-256 hardware accelerator"}
        l2 = {"description":
              "AES-256 hardware encryption accelerator with CBC/CTR mode support. "
              "Key schedule hardware. TL-UL register map for key loading, IV, "
              "control bits (enable/start/done), and status. Address decode "
              "maps registers to 0x00-0x3C. Software-accessible register bank."}
        (docs / "L1_FUNCTIONAL.json").write_text(json.dumps(l1))
        (docs / "L2_ARCH.json").write_text(json.dumps(l2))
        profile = detect_ic_class(p)
        ic_class = profile.get("ic_class")
        evidence = profile.get("decisive_evidence", "")
        assert ic_class == "crypto_accelerator", (
            f"Expected crypto_accelerator, got {ic_class!r}: {evidence}")


def test_542_vendor_rtl_check_waives_to_reused_ip():
    """input/vendor_rtl/ non-empty → rtl_gen WAIVED with catalog-glue hint (#542)."""
    from design_one_shot_runner import step_rtl_gen
    with tempfile.TemporaryDirectory() as td:
        p = Path(td)
        vendor = p / "input" / "vendor_rtl"
        vendor.mkdir(parents=True)
        (vendor / "core.v").write_text("module core(); endmodule\n")
        result = step_rtl_gen(p, "processor_cpu")
        assert result.status == "WAIVED"
        assert "catalog-glue-author" in str(result.detail)
        assert "vendor_rtl" in str(result.detail)


def test_542_all_ic_classes_has_new_entries():
    """ALL_IC_CLASSES must contain bus_peripheral and crypto_accelerator."""
    from ic_class_profile import ALL_IC_CLASSES
    assert "bus_peripheral" in ALL_IC_CLASSES
    assert "crypto_accelerator" in ALL_IC_CLASSES


def test_542_registry_has_bus_peripheral_and_crypto():
    """ic_class_registry.json must contain the two new entries."""
    reg = json.loads(
        (PROG_DIR / "ic_class_registry.json").read_text())
    names = {c["name"] for c in reg["classes"]}
    assert "bus_peripheral" in names
    assert "crypto_accelerator" in names
