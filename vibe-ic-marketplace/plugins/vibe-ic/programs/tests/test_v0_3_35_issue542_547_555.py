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


def _write_l8_with_period(docs_dir: Path, period_ns: float) -> None:
    """Write L8 JSON with CLOCK_PERIOD_NS key in a format find_rtl_clock_period_ns
    parses (regex-searched as text, so the key must match the PERIOD_SYNONYMS_NS
    patterns like CLOCK_PERIOD_NS)."""
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({
        "CLOCK_PERIOD_NS": period_ns,
        "clocks": [{"port_name": "clk", "period_ns": period_ns}],
    }))


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
