"""Regression for ORGANIC #670 — Phase-1 L7/L10 extractor emits false
`no_*_in_input` honest-absence flags + empty typed lists for no-cmd-protocol
REUSED-IP classes whose input docs DO carry harvestable verification-intent (a
DV checklist table) and a power-on bring-up sequence.

現象 (round-4 v1.0.42 6-IC clean-room): for a no-command-protocol REUSED-IP
class (crypto_accelerator: command_protocol_applicable=false + rtl_gen=null →
_class_no_cmd_protocol=True) the L7 emitter wrote
test_scenarios=[]/test_modes=[]/verification_strategy=[] with
no_verification_strategy_in_input=true, and the L10 emitter wrote
test_cases=[] + bring_up_sequence=[] with no_test_cases_in_input=true /
no_bring_up_sequence_in_input=true — EVEN THOUGH the input docs contain
(a) a structured DV verification-checklist table (testplan / smoke /
regression / coverage / FPV-assertion rows) and (b) an explicit numbered
power-on bring-up + initialization prose sequence. l_doc_structured_field_
count_check then FAILed L7 (need ≥3, have 0) and L10 (need ≥2, have 0); the
#641 escape could not rescue it because bring_up_sequence was EMPTY and L7 was
never in #641's escape set.

Fix (EMITTER-side, chip-AGNOSTIC):
  - L7: harvest the DV/verification CHECKLIST table rows into typed
    test_scenarios[] + verification_strategy[], keyed on the checklist
    table's header semantics (Item/Resolution/Status column family) +
    UPPER_SNAKE item shape; clear no_verification_strategy_in_input when
    content is harvested.
  - L10: harvest the numbered/sequential bring-up + initialization prose into
    a typed bring_up_sequence[] (so the #641 reused-IP credit fires) AND the
    DV checklist rows into test_cases[]; clear the false no_*_in_input flags
    from the ACTUAL harvested content.

NEGATIVE no-leak (load-bearing — the harvesters must NOT fabricate):
  (a) a plain datapath doc with NO checklist table and NO bring-up section
      harvests ZERO entries (the flags stay honestly true);
  (b) a register-map table (Field|Bits|Access) is NOT a DV checklist — ZERO
      entries;
  (c) a test-vector table (Test|Input|Expected) is NOT a DV checklist — ZERO
      entries (it is already covered by the v0.1.77 test-vector harvester and
      must not be double-counted as a checklist);
  (d) the #641 positive case (no-cmd class + no_test_cases_in_input=true +
      POPULATED bring_up_sequence) still PASSes the gate.

chip-AGNOSTIC: registry class flag + DV-checklist-table header semantics +
bring-up section vocab + UPPER_SNAKE item shape; NO chip / vendor / SKU literal.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_doc_one_shot_runner as R  # noqa: E402
import l_doc_structured_field_count_check as G  # noqa: E402

_GEN_DIR = Path("phase1") / "generated_docs"


# ── chip-AGNOSTIC fixtures shaped like the round-4 AES docs (NO chip literal) ─

DV_CHECKLIST_DOC = """## Verification Checklist

### V1

 Type         | Item                                  | Resolution  | Note
--------------|---------------------------------------|-------------|------
Documentation | [DV_DOC_DRAFT_COMPLETED][]            | Done        |
Documentation | [TESTPLAN_COMPLETED][]                | Done        |
Testbench     | [TB_TOP_CREATED][]                    | Done        |
Tests         | [SIM_SMOKE_TEST_PASSING][]            | Done        |
Tests         | [FPV_MAIN_ASSERTIONS_PROVEN][]        | N/A         |
Regression    | [SIM_NIGHTLY_REGRESSION_SETUP][]      | Done        |
Coverage      | [SIM_COVERAGE_MODEL_ADDED][]          | Done        |
"""

BRING_UP_DOC = """# Programmer's Guide

## Clear upon Reset

Upon reset, the unit will first reseed the internal PRNGs and then clear all
key, IV and data registers with pseudo-random data. Only after this sequence
has finished, the unit becomes idle. The unit is then ready for software
initialization.

## Initialization

Before initialization, software must ensure that the unit is idle. To
initialize the unit, software must first provide the configuration to the
control register. Then software must write the initial key registers.

## Block Operation

For block operation, software must initialize the unit as described above.
1. Automatically starts when new input data is available.
1. Does not overwrite previous output data that has not been read.
"""


def _run_l7(tmp_path: Path, extracted: dict) -> dict:
    (tmp_path / _GEN_DIR).mkdir(parents=True, exist_ok=True)
    R.gen_l7_test_debug(tmp_path, extracted)
    return json.loads(
        (tmp_path / _GEN_DIR / "L7_TEST_DEBUG.json").read_text())


def _run_l10(tmp_path: Path, extracted: dict) -> dict:
    (tmp_path / _GEN_DIR).mkdir(parents=True, exist_ok=True)
    R.gen_l10_test_cases(tmp_path, extracted, {"opcodes": []})
    return json.loads(
        (tmp_path / _GEN_DIR / "L10_TEST_CASES.json").read_text())


# ── (0) unit: the two harvesters extract the right structured content ────────

def test_dv_checklist_harvester_extracts_rows():
    rows = R._v1_0_44_harvest_dv_checklist_table({"chk.md": DV_CHECKLIST_DOC})
    names = {r["name"] for r in rows}
    assert "testplan_completed" in names
    assert "sim_smoke_test_passing" in names
    assert "fpv_main_assertions_proven" in names
    assert len(rows) >= 5
    # every row carries an evidence + extraction_strategy (no fabrication)
    for r in rows:
        assert r["extraction_strategy"] == "dv_checklist_table_v1_0_44"
        assert "input/docs/chk.md" in r["evidence"]


def test_bring_up_prose_harvester_extracts_steps():
    steps = R._v1_0_44_harvest_bring_up_steps_from_prose({"pg.md": BRING_UP_DOC})
    assert len(steps) >= 2
    for s in steps:
        assert s.get("step") and s.get("action")
        assert "input/docs/pg.md" in s["evidence"]


# ── (1) L7: DV checklist → typed scenarios + verification_strategy, flag clear ─

def test_l7_harvests_dv_checklist_and_clears_flag(tmp_path: Path):
    l7 = _run_l7(tmp_path, {"aes_checklist.md": DV_CHECKLIST_DOC,
                            "aes_programmers_guide.md": BRING_UP_DOC})
    n_scen = len(l7.get("test_scenarios") or [])
    n_vstrat = len(l7.get("verification_strategy") or [])
    assert n_scen >= 3, f"L7 test_scenarios under floor: {n_scen}"
    assert n_vstrat >= 3, f"L7 verification_strategy under floor: {n_vstrat}"
    # false honest-absence flag is cleared from ACTUAL harvested content
    assert l7.get("no_verification_strategy_in_input") is False
    # the field-count gate passes for the no-cmd REUSED-IP class
    ok, msg = G._check_l_doc(7, l7, ic_class="crypto_accelerator")
    assert ok, f"L7 field-count still FAILs: {msg}"


# ── (2) L10: bring-up prose + DV checklist → cases + sequence, flags clear ────

def test_l10_harvests_bringup_and_checklist_and_clears_flags(tmp_path: Path):
    l10 = _run_l10(tmp_path, {"aes_checklist.md": DV_CHECKLIST_DOC,
                              "aes_programmers_guide.md": BRING_UP_DOC})
    n_bus = len(l10.get("bring_up_sequence") or [])
    n_cases = len(l10.get("test_cases") or [])
    assert n_bus >= 2, f"L10 bring_up_sequence under floor: {n_bus}"
    assert n_cases >= 2, f"L10 test_cases under floor: {n_cases}"
    assert l10.get("no_bring_up_sequence_in_input") is False
    assert l10.get("no_test_cases_in_input") is False
    ok, msg = G._check_l_doc(10, l10, ic_class="crypto_accelerator")
    assert ok, f"L10 field-count still FAILs: {msg}"


# ── (3) NEGATIVE no-leak ──────────────────────────────────────────────────────

def test_plain_doc_harvests_nothing_NOLEAK(tmp_path: Path):
    """A plain datapath doc with NO checklist table and NO bring-up section
    must harvest ZERO entries — the honest-absence flags stay true."""
    plain = {"README.md": (
        "# Multiplier\n\nThis is a multiplier datapath. It computes products.\n\n"
        "| signal | width | dir |\n|--------|-------|-----|\n"
        "| a | 8 | input |\n| b | 8 | input |\n")}
    assert R._v1_0_44_harvest_dv_checklist_table(plain) == []
    assert R._v1_0_44_harvest_bring_up_steps_from_prose(plain) == []
    l7 = _run_l7(tmp_path, plain)
    # no DV checklist → verification_strategy stays empty + flag honest
    assert not [s for s in (l7.get("test_scenarios") or [])
                if s.get("extraction_strategy") == "dv_checklist_table_v1_0_44"]


def test_register_map_table_not_a_checklist_NOLEAK():
    """A register-map table (Field|Bits|Access) is not a DV checklist."""
    regmap = {"regs.md": (
        "## Register Map\n\n| Field | Bits | Access |\n"
        "|-------|------|--------|\n| cfg | 7:0 | rw |\n| mode | 15:8 | rw |\n")}
    assert R._v1_0_44_harvest_dv_checklist_table(regmap) == []


def test_test_vector_table_not_a_checklist_NOLEAK():
    """A test-vector table (Test|Input|Expected) is handled by the v0.1.77
    test-vector harvester and must NOT be double-counted as a DV checklist."""
    tv = {"plan.md": (
        "## Test Plan\n\n| Test | Input | Expected |\n"
        "|------|-------|----------|\n| vec1 | 0x00 | 0xFF |\n"
        "| vec2 | 0x01 | 0xFE |\n")}
    assert R._v1_0_44_harvest_dv_checklist_table(tv) == []


def test_641_positive_case_still_passes_NOLEAK():
    """#641's OWN L10 positive case (no-cmd class + no_test_cases_in_input=true
    + POPULATED bring_up_sequence of >=3 dicts) still returns ok=True."""
    l10 = {
        "test_cases": [],
        "no_test_cases_in_input": True,
        "bring_up_sequence": [
            {"step": 1, "action": "POR", "expected": "idle"},
            {"step": 2, "action": "load_firmware", "expected": "ready"},
            {"step": 3, "action": "release_reset", "expected": "running"},
        ],
    }
    ok, msg = G._check_l_doc(10, l10, ic_class="processor_cpu")
    assert ok, f"#641 positive case regressed: {msg}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
