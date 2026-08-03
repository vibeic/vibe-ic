"""A harvested L10 test case must not restate its own stimulus as its oracle.

MEASURED DEFECT (pre-fix). `_harvest_test_cases_from_input_tables` picks the
`expected` cell by HEADER SEMANTICS but picked the `stimulus` cell purely
POSITIONALLY — `cells[1]` on any table with three or more columns. On every
table whose oracle column happens to sit at index 1 (a very ordinary shape:
`| test | expected | covers |`) those two resolve to the SAME cell, so the
emitted case carries `stimulus == expected`.

`l10_test_case_oracle_anchor_check` correctly calls that
EXPECTED_RESTATES_STIMULUS: comparing a value against itself is trivially true,
so the generated testbench can never fail. Measured on a CPU cell, 2 of 10
harvested cases had this shape — and the source table was WELL-FORMED: the
stimulus sat in column 0 all along.

Fix: resolve the stimulus by header semantics, and ONLY when the positional
pick collides with the oracle column — so every table that was already correct
stays byte-identical.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]


def _p1():
    key = "p1_l10stim"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(
        key, PROGRAMS / "phase1_doc_one_shot_runner.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[key] = m
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


def _harvest(doc: str):
    return _p1()._harvest_test_cases_from_input_tables({"L7_verification.md": doc})


def _by_name(cases, name):
    return next(c for c in cases if c["name"] == name)


# --------------------------------------------------------------------------
# 1. The defect: oracle column at index 1 of a 3-column table.
# --------------------------------------------------------------------------
_DOC_ORACLE_AT_1 = """
## Verification

| Test firmware | expected result | coverage |
|---|---|---|
| `alpha.hex` | output toggles regularly | fetch, store, loop |
| `beta.hex` | output emits the greeting string | fetch, data read, timing loop |
"""


def test_stimulus_is_not_the_oracle_cell(**_) -> None:
    cases = _harvest(_DOC_ORACLE_AT_1)
    assert len(cases) == 2
    for c in cases:
        assert c["stimulus"] != c["expected"], c


def test_stimulus_is_the_tests_own_column(**_) -> None:
    """The stimulus is the firmware name in column 0 — not a re-read of the
    expectation."""
    cases = _harvest(_DOC_ORACLE_AT_1)
    assert _by_name(cases, "alpha_hex")["stimulus"] == "alpha.hex"
    assert _by_name(cases, "beta_hex")["stimulus"] == "beta.hex"


def test_expected_is_still_taken_by_header_semantics(**_) -> None:
    cases = _harvest(_DOC_ORACLE_AT_1)
    assert _by_name(cases, "alpha_hex")["expected"] == "output toggles regularly"


# --------------------------------------------------------------------------
# 2. No-regression: tables that were already right must not move.
# --------------------------------------------------------------------------
_DOC_ORACLE_AT_2 = """
| scenario | input | expected |
|---|---|---|
| idle case | drive zero | output stays low |
| active case | drive one | output goes high |
"""

_DOC_TWO_COL = """
| scenario | expected |
|---|---|
| reset held | write strobe stays low for the whole assertion |
| reset released | first fetch address equals the reset vector |
"""


def test_three_column_table_with_a_trailing_oracle_is_unchanged(**_) -> None:
    """Here the positional pick (`cells[1]`) does NOT collide with the oracle
    column, so it must be used exactly as before."""
    cases = _harvest(_DOC_ORACLE_AT_2)
    assert _by_name(cases, "idle_case")["stimulus"] == "drive zero"
    assert _by_name(cases, "idle_case")["expected"] == "output stays low"


def test_two_column_table_is_unchanged(**_) -> None:
    cases = _harvest(_DOC_TWO_COL)
    c = _by_name(cases, "reset_held")
    assert c["stimulus"] == "reset held"
    assert c["expected"] == "write strobe stays low for the whole assertion"


# --------------------------------------------------------------------------
# 3. The harvested stimulus is cleaned the same way the oracle is.
# --------------------------------------------------------------------------
def test_stimulus_backticks_are_stripped_like_the_oracles(**_) -> None:
    """`expected` has always had its markdown emphasis stripped. A stimulus
    that keeps its backticks does not match the same name anywhere else."""
    cases = _harvest(_DOC_ORACLE_AT_1)
    for c in cases:
        assert "`" not in c["stimulus"] and "*" not in c["stimulus"]
