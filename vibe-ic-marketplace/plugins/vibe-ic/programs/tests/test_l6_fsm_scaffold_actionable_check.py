#!/usr/bin/env python3
"""Smoke tests for l6_fsm_scaffold_actionable_check.py.

NEGATIVE CONTROL IS THE POINT. Every requirement is asserted in BOTH
directions: a deliberately-gutted L6 must FAIL and the well-formed
sibling must PASS.

All fixtures are SYNTHESIZED neutral data — invented state names
(``ST_A``/``ST_B``/``ST_C``) and invented rule text. No real design's
files, no vendor tokens, no PDK names.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "l6_fsm_scaffold_actionable_check.py")


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _mk(tmp_path: Path, l6: dict, name: str = "p", l3: dict | None = None):
    proj = tmp_path / name
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L6_CONTROL_LOGIC.json").write_text(json.dumps(l6),
                                              encoding="utf-8")
    (gd / "L1_DATASHEET.json").write_text(
        json.dumps({"ic_name": "synth_part", "interface": "uart"}),
        encoding="utf-8")
    if l3 is not None:
        (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps(l3),
                                                 encoding="utf-8")
    return proj


def _good_fsm() -> dict:
    """An FSM skeleton phase2_scaffold_gen can actually scaffold."""
    return {
        "fsm_states": [
            {"name": "ST_A", "transitions": [{"to": "ST_B",
                                              "condition": "start"}]},
            {"name": "ST_B", "transitions": [{"to": "ST_C",
                                              "condition": "done"}]},
            {"name": "ST_C", "transitions": [{"to": "ST_A",
                                              "condition": "reset"}]},
        ],
        "no_fsm_in_input": False,
        "no_fsm_states_in_input": False,
    }


# ---------------------------------------------------------------------------
# PART A — FSM skeleton. Positive control first.
# ---------------------------------------------------------------------------

def test_positive_control_wellformed_fsm_passes(tmp_path):
    r = _run(_mk(tmp_path, _good_fsm()))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


def test_negative_control_single_state_fails(tmp_path):
    """One state is not a state machine — emit_fsm_v() gives it a 1-bit
    register that can never change value."""
    l6 = _good_fsm()
    l6["fsm_states"] = [{"name": "ST_A", "transitions": []}]
    r = _run(_mk(tmp_path, l6))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "1 FSM state" in r.stdout


def test_negative_control_states_under_wrong_key_fails(tmp_path):
    """THE motivating shape: the state list IS in L6 — under ``states``,
    which derive_fsm_states() does not read. Token present, layer
    populated, consumer gets nothing."""
    good = _good_fsm()
    l6 = {
        "states": good["fsm_states"],       # wrong key
        "no_fsm_in_input": False,
        "no_fsm_states_in_input": False,
    }
    r = _run(_mk(tmp_path, l6))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "returns 0 states" in r.stdout
    assert "fsm_states" in r.stdout          # the fix is named


def test_negative_control_no_transitions_fails(tmp_path):
    """States but no edges: emit_fsm_v()'s body is a TODO comment, so
    phase 2 receives a state enum with no transition information."""
    l6 = _good_fsm()
    for st in l6["fsm_states"]:
        st["transitions"] = []
    r = _run(_mk(tmp_path, l6))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "0 transitions" in r.stdout


def test_negative_control_dangling_transition_target_fails(tmp_path):
    l6 = _good_fsm()
    l6["fsm_states"][0]["transitions"] = [{"to": "ST_NEVER_DECLARED"}]
    r = _run(_mk(tmp_path, l6))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "not in the derived state set" in r.stdout


def test_honest_no_fsm_in_input_skips(tmp_path):
    """A design whose input documents no FSM must not be penalised for
    saying so."""
    r = _run(_mk(tmp_path, {
        "fsm_states": [],
        "no_fsm_in_input": True,
        "no_fsm_states_in_input": True,
    }))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "[SKIP]" in r.stdout


def test_missing_l6_skips(tmp_path):
    proj = tmp_path / "empty"
    proj.mkdir(parents=True, exist_ok=True)
    r = _run(proj)
    assert r.returncode == 2, r.stdout + r.stderr


# ---------------------------------------------------------------------------
# PART B — reject_rules actionability.
# ---------------------------------------------------------------------------

def _good_rules() -> list:
    return [
        {"rule_id": "R_CRC", "action": "DROP",
         "condition": "crc_mismatch on received frame => drop frame"},
        {"rule_id": "R_LEN", "action": "DROP",
         "condition": "len_out_of_range => reject and stay idle"},
    ]


def test_positive_control_wellformed_reject_rules_pass(tmp_path):
    l6 = _good_fsm()
    l6["reject_rules"] = _good_rules()
    r = _run(_mk(tmp_path, l6))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


def test_negative_control_unmatchable_condition_fails(tmp_path):
    """A condition the consumer's own extractor derives no keyword from
    makes l11_sequence_covers_l6_reject_rules_check take its
    'accept any silent sequence' branch — the coverage gate goes
    vacuous for that rule."""
    l6 = _good_fsm()
    l6["reject_rules"] = [
        {"rule_id": "R_X", "action": "DROP",
         "condition": "the peripheral shall behave per the table above"},
    ]
    r = _run(_mk(tmp_path, l6))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "NO keyword" in r.stdout


def test_negative_control_accidental_substring_keyword_fails(tmp_path):
    """The subtle one. The consumer matches by bare substring, so a raw
    document scrape mentioning a 39-bit word yields the keyword '9 bit'
    — matched INSIDE '39 bit'. The rule looks covered by a concept it
    never meant. Requiring a token-boundary hit catches it."""
    l6 = _good_fsm()
    l6["reject_rules"] = [
        {"rule_id": "R_SCRAPE", "action": "DROP",
         "condition": "| field | payload words are 39 bit wide | note |"},
    ]
    r = _run(_mk(tmp_path, l6))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "by accident" in r.stdout


def test_negative_control_rule_without_identity_fails(tmp_path):
    l6 = _good_fsm()
    l6["reject_rules"] = [{"condition": "crc_mismatch => drop"}]
    r = _run(_mk(tmp_path, l6))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "no name/rule_id" in r.stdout


def test_negative_control_rule_with_empty_condition_fails(tmp_path):
    l6 = _good_fsm()
    l6["reject_rules"] = [{"rule_id": "R_E", "condition": ""}]
    r = _run(_mk(tmp_path, l6))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "empty condition" in r.stdout


def test_waiver_suppresses_fail(tmp_path):
    l6 = _good_fsm()
    l6["fsm_states"] = [{"name": "ST_A", "transitions": []}]
    proj = _mk(tmp_path, l6)
    (proj / "waivers.json").write_text(json.dumps({
        "l6_fsm_scaffold_degraded_intentional":
            "This synthesized fixture intentionally declares a single "
            "state so the documented waiver path is exercised in test.",
    }), encoding="utf-8")
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "waived" in r.stdout


# ---------------------------------------------------------------------------
# Both directions on one edit — a real control.
# ---------------------------------------------------------------------------

def test_both_directions_on_one_edit(tmp_path):
    """Move the state list from the key the emitter reads to one it does
    not. Nothing else changes — not one character of content."""
    good_l6 = _good_fsm()
    bad_l6 = {"states": good_l6["fsm_states"],
              "no_fsm_in_input": False,
              "no_fsm_states_in_input": False}

    r_good = _run(_mk(tmp_path, good_l6, name="good"))
    r_bad = _run(_mk(tmp_path, bad_l6, name="bad"))
    assert r_good.returncode == 0, r_good.stdout
    assert r_bad.returncode == 1, r_bad.stdout
    assert r_good.returncode != r_bad.returncode
