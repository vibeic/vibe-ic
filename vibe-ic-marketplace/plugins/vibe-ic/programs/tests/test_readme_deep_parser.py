#!/usr/bin/env python3
"""Tests for readme_deep_parser.py — deep README spec-fact parser (#27).

Pins the regex extraction passes (key sizes / block width / S-box
parallelism / cipher modes / markdown references) AND the guardrails that
distinguish them from noise: CI/shields.io badge URLs route to
ignored_badges (not references), generic call-to-action anchors are
dropped, and English-prose tokens never pass the cipher-mode shape filter.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import readme_deep_parser as mod  # noqa: E402


# ----------------------------------------------------------------------
# PASS — a real crypto README populates every structured field.
# ----------------------------------------------------------------------
def test_pass_parses_all_facts():
    txt = (
        "# MyAES\n"
        "This core supports 128 and 256 bit keys.\n"
        "It processes one 128 bit block at a time.\n"
        "There are 4 S-boxes in the data path.\n"
        "Supports cipher modes such as CTR, CCM, GCM.\n"
        "\n"
        "See [NIST FIPS 197](https://csrc.nist.gov/publications/fips197).\n"
    )
    p = mod.parse_readme(txt)
    assert not p.is_empty()
    assert [e["value"] for e in p.key_lengths] == [[128, 256]]
    assert p.block_width_bits["value"] == 128
    assert p.parallelism_sboxes["value"] == 4
    assert [e["value"] for e in p.supported_modes] == ["CTR", "CCM", "GCM"]
    refs = [(e["name"], e["url"]) for e in p.references]
    assert ("NIST FIPS 197",
            "https://csrc.nist.gov/publications/fips197") in refs
    # every key-length entry carries readme_deep_parser provenance
    assert p.key_lengths[0]["evidence"]["extraction_strategy"] == \
        "readme_deep_parser"


# ----------------------------------------------------------------------
# Guardrails — the defects this parser was hardened against.
# ----------------------------------------------------------------------
def test_badge_url_routed_to_ignored_not_references():
    # A shields.io CI badge embedded as a click-wrapped image must NOT
    # land in references; it goes to ignored_badges. The real spec link
    # alongside it survives.
    txt = (
        "[![build](https://img.shields.io/badge/build-passing.svg)]"
        "(https://example.org/ci)\n"
        "See [Real Spec](https://example.org/spec.pdf) for details.\n"
    )
    p = mod.parse_readme(txt)
    ref_urls = [e["url"] for e in p.references]
    assert "https://example.org/spec.pdf" in ref_urls
    # the badge SVG never enters references
    assert all("shields.io" not in u for u in ref_urls)
    assert len(p.ignored_badges) == 1
    assert "shields.io" in p.ignored_badges[0]["url"]


def test_generic_anchor_and_numeric_cite_dropped():
    # "here" is a call-to-action anchor; bracket-numeric "[1]" carries no
    # bibliographic name -> both dropped by the reference-name cleaner.
    txt = (
        "Click [here](https://example.org/page).\n"
        "[1](https://example.org/cite).\n"
    )
    p = mod.parse_readme(txt)
    names = [e["name"] for e in p.references]
    assert "here" not in [n.lower() for n in names]
    assert "1" not in names and "[1" not in names


def test_cipher_mode_shape_filter_rejects_english_words():
    # _parse_modes_blob must reject ordinary English words but keep modes.
    assert mod._parse_modes_blob("THE GREAT CTR AND GCM") == ["CTR", "GCM"]
    assert mod._looks_like_cipher_mode("CTR") is True
    assert mod._looks_like_cipher_mode("GREAT") is False


def test_features_section_grouped_by_subsection():
    txt = (
        "## Features\n"
        "  PHY:\n"
        "    - Auto-Precharge\n"
        "  Core:\n"
        "    - ECC\n"
        "    - BIST\n"
        "## Usage\n"
    )
    feats = mod.extract_features_block(txt)
    assert "phy" in feats and "core" in feats
    assert [e["value"] for e in feats["core"]] == ["ECC", "BIST"]


# ----------------------------------------------------------------------
# Empty input -> empty ParsedReadme (no fabrication, is_empty True).
# ----------------------------------------------------------------------
def test_empty_readme_is_empty():
    p = mod.parse_readme("")
    assert p.is_empty()
    assert p.key_lengths == [] and p.references == []


def test_find_readme_text_prefers_input_docs():
    extracted = {
        "README.md": "input docs body",
        "__chip_root__/README.md": "chip root body",
    }
    text, src = mod.find_readme_text(extracted)
    assert text == "input docs body"
    assert src == "input/docs/README.md"


def test_find_readme_text_none_when_no_readme():
    text, src = mod.find_readme_text({"design.v": "module x; endmodule"})
    assert text is None and src is None
