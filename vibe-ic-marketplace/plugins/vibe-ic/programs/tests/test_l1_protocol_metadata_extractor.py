"""Tests for v0.1.68 R23 capture: L1_DATASHEET protocol-metadata extractor +
runner overlay for bus_interconnect_protocol class.

Captured from v0.1.67 parity loop iter 5: L1 had 19 ABSENT findings — all
protocol-document metadata fields (document_id, copyright, confidentiality,
endianness, purpose, intended_audience, burst_boundary_rule, ...) that
Claude extracted but the chip-shape L1 emitter doesn't carry.

Doctrine: general regex catalog (no AMBA/AXI brand strings); the extractor
catches document metadata in any spec document with standard cover-page
conventions.
"""
import importlib
import sys
from pathlib import Path
from _hostpaths import require_repo  # noqa: E402

PROGRAMS = Path(__file__).resolve().parents[1]


def _load():
    if "phase1_protocol_spec_extract" in sys.modules:
        del sys.modules["phase1_protocol_spec_extract"]
    sys.path.insert(0, str(PROGRAMS))
    return importlib.import_module("phase1_protocol_spec_extract")


# ── Extractor exists, general, anti-brand-keyword ────────────────────

def test_extract_l1_protocol_metadata_callable():
    mod = _load()
    assert callable(getattr(mod, "extract_l1_protocol_metadata", None))


def test_l1_extractor_regex_block_no_brand_keywords():
    """Per memory 'enhancements must be general, not keyword': regex
    DEFINITIONS in the L1 block must not contain brand names."""
    import re
    src = (PROGRAMS / "phase1_protocol_spec_extract.py").read_text()
    start = src.find("# L1 — Protocol Document Metadata")
    end = src.find("def extract_l1_protocol_metadata")
    block = src[start:end]
    regex_strings = re.findall(r"re\.compile\(\s*[r]?\"(.*?)\"", block,
                                 re.DOTALL)
    combined = "".join(regex_strings).lower()
    for brand in ("amba", "axi", "ahb", "apb", "wishbone",
                  "tilelink", "avalonmm", "stbus"):
        assert brand not in combined, (
            f"brand keyword {brand!r} in L1 extractor regex; per memory, "
            f"must be general structural pattern only.")


# ── Per-field extraction (synthetic) ─────────────────────────────────

def test_document_id_extracted():
    mod = _load()
    text = "Document Number: TC 0345B (ID040120)\nVersion 2.0"
    result = mod.extract_l1_protocol_metadata(text)
    assert "document_id" in result
    # The regex captures the canonical <ACRONYM> <DIGITS><suffix> form
    assert "TC" in result["document_id"]
    assert "0345" in result["document_id"]


def test_copyright_and_issuer_derived():
    mod = _load()
    text = "Copyright © 2003-2020 Acme Limited. All rights reserved."
    result = mod.extract_l1_protocol_metadata(text)
    assert result["copyright"].startswith("Copyright")
    assert result["issuer"] == "Acme Limited"


def test_confidentiality_extracted():
    mod = _load()
    text = "This document is Non-Confidential."
    assert _load().extract_l1_protocol_metadata(text).get("confidentiality") \
        .lower().startswith("non")


def test_endianness_detected():
    mod = _load()
    text = "The protocol supports little-endian and big-endian variants."
    result = mod.extract_l1_protocol_metadata(text)
    assert "endianness" in result
    assert "little" in result["endianness"].lower()
    assert "big" in result["endianness"].lower()


def test_purpose_extracted_from_this_specification_form():
    mod = _load()
    text = ("This specification defines the protocol semantics for the "
             "data bus, including handshake rules and burst transfers.")
    result = mod.extract_l1_protocol_metadata(text)
    assert "purpose" in result
    assert "defines" in result["purpose"] or "protocol" in result["purpose"]


def test_purpose_rejects_table_of_contents_lines():
    mod = _load()
    text = ("Purpose\n\n"
             "A1.1 About the protocol ........................................ A1-1\n"
             "A1.2 Architecture overview ..................................... A1-2")
    result = mod.extract_l1_protocol_metadata(text)
    # Must not pick the TOC line as purpose
    if "purpose" in result:
        assert "A1.1" not in result["purpose"]
        assert "....." not in result["purpose"]


def test_intended_audience_extracted():
    mod = _load()
    text = ("Intended audience\n\nThis specification is written for hardware "
             "and software engineers familiar with bus protocols.")
    result = mod.extract_l1_protocol_metadata(text)
    assert "intended_audience" in result
    assert "engineers" in result["intended_audience"]


def test_burst_boundary_rule_extracted():
    mod = _load()
    text = "Constraint: A burst must not cross a 4KB address boundary in this protocol."
    result = mod.extract_l1_protocol_metadata(text)
    assert "burst_boundary_rule" in result
    assert "4KB" in result["burst_boundary_rule"]


def test_electrical_and_package_default_false():
    """For protocol specs, electrical_specs_present and package_info_present
    default to False (sane for bus protocol documents)."""
    mod = _load()
    result = mod.extract_l1_protocol_metadata("any text")
    assert result["electrical_specs_present"] is False
    assert result["package_info_present"] is False


# ── Cross-extractor mirrors ──────────────────────────────────────────

def test_supported_data_bus_widths_mirrored_from_l8():
    """When l8_widths is provided, supported_data_bus_widths_bits mirrors
    DATA_WIDTH_bits.legal_values."""
    mod = _load()
    l8 = {"width_parameters": {
        "DATA_WIDTH_bits": {"legal_values": [8, 32, 128]}}}
    result = mod.extract_l1_protocol_metadata("any", l8_widths=l8)
    assert result["supported_data_bus_widths_bits"] == [8, 32, 128]


def test_release_history_mirrored_from_l14():
    """When l14_versioning is provided, release_history mirrors versions."""
    mod = _load()
    l14 = {"versions": [{"version": "1.0", "date": "2003"},
                        {"version": "2.0", "date": "2010"}]}
    result = mod.extract_l1_protocol_metadata("any", l14_versioning=l14)
    assert result["release_history"] == l14["versions"]


# ── Runner wiring ────────────────────────────────────────────────────

def test_runner_has_l1_protocol_metadata_step():
    src = (PROGRAMS / "phase1_doc_one_shot_runner.py").read_text()
    assert "[14c1/15] L1 protocol metadata overlay (R23)" in src


def test_runner_l1_overlay_gated_by_bus_interconnect_protocol():
    src = (PROGRAMS / "phase1_doc_one_shot_runner.py").read_text()
    block = src[src.find("[14c1/15] L1 protocol metadata"):
                 src.find("[14c2/15] L3 protocol mirror")]
    assert 'if _ic_r23 == "bus_interconnect_protocol"' in block


# ── End-to-end on real AMBA AXI ──────────────────────────────────────

def test_real_amba_axi_l1_extracts_doc_metadata():
    inp = require_repo("benchmark-data/evaluation/phase1_parity/arm_aix/phase1/"
                       "input_doc/IHI0022H_amba_axi_protocol_spec.txt")
    if not inp.is_file():
        import pytest
        pytest.skip("AMBA AXI input_doc not present on this host")
    mod = _load()
    text = inp.read_text()
    l8 = mod.extract_l8_protocol_widths(text)
    l14 = mod.extract_l14_versioning(text)
    result = mod.extract_l1_protocol_metadata(text, l8_widths=l8, l14_versioning=l14)
    # All 10+ metadata fields must be captured for AMBA AXI
    for k in ("document_id", "copyright", "confidentiality", "endianness",
                "intended_audience", "issuer", "burst_boundary_rule",
                "electrical_specs_present", "package_info_present",
                "supported_data_bus_widths_bits"):
        assert k in result, (
            f"R23 missed {k!r} on AMBA AXI. Got keys: {sorted(result.keys())}")
    # Specific value checks
    assert "0022" in result["document_id"]
    assert result["electrical_specs_present"] is False
    assert result["package_info_present"] is False
    assert 8 in result["supported_data_bus_widths_bits"]
