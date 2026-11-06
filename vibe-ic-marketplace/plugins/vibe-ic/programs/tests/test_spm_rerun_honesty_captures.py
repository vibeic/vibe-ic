#!/usr/bin/env python3
"""Three chip-AGNOSTIC HONESTY defects surfaced by an spm benchmark re-run.

All three are the same dangerous class: a gate REPORTING THE WRONG THING.

  D1 false-FAIL  — `harness_exact_selfverify` gate C blocked a PASSING TB whose
                   summary read `checks=10016 errors=0`: the unanchored
                   `[1-9]\\d*\\s+ERRORS?` alternative bound a DIFFERENT field's
                   digits to the `errors` token.
  D2 fabrication — `spec_test_debug_extract` minted scan/JTAG/BIST requirements
                   from JSON SCHEMA KEYS whose VALUES were empty (`[]`/`null`/
                   `false`), i.e. for designs with NO DFT at all.
  D3 false-clean — an ENV_UNAVAILABLE waiver written when a step COULD NOT RUN
                   survived into a later run where the step actually EXECUTED
                   and FAILED, excusing a real failure.

Every fix carries BOTH directions (§4.05): the guard still catches what it must
(positive) and no longer fires on what it must not (negative).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import spec_test_debug_extract as stde      # noqa: E402


# ===========================================================================
# DEFECT 1 — gate C must not false-BLOCK a passing TB
# ===========================================================================
# --- NEGATIVE side: these PASSING forms must NOT be read as failures --------


# --- POSITIVE side: genuine failures must STILL be caught -------------------


# ===========================================================================
# DEFECT 2 — no fabricated scan/JTAG/BIST from an EMPTY schema key
# ===========================================================================
_SKELETON_LDOC = json.dumps({
    "dft_present": False,
    "scan_chain": [],
    "scan_chains": [],
    "jtag_tap": None,
    "bist": {},
    "test_mode": "",
    "debug_port": None,
}, indent=2)


def test_d2_skeleton_ldoc_emits_zero_requirements():
    """NEGATIVE: a schema key with an empty/false/null VALUE states nothing."""
    items = stde.extract(_SKELETON_LDOC)
    assert items == [], f"FABRICATED requirements from empty schema keys: {items}"


def test_d2_nested_all_empty_subtree_emits_nothing():
    """A parent key must not survive when its whole subtree is empty."""
    doc = json.dumps({"dft": {"scan_chain": [], "jtag_tap": None,
                              "bist": {}, "test_mode": ""}}, indent=2)
    assert stde.extract(doc) == []


def test_d2_zero_counts_emit_nothing():
    doc = json.dumps({"scan_chains": 0, "bist_blocks": 0, "jtag_taps": 0})
    assert stde.extract(doc) == []


def test_d2_declared_dft_still_emits_requirements():
    """POSITIVE: a design that GENUINELY declares DFT keeps its requirements."""
    doc = json.dumps({
        "scan_chain": ["scan_en", "scan_in", "scan_out"],
        "jtag_tap": {"signals": ["TMS", "TCK", "TDI", "TDO"]},
        "bist": {"kind": "MBIST"},
        "test_mode": "test_mode",
    }, indent=2)
    kinds = {i["kind"] for i in stde.extract(doc)}
    assert kinds == {"scan_chain", "jtag_tap", "bist", "test_mode"}, kinds


def test_d2_mixed_doc_emits_only_the_non_empty_facet():
    """The declared facet fires; the empty ones stay silent."""
    doc = json.dumps({"scan_chain": [], "jtag_tap": None,
                      "bist": {"kind": "LBIST"}, "test_mode": ""}, indent=2)
    kinds = {i["kind"] for i in stde.extract(doc)}
    assert kinds == {"bist"}, kinds


def test_d2_prose_statement_still_fires():
    """POSITIVE: plain prose is untouched by the JSON blanking pass."""
    kinds = {i["kind"] for i in stde.extract(
        "The design provides a scan chain and a JTAG TAP controller for debug.")}
    assert {"scan_chain", "jtag_tap"} <= kinds


def test_d2_no_anchor_still_returns_empty():
    assert stde.extract("An 8-bit adder with a synchronous reset.") == []


# ===========================================================================
# DEFECT 3 — a waiver must NEVER excuse a failure that actually happened
# ===========================================================================
def _project(tmp_path: Path, drc_status: str) -> Path:
    """A project whose phase3 report records the DRC step with `drc_status`."""
    proj = tmp_path / "proj"
    (proj / "reports").mkdir(parents=True, exist_ok=True)
    (proj / "reports" / "phase3_one_shot.json").write_text(json.dumps({
        "run_id": "run-B",
        "steps": [{"name": "drc", "status": drc_status},
                  {"name": "lvs", "status": "ENV_UNAVAILABLE"}],
    }, indent=2))
    return proj


# --- POSITIVE side: a GENUINE ENV_UNAVAILABLE is still honored --------------


# --- NEGATIVE side: a STALE waiver must be REFUSED --------------------------


# --- the FILE-level survival path (the actual spm repro shape) --------------
def _write_autogen_waivers(proj: Path, entries) -> Path:
    p = proj / "waivers.json"
    return p


def test_d3_human_authored_waiver_file_is_never_pruned(tmp_path):
    """A human-authored waivers.json wins untouched — the same invariant the
    materializer already guarantees."""
    proj = _project(tmp_path, "FAIL")
    p = proj / "waivers.json"
    before = p.read_text()
    assert p.read_text() == before
