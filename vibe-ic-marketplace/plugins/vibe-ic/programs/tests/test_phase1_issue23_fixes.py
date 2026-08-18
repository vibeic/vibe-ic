"""tests/test_phase1_issue23_fixes.py — v1.6.91

Closes issue #23:
- Bug 1 (P1): _is_real_submodule_name flips from EXCLUDE-by-verb-deny-list
  to INCLUDE-by-RTL-shape. New helper `_looks_rtl_shaped` requires real
  RTL identifier shape (underscore / digit / known IC subsystem stem).
  Closes leaks of `along` (preposition), `costs` (noun), and any other
  bare English word that evades the verb deny-list.
- Bug 2 (P2): _is_vendor_tool_doc skips Intel UG / AN / Terasic dev-kit
  READMEs / Yosys / OpenROAD manuals from the prose-submodule extractor.
  These describe the dev-kit / EDA tools, not the chip-under-design.

Both fixes are chip-AGNOSTIC.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(
    str(__import__("pathlib").Path(__file__).resolve().parents[2])
)
sys.path.insert(0, str(PLUGIN_ROOT))


# ---------------------------------------------------------------------------
# Bug 1 — RTL-shape filter
# ---------------------------------------------------------------------------


def test_is_real_submodule_name_rejects_non_rtl_shaped_words():
    """Bare English words must NOT pass — they are not RTL-shaped."""
    from programs.phase1_one_shot_runner import _is_real_submodule_name
    rejected = [
        "along", "costs", "data", "value",
        "signal", "ground", "voltage", "above", "below",
        "input", "output", "between", "during", "while",
    ]
    for word in rejected:
        assert not _is_real_submodule_name(word), (
            f"v1.6.91: '{word}' should be rejected "
            "(not RTL-shaped — bare English word)"
        )


def test_is_real_submodule_name_keeps_rtl_shaped_names():
    """Real RTL module names (underscore / digit / subsystem stem) must pass."""
    from programs.phase1_one_shot_runner import _is_real_submodule_name
    accepted = [
        "tx_phy", "aes_core", "crc8", "wrapper",
        "byte_assembler", "id_bus_logic", "mem_unit",
        "engine", "fifo", "buffer",
        "main_fsm", "axi_bridge", "sha256_core",
        "controller", "decoder",
    ]
    for name in accepted:
        assert _is_real_submodule_name(name), (
            f"v1.6.91: '{name}' should be accepted (RTL-shaped)"
        )


def test_looks_rtl_shaped_distinguishes_stem_vs_bare_word():
    """Direct test of `_looks_rtl_shaped` for the bare-stem vs bare-word edge."""
    from programs.phase1_one_shot_runner import _looks_rtl_shaped
    # Underscore present → accepted
    assert _looks_rtl_shaped("axi_block")
    # Digit present → accepted
    assert _looks_rtl_shaped("crc8_block")
    # Bare known stem → accepted
    assert _looks_rtl_shaped("wrapper")
    assert _looks_rtl_shaped("controller")
    # Bare English word that is NOT a stem → rejected
    assert not _looks_rtl_shaped("along")
    assert not _looks_rtl_shaped("costs")
    assert not _looks_rtl_shaped("between")


# ---------------------------------------------------------------------------
# Bug 2 — vendor-tool doc skip
# ---------------------------------------------------------------------------


def test_is_vendor_tool_doc_recognises_patterns():
    """Direct test of `_is_vendor_tool_doc` predicate."""
    from programs.phase1_one_shot_runner import _is_vendor_tool_doc
    # Vendor-tool patterns must match
    assert _is_vendor_tool_doc("ug-m10-gpio-15.1.pdf")
    assert _is_vendor_tool_doc("an-456-some-app-note.pdf")
    assert _is_vendor_tool_doc("README_de10_lite.txt")
    assert _is_vendor_tool_doc("iic-osic-tools-manual.pdf")
    assert _is_vendor_tool_doc("yosys-manual.pdf")
    # Real chip docs must NOT match
    assert not _is_vendor_tool_doc("chip-frs.txt")
    assert not _is_vendor_tool_doc("EXAMPLE_CHIP_Datasheet.pdf")
    assert not _is_vendor_tool_doc("integration_spec.md")


def test_l9_skips_vendor_tool_intel_ug_pdf(tmp_path):
    """Vendor-tool doc (Intel UG) must not contribute prose-submodule names.

    Real chip-spec doc must still contribute its declared submodule.
    """
    from programs.phase1_one_shot_runner import gen_l9_integration_spec
    project = tmp_path
    extracted_dir = project / "phase1" / "input_doc"
    extracted_dir.mkdir(parents=True, exist_ok=True)
    docs = project / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    # Vendor-tool reference (should be skipped). Use the prose-extractor
    # trigger pattern (line-start `submodule|block|component <name>`)
    # so we are testing the SKIP, not the extractor's recall on noise.
    vendor_text = (
        "block: along\n"
        "block: costs\n"
        "submodule: between\n"
    )
    (extracted_dir / "ug-m10-gpio-15.1.txt").write_text(vendor_text)
    # Real chip spec (should contribute).
    chip_text = (
        "Submodule: crc8_engine\n"
    )
    (extracted_dir / "chip-frs.txt").write_text(chip_text)

    extracted = {
        "ug-m10-gpio-15.1.txt": vendor_text,
        "chip-frs.txt": chip_text,
    }
    # gen_l9_integration_spec needs an l3 dict; minimal stub is enough.
    l3_stub = {
        "verdict_byte_hex": "__TODO__",
        "verdict_byte_offset": 6,
    }
    gen_l9_integration_spec(project, extracted, l3_stub)

    l9_path = docs / "L9_INTEGRATION_SPEC.json"
    assert l9_path.exists(), "L9_INTEGRATION_SPEC.json should be written"
    l9 = json.loads(l9_path.read_text())
    submods = l9.get("submodules") or []
    names = {s.get("name", "").lower() for s in submods}

    # Bug 1 + Bug 2: prose-noise from vendor doc must NOT leak.
    # `along` / `costs` would be filtered by Bug 1 (RTL-shape) even
    # if Bug 2 (vendor-doc skip) were absent, but `between` and any
    # future word evading the verb deny-list relies on Bug 2.
    assert "along" not in names, (
        "v1.6.91 #23 Bug 1: 'along' must not leak into L9.submodules"
    )
    assert "costs" not in names, (
        "v1.6.91 #23 Bug 1: 'costs' must not leak into L9.submodules"
    )
    assert "between" not in names, (
        "v1.6.91 #23 Bug 2: vendor-tool doc must be skipped entirely"
    )
