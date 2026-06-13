"""tests/test_phase1_issue5_v1659_followup.py — v1.6.60

Direct regression tests for the v1.6.59 follow-up failure modes the
user posted on GitHub issue #5:

1. SerDes link → still UNKNOWN_IC despite README having a clear H1.
   Root cause: H1 like "# Open Source SerDes" failed
   `_is_valid_ic_name_phrase` because "Open" is in the stopword set.
   v1.6.60 fix: `_trim_h1_to_ip_phrase` skips leading stopwords.
2. Logic-analyzer → still "Analyzer" (sub-word from impl-of).
   Root cause: single-token captures via Tier 1 only checked the
   loose `_looks_like_ip_token` validator. v1.6.60 fix: Tier 1
   single-token captures must also pass `_is_strict_single_token_ic_name`
   (all-caps acronym OR digit-bearing OR known IP-family prefix).
3. EXAMPLE_CHIP rich-input → "SHA-2" regression. Root cause: the EXAMPLE_CHIP
   datasheet mentions FIPS 180 once (cryptographic context) and Tier
   2 fired before Tier 5 chip-style. v1.6.60 fix: new Tier 1.5 —
   when a chip-style part-number appears with frequency ≥3 across
   docs, it wins before FIPS/RFC references.
4. L6 false-negative on rich-input EXAMPLE_PROTOCOL-class → docs DO describe FSM
   states in prose ("when in IDLE state"), state tables, and arrow
   transitions. v1.6.60 fix: Tier-A harvest extended with three new
   regex patterns covering prose adjacency, state-table rows, and
   arrow transitions.
"""
from __future__ import annotations

import json
from pathlib import Path

from programs.phase1_one_shot_runner import (
    _ic_name_from_docs,
    _is_strict_single_token_ic_name,
    _trim_h1_to_ip_phrase,
    gen_l6_control_logic,
)
import pytest


# ---------------------------------------------------------------------------
# 1. SerDes — H1 with leading stopwords no longer returns UNKNOWN_IC.
# ---------------------------------------------------------------------------

def test_serdes_h1_returns_serdes_not_unknown() -> None:
    """v1.6.59 returned UNKNOWN_IC because `_trim_h1_to_ip_phrase`
    refused to drop the leading "Open Source" boilerplate stopwords.
    v1.6.60 skips leading stopwords."""
    extracted = {
        "README.md": "# Open Source SerDes\n\nbody\n",
    }
    name = _ic_name_from_docs(extracted)
    assert name != "UNKNOWN_IC"
    assert "SerDes" in name


def test_h1_skips_leading_stopwords() -> None:
    assert _trim_h1_to_ip_phrase("Open Source SerDes") == "SerDes"
    assert _trim_h1_to_ip_phrase("The AES core") == "AES core"
    assert _trim_h1_to_ip_phrase("Free Verilog Implementation of MyIP") \
        in {"MyIP", ""}  # `Implementation` rejected, `MyIP` accepted


# ---------------------------------------------------------------------------
# 2. Logic Analyzer — Tier 1 single-token strict reject.
# ---------------------------------------------------------------------------

def test_impl_of_rejects_mixed_case_single_token() -> None:
    """v1.6.59: "implementation of Analyzer" returned "Analyzer"
    (mixed-case English noun). v1.6.60 strict single-token rule
    rejects it. Picker then falls through to H1."""
    extracted = {
        "README.md": (
            "# Logic Analyzer\n\n"
            "Verilog implementation of Analyzer for SignalTap.\n"
        ),
    }
    name = _ic_name_from_docs(extracted)
    assert name != "Analyzer"
    # Should now pick the full H1.
    assert "Logic" in name and "Analyzer" in name


def test_strict_single_token_validator() -> None:
    """All-caps OR digit OR known prefix accepts; mixed-case English
    rejects."""
    # Accept (real IP names):
    assert _is_strict_single_token_ic_name("AES")
    assert _is_strict_single_token_ic_name("JTAG")
    assert _is_strict_single_token_ic_name("USB")
    assert _is_strict_single_token_ic_name("EXAMPLE_CHIP")
    assert _is_strict_single_token_ic_name("ChaCha20")
    assert _is_strict_single_token_ic_name("EXAMPLE_TESTER")
    assert _is_strict_single_token_ic_name("LiteDRAM")
    assert _is_strict_single_token_ic_name("OpenRISC")
    # Reject (mixed-case English):
    assert not _is_strict_single_token_ic_name("Analyzer")
    assert not _is_strict_single_token_ic_name("Module")
    assert not _is_strict_single_token_ic_name("Controller")
    assert not _is_strict_single_token_ic_name("Debug")


def test_impl_of_still_works_for_real_ip_names() -> None:
    """The strict rule must NOT regress the v1.6.59 wins."""
    cases = [
        # (text, expected substring)
        ("Verilog implementation of AES.\n", "AES"),
        ("This is an implementation of ChaCha20-Poly1305.\n", "ChaCha20"),
        ("Implementation of LiteDRAM controller.\n", "LiteDRAM"),
    ]
    for src, expected in cases:
        extracted = {"doc.txt": src}
        name = _ic_name_from_docs(extracted)
        assert expected in name, f"{src!r} → {name!r}"


# ---------------------------------------------------------------------------
# 3. EXAMPLE_CHIP rich-input — chip-style with high frequency beats FIPS.
# ---------------------------------------------------------------------------

def test_example_chip_with_fips_side_mention_returns_chip_number() -> None:
    """v1.6.59 returned "SHA-2" because Tier 2 fired on a single
    "FIPS 180" mention buried in the EXAMPLE_CHIP datasheet. v1.6.60
    introduces Tier 1.5: chip-style frequency ≥3 wins before FIPS."""
    extracted = {
        "EXAMPLE_CHIP_Datasheet.txt": (
            "EXAMPLE_CHIP EXAMPLE_PROTOCOL-class authentication IC.\n"
            "EXAMPLE_CHIP implements a CMAC over the FIPS 180 secure hash.\n"
            "EXAMPLE_CHIP specifications follow.\n"
            "Reset: EXAMPLE_CHIP enters S_IDLE on power-up.\n"
            "Power: see EXAMPLE_CHIP datasheet section 3.\n"
        ),
    }
    name = _ic_name_from_docs(extracted)
    assert name == "EXAMPLE_CHIP"


def test_chip_style_low_frequency_does_not_steal_aes_pick() -> None:
    """When a doc mentions a part number once and has clear FIPS
    signal, FIPS still wins (chip-style frequency below threshold)."""
    extracted = {
        "aes_spec.txt": (
            "Verilog AES core. Conforms to NIST FIPS 197. "
            "Tested on board EXAMPLE_TESTER once.\n"
        ),
    }
    name = _ic_name_from_docs(extracted)
    # EXAMPLE_TESTER mentioned only once — below freq-3 threshold; FIPS wins.
    assert name == "AES"


def test_example_tester_frequent_mention_wins_over_fips_side_mention() -> None:
    extracted = {
        "EXAMPLE_TESTER_Datasheet.txt": (
            "EXAMPLE_TESTER single-wire authentication IC. "
            "EXAMPLE_TESTER protocol overview. "
            "EXAMPLE_TESTER reset: see FIPS 180 section 4. "
            "EXAMPLE_TESTER calibration. "
            "EXAMPLE_TESTER OTP layout.\n"
        ),
    }
    assert _ic_name_from_docs(extracted) == "EXAMPLE_TESTER"


# ---------------------------------------------------------------------------
# 4. L6 prose state extraction — rich-input EXAMPLE_PROTOCOL-class.
# ---------------------------------------------------------------------------

def _seed_with_l2(tmp_path: Path, half_duplex: bool = True) -> Path:
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


def test_prose_state_extraction_in_X_state(tmp_path: Path) -> None:
    """v1.6.60 — capture state names from "in <STATE> state" prose."""
    project = _seed_with_l2(tmp_path)
    extracted = {
        "control_logic.txt": (
            "When the device is in IDLE state, it waits for a falling "
            "edge. After the edge, it enters the RX_BIT state and "
            "samples successive bit periods. During the DISPATCH "
            "state, the controller routes the frame.\n"
        ),
    }
    gen_l6_control_logic(project, extracted)
    l6 = _read_l6(project)
    state_names = {s["name"] for s in l6["fsm_states"]}
    assert "IDLE" in state_names
    assert "RX_BIT" in state_names
    assert "DISPATCH" in state_names
    assert l6["no_fsm_states_in_input"] is False


def test_prose_state_extraction_state_table_row(tmp_path: Path) -> None:
    project = _seed_with_l2(tmp_path)
    extracted = {
        "fsm_table.txt": (
            "State table:\n"
            "S_FETCH state:   on rd → S_READ\n"
            "S_READ state:    on done → S_IDLE\n"
        ),
    }
    gen_l6_control_logic(project, extracted)
    l6 = _read_l6(project)
    state_names = {s["name"] for s in l6["fsm_states"]}
    assert "S_FETCH" in state_names
    assert "S_READ" in state_names


def test_arrow_transition_state_extraction(tmp_path: Path) -> None:
    """`A -> B` rows (or `=>` / unicode `→`) yield A and B both as
    state names."""
    project = _seed_with_l2(tmp_path)
    extracted = {
        "fsm_protocol.txt": (
            "Transitions:\n"
            "S_IDLE -> S_RX_BIT\n"
            "S_RX_BIT => S_DISPATCH\n"
            "S_DISPATCH → S_TX_REPLY\n"
        ),
    }
    gen_l6_control_logic(project, extracted)
    l6 = _read_l6(project)
    state_names = {s["name"] for s in l6["fsm_states"]}
    assert state_names >= {"S_IDLE", "S_RX_BIT",
                            "S_DISPATCH", "S_TX_REPLY"}


def test_prose_state_rejects_english_conjunctions(tmp_path: Path) -> None:
    """Words like AND / OR / NOT must NOT be captured as state names
    even if they appear before "state" in prose."""
    project = _seed_with_l2(tmp_path)
    extracted = {
        "doc.txt": (
            "The TRUE state and the FALSE state are mutually exclusive.\n"
            "After AND state combination, NOT state inverts.\n"
        ),
    }
    gen_l6_control_logic(project, extracted)
    l6 = _read_l6(project)
    state_names = {s["name"] for s in l6["fsm_states"]}
    assert "AND" not in state_names
    assert "OR" not in state_names
    assert "NOT" not in state_names
    assert "TRUE" not in state_names
    assert "FALSE" not in state_names


def test_aid_class_rich_input_captures_real_states(tmp_path: Path) -> None:
    """Direct regression for the v1.6.59 false-negative on rich-input
    EXAMPLE_PROTOCOL-class chip — its prose / state-table / arrow rows now feed
    Tier A so `fsm_states` is no longer mistakenly empty."""
    project = _seed_with_l2(tmp_path, half_duplex=True)
    extracted = {
        "EXAMPLE_CHIP_TxRx_signal_format.txt": (
            "Reset: device enters S_IDLE state on power-up.\n"
            "Frame start: BR pulse detected; transition S_IDLE -> S_RX_BIT\n"
            "Bit reception: in S_RX_BIT state, sample 3-region majority.\n"
            "On IBT_QUIET: S_RX_BIT -> S_DISPATCH\n"
            "Dispatch: in S_DISPATCH state, route to S_TX_REPLY or S_DROP.\n"
        ),
    }
    gen_l6_control_logic(project, extracted)
    l6 = _read_l6(project)
    state_names = {s["name"] for s in l6["fsm_states"]}
    assert state_names >= {"S_IDLE", "S_RX_BIT",
                            "S_DISPATCH", "S_TX_REPLY", "S_DROP"}
    assert l6["no_fsm_states_in_input"] is False
    assert l6["no_fsm_in_input"] is False
    # Critically: each state's evidence references a real source span,
    # not a per-class template marker.
    for s in l6["fsm_states"]:
        assert "EXAMPLE_PROTOCOL 5-state template" not in s.get("evidence", "")
