"""tests/test_phase1_ic_name_extraction.py — v1.6.55

Closes the most-cited example from GitHub issue #4: README says
"Verilog implementation of AES (NIST FIPS 197)" but L1.ic_name
remained "UNKNOWN_IC" because the prior heuristic only matched
chip-style part numbers like EXAMPLE_CHIP / EXAMPLE_TESTER."""
from __future__ import annotations

from programs.phase1_one_shot_runner import _ic_name_from_docs


# ---------------------------------------------------------------------------
# Existing chip-style part number — must still work.
# ---------------------------------------------------------------------------

def test_chip_style_part_number_still_extracted() -> None:
    extracted = {
        "datasheet.txt": "The EXAMPLE_CHIP chip is a half-duplex auth IC. "
                          "EXAMPLE_CHIP supports BR framing.",
    }
    assert _ic_name_from_docs(extracted) == "EXAMPLE_CHIP"


def test_most_frequent_part_number_wins() -> None:
    """The chip-style regex matches `[A-Z]{2,4}\\d{4}[A-Z]?` exactly
    (2-4 letters + 4 digits + optional letter). Two valid chips →
    most-frequent wins."""
    extracted = {
        "doc1.txt": "BC1234 reference. BC1234 specifications. "
                    "BC1234 implementation note.",
        "doc2.txt": "Mention BC1234 once and EXAMPLE_CHIP once.",
    }
    assert _ic_name_from_docs(extracted) == "BC1234"


# ---------------------------------------------------------------------------
# Markdown H1 fallback (issue #4).
# ---------------------------------------------------------------------------

def test_h1_extracted_from_readme() -> None:
    """v1.6.58 — closes issue #5 BUG 1. The new tie-breaker order
    puts `implementation of <X>` ABOVE H1 (so the README of a block
    cipher project doesn't pick "the AES core" as its IC name). Here
    the body line `Verilog implementation of AES.` outranks the H1
    `# AES core`, and the picker returns "AES"."""
    extracted = {
        "README.md": "# AES core\n\nVerilog implementation of AES.\n",
    }
    name = _ic_name_from_docs(extracted)
    assert name == "AES"


def test_h1_wins_when_no_impl_or_fips_signal() -> None:
    """H1 still wins when no higher-priority signal is present."""
    extracted = {
        "README.md": "# AES core\n\nA hardware AES block cipher.\n",
    }
    name = _ic_name_from_docs(extracted)
    assert name == "AES core"


def test_h1_strips_trailing_parens() -> None:
    extracted = {
        "README.md": "# DDR Controller (open-source)\n\nbody\n",
    }
    name = _ic_name_from_docs(extracted)
    assert name == "DDR Controller"


def test_h1_drops_boilerplate_words() -> None:
    extracted = {
        "README.md": "# This project documentation\n\nbody\n",
    }
    # Should fall through to the next heuristic (no other source) → UNKNOWN_IC.
    name = _ic_name_from_docs(extracted)
    assert name == "UNKNOWN_IC"


# ---------------------------------------------------------------------------
# "implementation of <X>" pattern.
# ---------------------------------------------------------------------------

def test_implementation_of_pattern() -> None:
    extracted = {
        "intro.md": "Open-source Verilog implementation of ChaCha20.",
    }
    name = _ic_name_from_docs(extracted)
    # Either H1 path or implementation-of path. Issue #4 example.
    assert name == "ChaCha20"


def test_verb_implementation_of_pattern() -> None:
    extracted = {
        "spec.txt": "Hardware implementation of SHA-256 hash function.",
    }
    name = _ic_name_from_docs(extracted)
    assert "SHA" in name


# ---------------------------------------------------------------------------
# FIPS / RFC standard reference.
# ---------------------------------------------------------------------------

def test_fips_197_yields_aes() -> None:
    extracted = {
        "spec.txt": "Compliant with NIST FIPS 197.",
    }
    assert _ic_name_from_docs(extracted) == "AES"


def test_rfc_7539_yields_chacha20() -> None:
    extracted = {
        "spec.txt": "Implements RFC 7539 stream cipher.",
    }
    assert _ic_name_from_docs(extracted) == "ChaCha20"


def test_fips_180_yields_sha2() -> None:
    extracted = {
        "spec.txt": "Conforms to FIPS 180-4.",
    }
    assert _ic_name_from_docs(extracted) == "SHA-2"


def test_ieee_1149_yields_jtag() -> None:
    extracted = {
        "spec.txt": "IEEE 1149.1 boundary scan.",
    }
    assert _ic_name_from_docs(extracted) == "JTAG"


# ---------------------------------------------------------------------------
# Adjacency to "core" / "controller" / "IP".
# ---------------------------------------------------------------------------

def test_x_core_pattern() -> None:
    extracted = {
        "doc.txt": "Project: a fast SHA1 core for hardware acceleration.",
    }
    name = _ic_name_from_docs(extracted)
    assert name == "SHA1"


def test_x_controller_pattern() -> None:
    extracted = {
        "spec.txt": "DDR4 controller with single-cycle write path.",
    }
    name = _ic_name_from_docs(extracted)
    assert name == "DDR4"


def test_lowercase_common_words_rejected_in_adjacency() -> None:
    extracted = {
        "doc.txt": "an open core supporting any controller protocol.",
    }
    # `an` / `any` / `open` should be rejected as candidates.
    name = _ic_name_from_docs(extracted)
    assert name == "UNKNOWN_IC"


# ---------------------------------------------------------------------------
# Empty / pathological inputs.
# ---------------------------------------------------------------------------

def test_empty_extracted_dict() -> None:
    assert _ic_name_from_docs({}) == "UNKNOWN_IC"


def test_no_match_anywhere_returns_unknown() -> None:
    extracted = {
        "weather.txt": "lorem ipsum dolor sit amet, consectetur "
                        "adipiscing elit. Sed do eiusmod tempor.",
    }
    assert _ic_name_from_docs(extracted) == "UNKNOWN_IC"
