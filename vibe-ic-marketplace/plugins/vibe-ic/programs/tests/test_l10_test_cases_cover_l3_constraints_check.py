#!/usr/bin/env python3
"""Tests for l10_test_cases_cover_l3_constraints_check (Wave 39 / D1)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "l10_test_cases_cover_l3_constraints_check.py")


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _make_proj(tmp_path: Path, l3: dict, l10: dict,
               waiver: str | None = None) -> Path:
    proj = tmp_path / "proj"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase1" / "generated_docs" / "L3_CMD_PROTOCOL.json").write_text(
        json.dumps(l3))
    (proj / "phase1" / "generated_docs" / "L10_TEST_CASES.json").write_text(
        json.dumps(l10))
    if waiver is not None:
        (proj / "waivers.json").write_text(json.dumps(
            {"l10_constraint_coverage_partial_intentional": waiver}))
    return proj


def test_skip_when_no_l3(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir(parents=True, exist_ok=True)
    r = _run(proj)
    assert r.returncode == 2


def test_skip_when_no_constraints(tmp_path):
    proj = _make_proj(tmp_path,
                      {"opcodes": [{"hex": "0x74"}]},
                      {"test_cases": [{"id": "TC1", "name": "x"}]})
    r = _run(proj)
    assert r.returncode == 2


def test_fail_when_constraint_uncovered(tmp_path):
    l3 = {"opcodes": [{
        "hex": "0xE2",
        "argument_constraints": [
            {"name": "addr", "max_hex": "0x7F",
             "evidence": "RX_EVENT.txt:8"}
        ],
    }]}
    l10 = {"test_cases": [
        {"id": "TC1", "name": "happy 0xE2", "expect_response": "ok"}
    ]}
    proj = _make_proj(tmp_path, l3, l10)
    r = _run(proj)
    assert r.returncode == 1
    assert "missing" in r.stdout


def test_pass_when_positive_and_negative_present(tmp_path):
    l3 = {"opcodes": [{
        "hex": "0xE2",
        "argument_constraints": [
            {"name": "addr", "max_hex": "0x7F",
             "evidence": "RX_EVENT.txt:8"}
        ],
    }]}
    l10 = {"test_cases": [
        {"id": "TC1", "name": "0xE2 addr=0x7F valid",
         "stimulus": "0xE2 addr 0x7F", "expect_response": "ok"},
        {"id": "TC2", "name": "0xE2 addr=0x80 out_of_range",
         "stimulus": "0xE2 addr 0x80", "expect_no_response": True,
         "negative": True},
    ]}
    proj = _make_proj(tmp_path, l3, l10)
    r = _run(proj)
    assert r.returncode == 0


def test_pre_wake_constraint_needs_negative_test(tmp_path):
    l3 = {"opcodes": [
        {"hex": "0x70", "pre_wake_allowed": False},
    ]}
    l10 = {"test_cases": [
        {"id": "TC1", "name": "0x70 happy", "stimulus": "0x70"}
    ]}
    proj = _make_proj(tmp_path, l3, l10)
    r = _run(proj)
    assert r.returncode == 1
    assert "pre-wake" in r.stdout.lower() or "pre_wake" in r.stdout.lower()


def test_waiver_pass(tmp_path):
    l3 = {"opcodes": [{
        "hex": "0xE2",
        "argument_constraints": [
            {"name": "addr", "max_hex": "0x7F", "evidence": ""},
        ],
    }]}
    l10 = {"test_cases": [{"id": "TC1", "name": "x"}]}
    waiver_text = ("Intentional partial coverage; remaining boundary "
                   "tests deferred to silicon bring-up — "
                   "ENG-DECISION-W39-Z29 over forty chars")
    proj = _make_proj(tmp_path, l3, l10, waiver=waiver_text)
    r = _run(proj)
    assert r.returncode == 0
    assert "waived" in r.stdout
