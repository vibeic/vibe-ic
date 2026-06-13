"""tests/test_phase1_issue5_l6_fsm_extraction.py — v1.6.58

Closes GitHub issue #5 BUG 2. The previous L6 generator emitted the
same hardcoded 5-state EXAMPLE_PROTOCOL-class scaffold for every IC in the 8-project
benchmark. The new three-tier extraction must:

* Tier A — harvest real state names from extracted docs when they exist
* Tier B — emit EXAMPLE_PROTOCOL 5-state template ONLY when L2.protocol_overview.
  half_duplex == true (i.e., the IC really is an EXAMPLE_PROTOCOL-class device)
* Tier C — emit `fsm_states: []` + `no_fsm_states_in_input: true` when
  no FSM evidence is present anywhere

This file asserts non-identical FSM lists across four IC classes — a
direct regression for the "all 8 projects emit the same 5 states" bug.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from programs.phase1_one_shot_runner import gen_l6_control_logic


_GEN_DIR = Path("phase1") / "generated_docs"


def _seed_project(tmp_path: Path, l2_content: dict | None = None) -> Path:
    """Create a phase1 project skeleton at tmp_path with optional L2."""
    project = tmp_path
    (project / _GEN_DIR).mkdir(parents=True, exist_ok=True)
    if l2_content is not None:
        (project / _GEN_DIR / "L2_FRS.json").write_text(
            json.dumps(l2_content)
        )
    return project


def _read_l6(project: Path) -> dict:
    return json.loads(
        (project / _GEN_DIR / "L6_CONTROL_LOGIC.json").read_text()
    )


# ---------------------------------------------------------------------------
# Tier A — concrete state-name evidence in the docs.
# ---------------------------------------------------------------------------

def test_tier_a_harvests_state_tokens_from_docs(tmp_path: Path) -> None:
    """A spec that says "S_FETCH" / "STATE_DECODE" / etc. must produce
    those state names verbatim, not the EXAMPLE_PROTOCOL template."""
    project = _seed_project(tmp_path)
    extracted = {
        "control_logic.txt": (
            "FSM transitions:\n"
            "S_FETCH -> S_DECODE -> S_EXEC -> S_WB\n"
            "STATE_FLUSH on exception\n"
        ),
    }
    gen_l6_control_logic(project, extracted)
    l6 = _read_l6(project)
    state_names = {s["name"] for s in l6["fsm_states"]}
    assert "S_FETCH" in state_names
    assert "S_DECODE" in state_names
    assert "S_EXEC" in state_names
    assert "STATE_FLUSH" in state_names
    # NOT the EXAMPLE_PROTOCOL template:
    assert "S_RX_BIT" not in state_names
    assert "S_DISPATCH" not in state_names
    assert l6["no_fsm_states_in_input"] is False


def test_tier_a_harvests_verilog_parameter_states(tmp_path: Path) -> None:
    """Verilog `parameter STATE_X = 3'b001;` rows are state evidence."""
    project = _seed_project(tmp_path)
    extracted = {
        "core_fsm_spec.txt": (
            "parameter STATE_IDLE = 3'b000;\n"
            "parameter STATE_RUN  = 3'b001;\n"
            "parameter STATE_HALT = 3'b010;\n"
        ),
    }
    gen_l6_control_logic(project, extracted)
    l6 = _read_l6(project)
    state_names = {s["name"] for s in l6["fsm_states"]}
    assert "STATE_IDLE" in state_names
    assert "STATE_RUN" in state_names
    assert "STATE_HALT" in state_names
    assert l6["no_fsm_states_in_input"] is False


# ---------------------------------------------------------------------------
# Tier B was REMOVED in v1.6.59 per issue #5 follow-up. Even EXAMPLE_PROTOCOL-class
# chips must extract their own real FSM states from their own datasheet
# / FRS — no per-class boilerplate.
# ---------------------------------------------------------------------------

def test_no_aid_template_even_when_l2_half_duplex_true(
        tmp_path: Path) -> None:
    """v1.6.59 closes the issue-#5 follow-up complaint that the v1.6.58
    fix only gated the hardcode behind half_duplex=true rather than
    removing it. An EXAMPLE_PROTOCOL-class chip with no explicit state tokens in
    its docs must NOT get the 5-state template — it must emit empty
    + flag, signalling that the real FSM is missing from input."""
    project = _seed_project(tmp_path, l2_content={
        "schema_version": 2,
        "doc_class": "frs",
        "protocol_overview": {"half_duplex": True},
    })
    extracted = {
        # No S_*/STATE_* tokens, no Verilog parameter rows.
        "datasheet.txt": "Single-wire half-duplex protocol.\n",
    }
    gen_l6_control_logic(project, extracted)
    l6 = _read_l6(project)
    assert l6["fsm_states"] == []
    assert l6["no_fsm_states_in_input"] is True
    assert l6["no_fsm_in_input"] is True  # alias added in v1.6.59


# ---------------------------------------------------------------------------
# Tier C — no FSM evidence anywhere → empty list + flag.
# ---------------------------------------------------------------------------

def test_tier_c_no_fsm_evidence_emits_empty_with_flag(tmp_path: Path) -> None:
    """Pure-combinational hash core, with NO L2 half_duplex and NO
    state tokens, must emit `fsm_states: []` + the no-evidence flag.
    Asserting the flag prevents downstream completeness gates from
    counting EXAMPLE_PROTOCOL template hits as L6 substance."""
    project = _seed_project(tmp_path, l2_content={
        "schema_version": 2,
        "doc_class": "frs",
        "protocol_overview": {"half_duplex": False},
    })
    extracted = {
        "sha256.txt": (
            "SHA-256 cryptographic hash.\n"
            "Combinational round expansion.\n"
        ),
    }
    gen_l6_control_logic(project, extracted)
    l6 = _read_l6(project)
    assert l6["fsm_states"] == []
    assert l6["no_fsm_states_in_input"] is True


def test_tier_c_no_l2_at_all_still_emits_empty(tmp_path: Path) -> None:
    """If the project has no L2_FRS.json yet (extreme edge case), L6
    must NOT crash — it must fall through to Tier C."""
    project = _seed_project(tmp_path, l2_content=None)
    extracted = {
        "doc.txt": "AES block cipher implementation. No FSM mentioned.\n",
    }
    gen_l6_control_logic(project, extracted)
    l6 = _read_l6(project)
    assert l6["fsm_states"] == []
    assert l6["no_fsm_states_in_input"] is True


# ---------------------------------------------------------------------------
# Cross-IC-class regression — issue #5's "same 5 states for everyone".
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "ic_class,extracted,l2_half_duplex,expected_set_kind",
    [
        # 1) EXAMPLE_PROTOCOL-class half-duplex with real S_* tokens in the doc:
        #    Tier A picks the real states, Tier B is gone.
        ("aid_half_duplex_real_states",
         {"protocol_spec.txt":
              "S_IDLE -> S_RX_BIT -> S_DISPATCH -> S_TX_REPLY -> S_DROP\n"},
         True,
         "concrete_aid_states"),
        # 2) Block cipher (combinational; no FSM, no half-duplex)
        ("aes_block_cipher",
         {"aes_spec.txt": "Verilog implementation of AES (FIPS 197). "
                          "Pure combinational round logic.\n"},
         False,
         "empty"),
        # 3) Hash core (combinational rounds, no FSM)
        ("sha256_hash",
         {"sha256_spec.txt": "SHA-256 message schedule. Combinational.\n"},
         False,
         "empty"),
        # 4) Memory controller with explicit FSM (Tier A wins)
        ("litedram_mc",
         {"litedram_fsm.txt":
              "S_PRECHARGE -> S_ACTIVATE -> S_RW -> S_REFRESH\n"},
         False,
         "concrete_states"),
    ],
)
def test_l6_does_not_emit_identical_fsm_for_every_ic_class(
        tmp_path_factory: pytest.TempPathFactory,
        ic_class: str,
        extracted: dict[str, str],
        l2_half_duplex: bool,
        expected_set_kind: str,
) -> None:
    """Issue #5 BUG 2 regression — assert that 4 distinct IC classes
    do NOT all produce the same 5-state EXAMPLE_PROTOCOL list. v1.6.59 removed the
    EXAMPLE_PROTOCOL template entirely; the EXAMPLE_PROTOCOL-class chip now needs real S_*
    tokens in its doc to get them in fsm_states."""
    project = _seed_project(
        tmp_path_factory.mktemp(ic_class),
        l2_content={
            "schema_version": 2,
            "doc_class": "frs",
            "protocol_overview": {"half_duplex": l2_half_duplex},
        },
    )
    gen_l6_control_logic(project, extracted)
    l6 = _read_l6(project)
    state_names = [s["name"] for s in l6["fsm_states"]]
    if expected_set_kind == "concrete_aid_states":
        # EXAMPLE_PROTOCOL class with REAL S_* tokens harvested from doc.
        assert "S_IDLE" in state_names
        assert "S_RX_BIT" in state_names
        assert l6["no_fsm_states_in_input"] is False
    elif expected_set_kind == "empty":
        assert state_names == []
        assert l6["no_fsm_states_in_input"] is True
        assert l6["no_fsm_in_input"] is True
    elif expected_set_kind == "concrete_states":
        assert "S_PRECHARGE" in state_names
        assert "S_ACTIVATE" in state_names
        assert l6["no_fsm_states_in_input"] is False


def test_aid_class_with_no_state_evidence_is_empty_not_template(
        tmp_path: Path) -> None:
    """v1.6.59 — even an EXAMPLE_PROTOCOL-class chip (L2.half_duplex=true) emits
    `fsm_states: []` when the docs have no real state tokens. No
    fallback template.

    v1.6.78 (issue #11) — also asserts the consistency rule: when the
    only doc supplied has a non-FSM-topic filename, the flag should
    still be True. Use ``misc_notes.txt`` (neutral, no fsm /
    state[_-]machine / control[_-]logic keyword) so the topic regex
    in `_TOPIC_FILENAME_PATTERNS` does not flip the flag to False.
    """
    project = _seed_project(tmp_path, l2_content={
        "protocol_overview": {"half_duplex": True},
    })
    extracted = {
        "misc_notes.txt": "EXAMPLE_PROTOCOL protocol; no state names listed.\n",
    }
    gen_l6_control_logic(project, extracted)
    l6 = _read_l6(project)
    assert l6["fsm_states"] == []
    assert l6["no_fsm_states_in_input"] is True
    assert l6["no_fsm_in_input"] is True
    aid_template = ["S_IDLE", "S_RX_BIT", "S_DISPATCH",
                    "S_TX_REPLY", "S_DROP"]
    assert [s["name"] for s in l6["fsm_states"]] != aid_template


def test_l6_flag_evidence_consistency_issue11(tmp_path: Path) -> None:
    """v1.6.78 — closes #11 for L6.fsm_states. When the input doc has
    a control-logic-topic filename (e.g. ``control_logic.txt``,
    ``state_machine.md``) but the state-name regex extracted nothing,
    the flag must be False because the input DOES carry FSM content
    structurally — we just failed to parse it."""
    project = _seed_project(tmp_path, l2_content={
        "protocol_overview": {"half_duplex": True},
    })
    extracted = {
        # Filename matches the L6 topic regex.
        "control_logic.txt": "FSM described in prose only, no token.\n",
    }
    gen_l6_control_logic(project, extracted)
    l6 = _read_l6(project)
    assert l6["fsm_states"] == []
    # Even with empty fsm_states, the flag stays False because the
    # evidence map carries a control-logic-topic filename.
    assert l6["no_fsm_states_in_input"] is False
    assert l6["no_fsm_in_input"] is False
