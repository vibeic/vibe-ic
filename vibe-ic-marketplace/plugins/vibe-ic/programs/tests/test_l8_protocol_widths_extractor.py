"""Tests for v0.1.65 R19 capture: L8 protocol-width parameter extractor +
runner overlay for bus_interconnect_protocol class.

Captured from v0.1.64 parity loop iteration 1: L8_RTL_CONSTANTS had 90
ABSENT findings on AMBA AXI parity vs Claude — almost all of them were
signal-width entries (AxLEN, AxSIZE, AxBURST, …) and named parameters
(DATA_WIDTH legal values) that Claude extracted but the chip-shape L8
emitter didn't carry.

Doctrine: general regex catalog (no AMBA/AXI brand strings); the
extractor catches signal widths in any protocol spec that uses
bracketed-bit-index conventions.
"""
import importlib
import re
import sys
from pathlib import Path
from _hostpaths import require_repo  # noqa: E402

PROGRAMS = Path(__file__).resolve().parents[1]


def _load():
    if "phase1_protocol_spec_extract" in sys.modules:
        del sys.modules["phase1_protocol_spec_extract"]
    sys.path.insert(0, str(PROGRAMS))
    return importlib.import_module("phase1_protocol_spec_extract")


# ── Extractor exists + general (no brand keywords) ───────────────────

def test_extract_l8_protocol_widths_callable():
    mod = _load()
    assert callable(getattr(mod, "extract_l8_protocol_widths", None))


def test_extractor_regex_block_has_no_brand_names():
    """Per memory 'enhancements must be general, not keyword': the
    extractor's REGEX DEFINITIONS must not contain brand strings (AMBA/
    AXI/Wishbone/etc.). Example mentions in DOCSTRING are OK — they
    explain what kinds of specs the general extractor targets."""
    src = (PROGRAMS / "phase1_protocol_spec_extract.py").read_text()
    # Look at only the actual `re.compile(...)` definitions in the L8 block
    start = src.find("# L8C — Protocol Width Parameters")
    end = src.find("def extract_l8_protocol_widths")
    block = src[start:end]
    # Find every re.compile(...) and check its raw string
    regex_strings = re.findall(r"re\.compile\(\s*[r]?\"(.*?)\"", block,
                                 re.DOTALL)
    combined = "".join(regex_strings).lower()
    for brand in ("amba", "axi", "ahb", "apb", "wishbone",
                  "tilelink", "avalonmm", "stbus"):
        assert brand not in combined, (
            f"brand keyword {brand!r} found in L8 extractor regex string; "
            f"per memory, must be general structural pattern only.")


# ── Pattern (1): named parameters with legal-value lists ────────────

def test_named_data_width_with_legal_list():
    mod = _load()
    text = ("The DATA_WIDTH parameter selects the data bus width.\n"
            "DATA_WIDTH can be 8, 16, 32, 64, 128, 256, 512, or 1024 bits.")
    result = mod.extract_l8_protocol_widths(text)
    # Emitted under width_parameters.DATA_WIDTH_bits.legal_values (R19
    # canonical-schema alignment with Claude's L8 shape).
    assert "DATA_WIDTH_bits" in result["width_parameters"]
    legal = result["width_parameters"]["DATA_WIDTH_bits"]["legal_values"]
    assert legal == [8, 16, 32, 64, 128, 256, 512, 1024]


def test_named_addr_width_extracted():
    mod = _load()
    text2 = ("The ID_WIDTH parameter is implementation-defined.\n"
              "Typical values: 4, 8, 16, 32 bits.")
    result2 = mod.extract_l8_protocol_widths(text2)
    assert "ID_WIDTH_bits" in result2["width_parameters"]


# ── Pattern (2): <signal>[msb:lsb] / [bit] ───────────────────────────

def test_signal_bit_range_captured():
    mod = _load()
    text = "The AxLEN[7:0] signal encodes burst length.\nIn AXI3, AxLEN[3:0] applies."
    result = mod.extract_l8_protocol_widths(text)
    assert "AxLEN_width" in result["width_parameters"]
    entry = result["width_parameters"]["AxLEN_width"]
    assert entry["bits"] == 8
    assert 4 in entry["observed_widths"]
    assert 8 in entry["observed_widths"]


def test_signal_single_bit_index_captured():
    mod = _load()
    text = "AxLOCK[0] indicates exclusive access in AXI4."
    result = mod.extract_l8_protocol_widths(text)
    assert "AxLOCK_width" in result["width_parameters"]
    assert result["width_parameters"]["AxLOCK_width"]["bits"] == 1


def test_multiple_signals_all_captured():
    mod = _load()
    text = ("AxSIZE[2:0] / AxBURST[1:0] / AxLEN[7:0] are signaled per "
            "transaction.")
    result = mod.extract_l8_protocol_widths(text)
    for sig in ("AxSIZE_width", "AxBURST_width", "AxLEN_width"):
        assert sig in result["width_parameters"]


# ── Evidence + provenance ────────────────────────────────────────────

def test_each_signal_has_bounded_evidence():
    """Evidence list must be bounded so a 10000-mention signal doesn't
    blow out the L doc."""
    mod = _load()
    text = "\n".join(["AxLEN[7:0] mention"] * 50)
    result = mod.extract_l8_protocol_widths(text)
    assert len(result["width_parameters"]["AxLEN_width"]["evidence"]) <= 3


def test_extracted_by_recorded():
    mod = _load()
    result = mod.extract_l8_protocol_widths("AxLEN[7:0]")
    assert "extract_l8_protocol_widths" in result["extracted_by"]


# ── Anti-false-positive ───────────────────────────────────────────────

def test_page_number_lists_rejected():
    """Lists like 'see pages 16, 17, 18' must NOT be captured as legal values
    (numbers too close together / max too small)."""
    mod = _load()
    text = "DATA_WIDTH discussed in pages 16, 17, 18, 19, 20."
    result = mod.extract_l8_protocol_widths(text)
    # legal_values should be empty (rejected) or DATA_WIDTH_bits absent
    if "DATA_WIDTH_bits" in result["width_parameters"]:
        legal = result["width_parameters"]["DATA_WIDTH_bits"]["legal_values"]
        assert 16 not in legal or max(legal) >= 100, (
            f"page-number list mis-captured as legal_values: {legal}")


def test_short_signal_names_not_captured():
    """Single-character or two-char signal names (a/b/io) shouldn't match —
    the regex requires at least 3 characters with proper bus-signal shape."""
    mod = _load()
    text = "Reset signal a[1:0] connects to the FSM."
    result = mod.extract_l8_protocol_widths(text)
    assert "a_width" not in result["width_parameters"]


# ── Runner wiring ────────────────────────────────────────────────────

def test_runner_imports_l8_widths_extractor():
    src = (PROGRAMS / "phase1_doc_one_shot_runner.py").read_text()
    assert "from phase1_protocol_spec_extract import extract_l8_protocol_widths" in src


def test_runner_only_overlays_for_bus_interconnect_protocol():
    """L8 widths overlay must be gated by ic_class == bus_interconnect_protocol
    so chip-class projects keep their existing L8 shape."""
    src = (PROGRAMS / "phase1_doc_one_shot_runner.py").read_text()
    overlay_block = src[src.find("[14b2/15] L8 protocol-width"):
                          src.find("[14c/15] L14-L18 protocol spec extract")]
    assert 'if _ic_class == "bus_interconnect_protocol"' in overlay_block


def test_runner_overlay_step_before_l14_l18():
    src = (PROGRAMS / "phase1_doc_one_shot_runner.py").read_text()
    l8w_pos = src.find("[14b2/15] L8 protocol-width")
    l14_pos = src.find("[14c/15] L14-L18 protocol spec extract")
    assert l8w_pos > 0 and l14_pos > 0
    assert l8w_pos < l14_pos


# ── End-to-end on AMBA AXI ────────────────────────────────────────────

def test_real_amba_axi_extraction_finds_many_widths():
    """The real PDF must yield ≥30 width entries and a DATA_WIDTH_bits slot."""
    inp = require_repo("benchmark-data/evaluation/phase1_parity/arm_aix/phase1/"
                       "input_doc/IHI0022H_amba_axi_protocol_spec.txt")
    if not inp.is_file():
        import pytest
        pytest.skip("AMBA AXI input_doc not present on this host")
    mod = _load()
    text = inp.read_text()
    result = mod.extract_l8_protocol_widths(text)
    wp = result["width_parameters"]
    assert len(wp) >= 30, (
        f"expected ≥30 width_parameters entries; got {len(wp)}")
    assert "DATA_WIDTH_bits" in wp
    legal = wp["DATA_WIDTH_bits"]["legal_values"]
    assert 8 in legal and 1024 in legal
