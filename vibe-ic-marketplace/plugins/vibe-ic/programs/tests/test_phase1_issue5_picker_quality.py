"""tests/test_phase1_issue5_picker_quality.py — v1.6.58

Closes GitHub issue #5 BUG 1. Quality gates on `_ic_name_from_docs`:
- markdown punctuation strip (sha256 # → sha256)
- single-word stoplist reject (`# the` → fall through)
- FPGA-eval-board SKU reject (VCU1525 / Alveo / Arty / Nexys)
- prefix preservation (LiteDRAM stays LiteDRAM, not DRAM)
- never fuzz-match (verbatim source spans, no character drops)
"""
from __future__ import annotations

from programs.phase1_one_shot_runner import (
    _ic_name_from_docs, _strip_markdown_punct, _is_fpga_board_name,
)
import pytest


# ---------------------------------------------------------------------------
# _strip_markdown_punct unit tests.
# ---------------------------------------------------------------------------

def test_strip_trailing_atx_hash() -> None:
    assert _strip_markdown_punct("sha256 #") == "sha256"


def test_strip_leading_atx_hash() -> None:
    assert _strip_markdown_punct("# sha256") == "sha256"


def test_strip_setext_underline() -> None:
    assert _strip_markdown_punct("=====") == ""


def test_strip_markdown_emphasis() -> None:
    assert _strip_markdown_punct("**SHA-2**") == "SHA-2"
    assert _strip_markdown_punct("__core__") == "core"


def test_strip_keeps_internal_punctuation() -> None:
    """Internal `#` / `_` / `-` must be preserved (`SHA-1`, `LiteDRAM`)."""
    assert _strip_markdown_punct("SHA-1") == "SHA-1"
    assert _strip_markdown_punct("LiteDRAM") == "LiteDRAM"


# ---------------------------------------------------------------------------
# _is_fpga_board_name.
# ---------------------------------------------------------------------------

def test_fpga_board_xilinx_variants() -> None:
    for name in ("VCU1525", "VCU118", "KCU105", "ZCU106", "ZCU111"):
        assert _is_fpga_board_name(name), name


def test_fpga_board_terasic_intel_variants() -> None:
    for name in ("DE10", "DE10-Lite", "DE10-Nano", "DE2-115"):
        assert _is_fpga_board_name(name), name


def test_fpga_board_diligent_variants() -> None:
    for name in ("Arty-A7", "Nexys-A7", "Genesys2", "Alveo-U250"):
        assert _is_fpga_board_name(name), name


def test_fpga_board_does_not_match_real_ip_names() -> None:
    """`AES`, `LiteDRAM`, `ChaCha20`, `SHA-256` must NOT match."""
    for name in ("AES", "LiteDRAM", "ChaCha20", "SHA-256",
                 "DDR4", "BC1234", "EXAMPLE_CHIP"):
        assert not _is_fpga_board_name(name), name


# ---------------------------------------------------------------------------
# Issue #5 BUG 1 regression cases — picker quality.
# ---------------------------------------------------------------------------

def test_does_not_pick_the_from_h1() -> None:
    """Issue #5: block-cipher project picked `the` as ic_name. The
    new chain prioritises 'implementation of <X>' BEFORE H1 to
    avoid this."""
    extracted = {
        "README.md": (
            "# the AES core\n\n"
            "Verilog implementation of AES (NIST FIPS 197).\n"
        ),
    }
    name = _ic_name_from_docs(extracted)
    assert name != "the"
    # Should resolve to AES via impl-of or FIPS reference.
    assert "AES" in name


def test_strips_trailing_atx_hash_in_h1() -> None:
    """Issue #5: `sha256 #` not stripped."""
    extracted = {
        "README.md": "# sha256 #\n\nbody\n",
    }
    name = _ic_name_from_docs(extracted)
    assert name == "sha256"
    assert "#" not in name


def test_rejects_fpga_board_name_in_h1() -> None:
    """Issue #5: a multi-IP repo's README listed `VCU1525` among
    boards; picker confused it for an IP family name."""
    extracted = {
        "README.md": (
            "# Networking IP family\n\n"
            "Tested on VCU1525 evaluation board.\n"
        ),
    }
    name = _ic_name_from_docs(extracted)
    assert name != "VCU1525"
    # Should pick the H1 instead.
    assert "Networking" in name or "IP" in name


def test_preserves_lite_prefix() -> None:
    """Issue #5: `LiteDRAM` got stripped to `DRAM`. Must keep prefix."""
    extracted = {
        "README.md": "# LiteDRAM\n\nA fast DRAM controller.\n",
    }
    name = _ic_name_from_docs(extracted)
    assert name == "LiteDRAM"
    assert "Lite" in name


def test_preserves_lite_prefix_when_adjacency_would_strip_it() -> None:
    """Even when both `LiteDRAM` and `DRAM controller` are in source,
    H1 wins over adjacency, so the prefix-preserved name is picked."""
    extracted = {
        "README.md": (
            "# LiteSATA\n\n"
            "A SATA controller IP, formerly known as LiteSATA.\n"
        ),
    }
    name = _ic_name_from_docs(extracted)
    assert name == "LiteSATA"


def test_implementation_of_wins_over_h1() -> None:
    """v1.6.58 tie-breaker order: impl-of beats H1."""
    extracted = {
        "README.md": (
            "# Cool Crypto Library\n\n"
            "This is a Verilog implementation of AES with key expansion.\n"
        ),
    }
    name = _ic_name_from_docs(extracted)
    assert "AES" in name


def test_fips_reference_wins_over_h1() -> None:
    extracted = {
        "README.md": (
            "# Boring Title\n\n"
            "Conforms to NIST FIPS 197.\n"
        ),
    }
    name = _ic_name_from_docs(extracted)
    assert name == "AES"


def test_unknown_ic_when_only_stopwords() -> None:
    """All-stopword H1 + no other signal → UNKNOWN_IC, not junk."""
    extracted = {
        "README.md": "# the project\n\nlorem ipsum\n",
    }
    assert _ic_name_from_docs(extracted) == "UNKNOWN_IC"


def test_does_not_drop_characters_in_word() -> None:
    """Issue #5: SHA-1 H1 returned `SHA-1 cryptgraphic hash` —
    user thought picker dropped a char from `cryptographic`. The
    picker must return verbatim source spans; no fuzz-matching."""
    src = "# SHA-1 cryptographic hash\n\nbody\n"
    extracted = {"README.md": src}
    name = _ic_name_from_docs(extracted)
    # Whatever the picker chose, the substring it returned must be
    # a contiguous substring of the source — no character dropping.
    assert name in src or name in src.replace("\n", " ")


def test_chip_style_part_number_still_works_as_fallback() -> None:
    """Tier-5 fallback: pure part-number doc with no H1 / FIPS / impl
    still returns the chip name."""
    extracted = {
        "datasheet.txt": "EXAMPLE_CHIP reference. EXAMPLE_CHIP specifications.",
    }
    assert _ic_name_from_docs(extracted) == "EXAMPLE_CHIP"


def test_chip_style_rejects_fpga_board_sku() -> None:
    """Tier-5 must NOT pick a board SKU even if frequent."""
    extracted = {
        "doc.txt": "VCU1525 VCU1525 VCU1525 VCU1525.",
    }
    assert _ic_name_from_docs(extracted) == "UNKNOWN_IC"


# ---------------------------------------------------------------------------
# 8 issue-#5 named regression scenarios in one test.
# ---------------------------------------------------------------------------

def test_issue_5_eight_failing_projects_all_pass() -> None:
    """Reproduce the 8 named picker-junk cases from issue #5 and
    assert each one returns a non-junk value."""
    cases = [
        # (README content, expected non-empty / non-junk predicate)
        ("# the AES core\nVerilog implementation of AES.\n",
         lambda n: n != "the" and "AES" in n),
        ("# sha256 #\n",
         lambda n: n == "sha256"),
        ("# LiteDRAM\n",
         lambda n: n == "LiteDRAM"),
        ("# LiteSATA\n",
         lambda n: n == "LiteSATA"),
        ("# LiteSDCard\n",
         lambda n: n == "LiteSDCard"),
        ("# LiteScope\n",
         lambda n: n == "LiteScope"),
        ("# Networking IP family\nTested on VCU1525 board.\n",
         lambda n: n != "VCU1525"),
        ("# 1G/10G/25G Ethernet MAC\n",
         lambda n: n != "UNKNOWN_IC" and ("Ethernet" in n or "MAC" in n)),
    ]
    for src, predicate in cases:
        extracted = {"README.md": src}
        name = _ic_name_from_docs(extracted)
        assert predicate(name), f"src={src!r} returned name={name!r}"
