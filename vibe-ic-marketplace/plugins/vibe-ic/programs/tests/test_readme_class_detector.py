#!/usr/bin/env python3
"""Tests for readme_class_detector.py — README-token IC class detector.

Pins the real weighted-scoring decision logic:
  * Unambiguous tokens (AES / SHA / JESD204B) route to the right class.
  * The issue-#35 example-list trap: a serdes IP whose README opens with
    a "such as Ethernet, SATA, PCIe, SDRAM Controller" motivating list
    must NOT misroute to memory_controller — the later JESD204B/SerDes
    evidence wins.
  * No positive marker -> (None, None) (v1.6.102 contract).
  * detect_class_with_fallback never returns None: positive analog
    marker -> pure_analog, else -> unknown_protocol_class.
  * detect_interface_types_from_readme counts protocol tokens and skips
    enumeration-prose ("such as ...") matches.
  * default_interface_type_for maps class -> default or None.

logic-pinned.
"""
from __future__ import annotations

import readme_class_detector as d


# ── detect_class_from_readme — unambiguous tokens ────────────────────
def test_aes_routes_to_block_cipher():
    cls, ev = d.detect_class_from_readme(
        "This is an AES-128 symmetric block cipher core.")
    assert cls == "crypto_block_cipher"
    assert ev["matched_token"]  # evidence carries the matched token


def test_sha_routes_to_hash():
    cls, _ = d.detect_class_from_readme("A SHA-256 hash engine.")
    assert cls == "crypto_hash"


# ── the issue-#35 example-list trap (the real regression guarded) ────
def test_example_list_trap_serdes_wins_over_sdram():
    readme = (
        "Useful for connecting components in modern SoCs such as Ethernet, "
        "SATA, PCIe, SDRAM Controller.\n"
        "This IP implements JESD204B SerDes with comma alignment.\n"
        "JESD204B link layer. JESD204B transport. SerDes PHY.\n"
    )
    cls, _ = d.detect_class_from_readme(readme)
    assert cls == "serdes_link"


# ── no positive marker -> (None, None) ───────────────────────────────
def test_no_marker_returns_none():
    assert d.detect_class_from_readme("A generic widget.") == (None, None)


def test_empty_returns_none():
    assert d.detect_class_from_readme("") == (None, None)
    assert d.detect_class_from_readme(None) == (None, None)


# ── detect_class_with_fallback — never None ──────────────────────────
def test_fallback_positive_class_wins():
    cls, _ = d.detect_class_with_fallback("AES-128 block cipher core.")
    assert cls == "crypto_block_cipher"


def test_fallback_positive_analog_marker():
    cls, ev = d.detect_class_with_fallback(
        "A bandgap voltage reference with op-amp and IBIAS network.")
    assert cls == "pure_analog"
    assert ev["extraction_strategy"] == "positive_analog_marker_fallback"


def test_fallback_unknown_protocol_class_default():
    cls, ev = d.detect_class_with_fallback("A generic widget with logic.")
    assert cls == "unknown_protocol_class"
    assert ev["extraction_strategy"] == "default_fallback_v1_6_522"


# ── detect_interface_types_from_readme ───────────────────────────────
def test_interface_types_counted_and_sorted():
    out = d.detect_interface_types_from_readme(
        "The core uses an AXI4 interface and an APB control bus. AXI4 again.")
    by_name = {e["name"]: e["occurrences"] for e in out}
    assert by_name["axi"] == 2
    assert by_name["apb"] == 1
    # sorted by occurrences desc -> axi first
    assert out[0]["name"] == "axi"


def test_interface_types_empty_input():
    assert d.detect_interface_types_from_readme("") == []
    assert d.detect_interface_types_from_readme(None) == []


# ── default_interface_type_for ───────────────────────────────────────
def test_default_interface_known_and_unknown():
    assert d.default_interface_type_for("crypto_hash") == "register_mapped"
    # too-varied classes default to None
    assert d.default_interface_type_for("serdes_link") is None
    assert d.default_interface_type_for(None) is None
