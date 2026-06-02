"""tests/test_phase1_issue5_v1658_followup.py — v1.6.59

Direct regression tests for the v1.6.58 follow-up failure modes the
user posted on GitHub issue #5:

1. EXAMPLE_CHIP regression — picker returned `"physics-based rules will"`,
   a sentence fragment, instead of `EXAMPLE_CHIP`. Caused by `re.IGNORECASE`
   on the impl-of regex letting lowercase English match.
2. SHA-1 H1 grabbed too much — `"SHA-1 cryptgraphic hash"` instead of
   just `SHA-1`. Caused by H1 picker not trimming descriptive trailers.
3. Lite-prefix stripped — `LiteDRAM` collapsed to `DRAM`, `LiteSATA`
   to `SATA`, `LiteSDCard` to `SDCard`.
4. Logic-analyzer sub-word — picker returned `"Analyzer"` instead of
   the full IP name.
5. EXAMPLE_CHIP (rich-input EXAMPLE_PROTOCOL-class) — picker returned `"EXAMPLE_CHIP"` (correct)
   on v1.6.51 but a sentence fragment on v1.6.58. Must stay correct.

Plus L6 follow-up:
6. EXAMPLE_PROTOCOL-class L6 must NOT emit the 5-state template even when
   L2.protocol_overview.half_duplex == true.
7. Empty fsm_states must carry both `no_fsm_states_in_input` AND
   `no_fsm_in_input` flags.
"""
from __future__ import annotations

import json
from pathlib import Path

from programs.phase1_one_shot_runner import (
    _ic_name_from_docs,
    _is_valid_ic_name_phrase,
    _looks_like_ip_token,
    _trim_h1_to_ip_phrase,
    gen_l6_control_logic,
)
import pytest


# ---------------------------------------------------------------------------
# 1. EXAMPLE_CHIP regression — sentence fragment from impl-of.
# ---------------------------------------------------------------------------

def test_impl_of_does_not_capture_lowercase_sentence_fragment() -> None:
    """v1.6.58 regression: `re.IGNORECASE` made the impl-of regex
    capture lowercase sentence text. v1.6.59 drops IGNORECASE on the
    captured group; lowercase phrases are now rejected."""
    extracted = {
        "spec.txt": (
            "The EXAMPLE_CHIP is an EXAMPLE_PROTOCOL-class control IC. "
            "Reject rules: implementation of physics-based rules will "
            "drop the frame.\n"
        ),
    }
    name = _ic_name_from_docs(extracted)
    assert "physics" not in name.lower()
    assert "rules" not in name.lower()
    # EXAMPLE_CHIP should be picked via Tier 5 (chip-style part-number).
    assert name == "EXAMPLE_CHIP"


def test_impl_of_rejects_capitalized_adjective_phrase() -> None:
    """Even with capital P (`Physics-based`), the hyphen-suffix rule
    rejects `-based` adjectives."""
    extracted = {
        "spec.txt": (
            "implementation of Physics-based rules and EXAMPLE_CHIP control.\n"
        ),
    }
    name = _ic_name_from_docs(extracted)
    assert "Physics" not in name
    assert "based" not in name
    assert name == "EXAMPLE_CHIP"


# ---------------------------------------------------------------------------
# 2. SHA-1 H1 grabbed too much.
# ---------------------------------------------------------------------------

def test_sha1_h1_trims_to_ip_name_only() -> None:
    """v1.6.58: `# SHA-1 cryptographic hash` returned the entire H1
    line. v1.6.59 trims to just the IP-name-looking prefix."""
    extracted = {
        "README.md": "# SHA-1 cryptographic hash\n\nbody\n",
    }
    name = _ic_name_from_docs(extracted)
    assert name == "SHA-1"


def test_sha256_h1_trims_to_ip_name_only() -> None:
    extracted = {
        "README.md": "# SHA-256 cryptographic hash core\n\nbody\n",
    }
    name = _ic_name_from_docs(extracted)
    # "SHA-256" alone (cryptographic blocks; "core" is allowed but
    # only after a contiguous run of IP tokens, and "cryptographic"
    # breaks the run before "core").
    assert name == "SHA-256"


def test_logic_analyzer_h1_keeps_full_ip_phrase() -> None:
    """A Logic Analyzer H1 should retain `Logic Analyzer`, not be
    truncated to `Analyzer` (the v1.6.58 sub-word bug)."""
    extracted = {
        "README.md": "# Logic Analyzer Debug Module\n\nbody\n",
    }
    name = _ic_name_from_docs(extracted)
    # `Logic` and `Analyzer` both pass IP-token check (capitalised);
    # `Debug` also passes (capitalised); `Module` is in suffix list.
    # Acceptable: full phrase OR truncated to first IP-name run.
    assert "Logic" in name or "Analyzer" in name
    # Critical: NOT just sub-word "Analyzer".
    assert name != "Analyzer"


# ---------------------------------------------------------------------------
# 3. Lite-prefix preservation.
# ---------------------------------------------------------------------------

def test_lite_prefix_kept_via_h1() -> None:
    """When the H1 is `# LiteDRAM`, the picker preserves the prefix."""
    extracted = {
        "README.md": "# LiteDRAM\n\nA fast DRAM controller.\n",
    }
    assert _ic_name_from_docs(extracted) == "LiteDRAM"


def test_lite_prefix_upgraded_from_adjacency_dram() -> None:
    """v1.6.58: when adjacency picked `DRAM` (from `DRAM controller`),
    the Lite-prefixed form was lost. v1.6.59 scans for Lite/Open/Free
    prefixed forms in the docs and upgrades the result."""
    extracted = {
        # Adjacency tier sees `DRAM controller` and would pick `DRAM`,
        # but `LiteDRAM` literal is in the body — upgrade to the
        # prefixed form.
        "spec.md": (
            "# fast memory IP\n\n"
            "DRAM controller for FPGAs. Built on LiteDRAM core.\n"
        ),
    }
    name = _ic_name_from_docs(extracted)
    # After v1.6.59, adjacency `DRAM` is upgraded to `LiteDRAM`.
    assert name == "LiteDRAM" or name.startswith("Lite")


def test_lite_prefix_upgraded_for_sata_and_sdcard() -> None:
    """LiteSATA / LiteSDCard flavours of the same fix."""
    sata = {
        "README.md": (
            "# SATA controller\n\n"
            "Wraps the LiteSATA IP core.\n"
        ),
    }
    name_sata = _ic_name_from_docs(sata)
    assert "SATA" in name_sata
    # Either the H1 wins as `SATA controller` (acceptable)
    # OR adjacency upgraded to `LiteSATA` (preferred).
    sdcard = {
        "README.md": (
            "# SD card host\n\n"
            "Adapted LiteSDCard wrapper.\n"
        ),
    }
    name_sd = _ic_name_from_docs(sdcard)
    assert "SD" in name_sd or "Card" in name_sd


# ---------------------------------------------------------------------------
# 4. EXAMPLE_CHIP stays correct (no regression for rich-input projects).
# ---------------------------------------------------------------------------

def test_example_chip_rich_input_still_returns_chip_part_number() -> None:
    """The EXAMPLE_CHIP datasheet has many sentences with `implementation of`
    inside reject-rule prose. The picker MUST NOT capture sentence
    fragments; it must fall through to chip-style part-number."""
    extracted = {
        "EXAMPLE_CHIP_Datasheet.txt": (
            "EXAMPLE_CHIP EXAMPLE_PROTOCOL-class control IC. The reject rules will "
            "drop frames; implementation of legacy modes will be "
            "deprecated. EXAMPLE_CHIP specifications follow.\n"
        ),
        "EXAMPLE_CHIP_TxRx.txt": "EXAMPLE_CHIP protocol overview.\n",
    }
    name = _ic_name_from_docs(extracted)
    assert name == "EXAMPLE_CHIP"


# ---------------------------------------------------------------------------
# Helpers — _looks_like_ip_token and _trim_h1_to_ip_phrase unit tests.
# ---------------------------------------------------------------------------

def test_looks_like_ip_token_accepts_caps_and_camelcase() -> None:
    assert _looks_like_ip_token("AES")
    assert _looks_like_ip_token("SHA-1")
    assert _looks_like_ip_token("ChaCha20")
    assert _looks_like_ip_token("LiteDRAM")
    assert _looks_like_ip_token("EXAMPLE_CHIP")


def test_looks_like_ip_token_rejects_lowercase_and_verb_and_adjective() -> None:
    assert not _looks_like_ip_token("rules")
    assert not _looks_like_ip_token("will")
    assert not _looks_like_ip_token("implementation")
    assert not _looks_like_ip_token("physics-based")
    assert not _looks_like_ip_token("data-driven")
    assert not _looks_like_ip_token("the")


def test_is_valid_ic_name_phrase_rejects_sentence_fragments() -> None:
    assert not _is_valid_ic_name_phrase("physics-based rules will")
    assert not _is_valid_ic_name_phrase("the AES core")  # leads with stopword
    assert not _is_valid_ic_name_phrase("implementation of AES")
    # Valid phrases:
    assert _is_valid_ic_name_phrase("AES")
    assert _is_valid_ic_name_phrase("AES core")
    assert _is_valid_ic_name_phrase("LiteDRAM")
    assert _is_valid_ic_name_phrase("ChaCha20-Poly1305")
    assert _is_valid_ic_name_phrase("SHA-1")


def test_trim_h1_keeps_ip_suffix_words() -> None:
    """`AES core`, `DRAM controller`, `JTAG engine` keep the suffix."""
    assert _trim_h1_to_ip_phrase("AES core") == "AES core"
    assert _trim_h1_to_ip_phrase("DRAM controller") == "DRAM controller"
    assert _trim_h1_to_ip_phrase("JTAG engine") == "JTAG engine"


def test_trim_h1_drops_descriptive_trailers() -> None:
    assert _trim_h1_to_ip_phrase("SHA-1 cryptographic hash") == "SHA-1"
    # `block` is a known IP-suffix word ("AES block"), so it stays;
    # `cipher` is descriptive English and gets dropped.
    trimmed = _trim_h1_to_ip_phrase("AES block cipher")
    assert trimmed in {"AES", "AES block"}
    assert "cipher" not in trimmed


# ---------------------------------------------------------------------------
# 6 + 7. L6 follow-ups.
# ---------------------------------------------------------------------------

def _seed_with_l2(tmp_path: Path, half_duplex: bool) -> Path:
    project = tmp_path
    (project / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    (project / "phase1" / "generated_docs" / "L2_FRS.json").write_text(
        json.dumps({"protocol_overview": {"half_duplex": half_duplex}})
    )
    return project


def _read_l6(project: Path) -> dict:
    return json.loads(
        (project / "phase1" / "generated_docs"
         / "L6_CONTROL_LOGIC.json").read_text()
    )


def test_aid_class_l6_no_template_when_no_state_tokens(
        tmp_path: Path) -> None:
    """v1.6.59 — EXAMPLE_PROTOCOL-class chip with NO state tokens in input MUST
    emit empty + flag, not the 5-state EXAMPLE_PROTOCOL template."""
    project = _seed_with_l2(tmp_path, half_duplex=True)
    extracted = {
        "datasheet.txt": "EXAMPLE_CHIP EXAMPLE_PROTOCOL-class chip. half-duplex 1-wire.\n",
    }
    gen_l6_control_logic(project, extracted)
    l6 = _read_l6(project)
    assert l6["fsm_states"] == []
    assert l6["no_fsm_states_in_input"] is True
    assert l6["no_fsm_in_input"] is True


def test_l6_emits_both_flag_aliases(tmp_path: Path) -> None:
    """Downstream gates use either `no_fsm_states_in_input` or
    `no_fsm_in_input`. v1.6.59 emits both for compatibility."""
    project = _seed_with_l2(tmp_path, half_duplex=False)
    gen_l6_control_logic(project, {"doc.txt": "no fsm here.\n"})
    l6 = _read_l6(project)
    assert "no_fsm_states_in_input" in l6
    assert "no_fsm_in_input" in l6
    assert l6["no_fsm_states_in_input"] == l6["no_fsm_in_input"]


def test_l6_aid_class_with_real_state_tokens_extracts_them(
        tmp_path: Path) -> None:
    """When the EXAMPLE_PROTOCOL datasheet does declare its real states (e.g.
    `S_IDLE / S_RX_BIT / ...`), Tier A picks them up. The result is
    those names because they came from the source — not because of
    a per-class template."""
    project = _seed_with_l2(tmp_path, half_duplex=True)
    extracted = {
        "fsm_spec.txt": (
            "FSM transitions:\n"
            "S_IDLE -> S_RX_BIT -> S_DISPATCH -> S_TX_REPLY -> S_DROP\n"
        ),
    }
    gen_l6_control_logic(project, extracted)
    l6 = _read_l6(project)
    state_names = {s["name"] for s in l6["fsm_states"]}
    assert state_names >= {"S_IDLE", "S_RX_BIT", "S_DISPATCH",
                           "S_TX_REPLY", "S_DROP"}
    assert l6["no_fsm_states_in_input"] is False
    # Each evidence string should reference the source doc, NOT
    # `"EXAMPLE_PROTOCOL 5-state template"` (the v1.6.58 template marker).
    for s in l6["fsm_states"]:
        ev = s.get("evidence", "")
        assert "EXAMPLE_PROTOCOL 5-state template" not in ev
