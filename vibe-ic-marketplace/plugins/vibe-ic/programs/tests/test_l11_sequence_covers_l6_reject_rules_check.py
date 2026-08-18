#!/usr/bin/env python3
"""Tests for l11_sequence_covers_l6_reject_rules_check (Wave 39 / D2)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "l11_sequence_covers_l6_reject_rules_check.py")


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _make_proj(tmp_path: Path, l6: dict, l11: dict | None = None,
               l12: dict | None = None,
               waiver: str | None = None) -> Path:
    proj = tmp_path / "proj"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase1" / "generated_docs" / "L6_CONTROL_LOGIC.json").write_text(
        json.dumps(l6))
    if l11 is not None:
        (proj / "phase1" / "generated_docs" / "L11_OTP_CONTENT.json").write_text(
            json.dumps(l11))
    if l12 is not None:
        (proj / "phase1" / "generated_docs"
         / "L12_BEHAVIORAL_SEQUENCES.json").write_text(json.dumps(l12))
    if waiver is not None:
        (proj / "waivers.json").write_text(json.dumps(
            {"l11_reject_rule_coverage_partial_intentional": waiver}))
    return proj


def test_skip_when_no_l6(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir(parents=True, exist_ok=True)
    r = _run(proj)
    assert r.returncode == 2


def test_skip_when_l6_has_no_rules(tmp_path):
    proj = _make_proj(tmp_path, {"reject_rules": []})
    r = _run(proj)
    assert r.returncode == 2


def test_fail_when_no_silent_sequence(tmp_path):
    l6 = {"reject_rules": [
        {"condition": "CRC mismatch",
         "action": "discard_frame", "evidence": "RX_EVENT.txt:5"},
        {"condition": "not awake (awake_latch=0) and opcode != 0x74",
         "action": "discard_frame", "evidence": "RX_EVENT.txt:14"},
    ]}
    l12 = {"sequences": [
        {"name": "happy_GET_ID", "expected_behavior": "8-byte reply"},
    ]}
    proj = _make_proj(tmp_path, l6, l12=l12)
    r = _run(proj)
    assert r.returncode == 1
    assert "lack" in r.stdout


def test_pass_when_silent_sequences_match(tmp_path):
    l6 = {"reject_rules": [
        {"condition": "CRC mismatch",
         "action": "discard_frame", "evidence": "x"},
        {"condition": "not awake and opcode != 0x74",
         "action": "discard_frame", "evidence": "y"},
    ]}
    l12 = {"sequences": [
        {"name": "crc_corrupt_silent",
         "trigger": "CRC mismatch", "expected_behavior": "dut_silent"},
        {"name": "pre_wake_reject",
         "trigger": "send 0x70 before awake_latch",
         "expected_behavior": "no_response"},
    ]}
    proj = _make_proj(tmp_path, l6, l12=l12)
    r = _run(proj)
    assert r.returncode == 0


def test_l11_behavioral_sequences_also_counts(tmp_path):
    l6 = {"reject_rules": [
        {"condition": "CRC mismatch", "action": "discard_frame"},
    ]}
    l11 = {"behavioral_sequences": [
        {"name": "crc_bad_silent", "expected_behavior": "discard"},
    ]}
    proj = _make_proj(tmp_path, l6, l11=l11)
    r = _run(proj)
    assert r.returncode == 0


def test_waiver_pass(tmp_path):
    l6 = {"reject_rules": [
        {"condition": "CRC mismatch", "action": "discard_frame"},
    ]}
    l12 = {"sequences": []}
    waiver_text = ("Negative coverage deferred to silicon bring-up; "
                   "documented in ENG-DECISION-W39-Q88 — over forty chars")
    proj = _make_proj(tmp_path, l6, l12=l12, waiver=waiver_text)
    r = _run(proj)
    assert r.returncode == 0


# ---------------------------------------------------------------
# Wave 43 (v0.119.75) — synonym extension tests.
# ---------------------------------------------------------------
def test_synonym_checksum_fail_covers_crc_mismatch(tmp_path):
    """L11 sequence using `checksum_fail` synonym covers a
    `crc_mismatch` rule."""
    l6 = {"reject_rules": [
        {"condition": "CRC mismatch on inbound frame",
         "name": "crc_mismatch", "action": "discard_frame"},
    ]}
    l12 = {"sequences": [
        {"name": "checksum_fail_silent",
         "trigger": "checksum_fail",
         "expected_behavior": "abort"},
    ]}
    proj = _make_proj(tmp_path, l6, l12=l12)
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr


def test_synonym_pre_wake_kanji_match(tmp_path):
    """繁中 '拒絕' classifies a sequence as silent; pre-wake rule with
    `not_awake` synonym still matches."""
    l6 = {"reject_rules": [
        {"name": "pre_wake_not_awake",
         "condition": "before_wake opcode received"},
    ]}
    l12 = {"sequences": [
        {"name": "wake_required_check",
         "trigger": "wake_required false then 0x70",
         "expected_behavior": "拒絕"},  # silent synonym
    ]}
    proj = _make_proj(tmp_path, l6, l12=l12)
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr


def test_synonym_address_invalid_covers_addr_out_of_range(tmp_path):
    """`address_invalid` synonym covers `addr_out_of_range` rule."""
    l6 = {"reject_rules": [
        {"name": "addr_out_of_range",
         "condition": "addr exceeds 0x7F"},
    ]}
    l12 = {"sequences": [
        {"name": "address_invalid_drop",
         "trigger": "address_invalid (0x80)",
         "expected_behavior": "drop"},
    ]}
    proj = _make_proj(tmp_path, l6, l12=l12)
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr


def test_synonym_ibt_timeout_covers_frame_timeout(tmp_path):
    """`ibt_timeout` synonym covers `frame_timeout` rule."""
    l6 = {"reject_rules": [
        {"name": "frame_timeout",
         "condition": "inter-byte gap exceeded"},
    ]}
    l12 = {"sequences": [
        {"name": "ibt_timeout_abort",
         "trigger": "ibt_timeout while assembling frame",
         "expected_behavior": "no_response"},
    ]}
    proj = _make_proj(tmp_path, l6, l12=l12)
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr


def test_synonym_size_too_large_covers_len_out_of_range(tmp_path):
    """`size_too_large` synonym covers `len_out_of_range` rule."""
    l6 = {"reject_rules": [
        {"name": "len_out_of_range",
         "condition": "length field too large"},
    ]}
    l12 = {"sequences": [
        {"name": "size_too_large_silent",
         "trigger": "size_too_large LEN=0xFF",
         "expected_behavior": "ignore"},
    ]}
    proj = _make_proj(tmp_path, l6, l12=l12)
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr


# ===========================================================================
# layergate-2 — TARGET-NOT-READY vocabulary family.
#
# Found by l6_fsm_scaffold_actionable_check, which asserts every L6
# reject_rule is machine-matchable by THIS gate's own extractor. A rule
# rejecting a transaction because the target is busy produced ZERO
# keywords, which sent main() down its `if not kws` branch — so ANY one
# unrelated silent sequence "covered" the rule and the gate reported
# PASS. Both directions asserted below.
# ===========================================================================

def test_target_not_ready_rule_yields_keywords(tmp_path):
    """NEGATIVE-CONTROL PRECONDITION: the rule must no longer fall into
    the vacuous `no keywords` branch."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_l11mod", str(PROG))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    kws = mod._rule_keywords(
        {"name": "write_while_busy",
         "condition": "host write while core busy => drop frame"})
    assert kws, "a busy/not-ready rule must yield matchable keywords"
    assert any("busy" in k for k in kws)


def test_target_not_ready_rule_is_covered_by_matching_sequence(tmp_path):
    l6 = {"reject_rules": [
        {"name": "write_while_busy",
         "condition": "host write while core busy => drop frame"},
    ]}
    l12 = {"sequences": [
        {"name": "write_while_busy_dropped",
         "trigger": "issue write while device_busy asserted",
         "expected_behavior": "discard"},
    ]}
    r = _run(_make_proj(tmp_path, l6, l12=l12))
    assert r.returncode == 0, r.stdout + r.stderr


def test_target_not_ready_rule_fails_without_covering_sequence(tmp_path):
    """POSITIVE CONTROL for the negative direction: now that the rule
    yields keywords, an unrelated silent sequence must NOT cover it —
    which is exactly what the missing vocabulary used to allow."""
    l6 = {"reject_rules": [
        {"name": "write_while_busy",
         "condition": "host write while core busy => drop frame"},
    ]}
    l12 = {"sequences": [
        {"name": "unrelated_crc_case",
         "trigger": "crc_mismatch on frame",
         "expected_behavior": "discard"},
    ]}
    r = _run(_make_proj(tmp_path, l6, l12=l12))
    assert r.returncode == 1, r.stdout + r.stderr
