"""An affirmation-only oracle cell means the SCENARIO cell is the oracle.

MEASURED DEFECT (2026-09-06, subservient x gf180mcuD, front door on v1.17.64,
image 0.3.46).  A verification-plan table of the shape

    | scenario                           | expected           |
    |---|---|
    | reset assert keeps sram content    | <tick>             |
    | rst glitch must not race the fetch | <tick>(sync reset) |

states a PROPOSITION in its scenario column and TICKS the oracle column to say
that proposition must hold.  `_harvest_test_cases_from_input_tables` read the
oracle column positionally and emitted an `expected` that was just the tick, so
`l10_test_case_oracle_anchor_check` refused the case -- VACUOUS_EXPECTED ("a
checkmark or bullet is not an oracle"), or NO_ORACLE_ANCHOR when the tick
trailed a parenthetical rationale.

2 of that design's 10 harvested cases were this shape, and BOTH scenario texts
anchor against the design's OWN observable vocabulary.  The input stated a
checkable property; the harvest filed it where nothing reads it as one.  That
refusal FAILed Step D1, which voided Step 1, which left the P0 umbrella
INCOMPLETE, which forced the whole Phase-2 `final_audit` to FAIL.

FIX: when the oracle cell is AFFIRMATION-LED and its remainder carries no digit
and no comparison relation, the row is an ASSERTION row: carry the scenario cell
as the oracle, prefixed with an explicit polarity word so the case predicts
something rather than restating its scenario, and keep the tick verbatim in
`assertion_affirmation` so the routing is auditable.

NO-LEAK -- each of these is asserted below:
  * a tick that merely PREFIXES a real oracle carries its own oracle in the
    remainder and is left byte-identical;
  * a substantive oracle with no tick is untouched;
  * a row whose scenario cell carries no alphanumeric content is NOT rescued
    (there is no proposition to carry);
  * an affirmation word must be a WHOLE TOKEN, so an ordinary oracle beginning
    with one of their letters is not mistaken for one;
  * the emitted `expected` is never byte-identical to the `stimulus`, so this
    can never manufacture an EXPECTED_RESTATES_STIMULUS case.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]

# U+2705 WHITE HEAVY CHECK MARK -- the affirmation the measured input used.
# Written as an escape so this file's source stays pure ASCII.
TICK = "\u2705"


def _p1():
    key = "p1_l10assert"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(
        key, PROGRAMS / "phase1_doc_one_shot_runner.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[key] = m
    assert spec.loader is not None
    spec.loader.exec_module(m)
    return m


def _harvest(table: str) -> list:
    return _p1()._harvest_test_cases_from_input_tables(
        {"L7_verification_plan.md": table})


def _by_name(cases: list, name: str) -> dict:
    for c in cases:
        if c["name"] == name:
            return c
    raise AssertionError(
        f"{name} not harvested from {[c['name'] for c in cases]}")


def _table(rows: str) -> str:
    return ("## Functional scenarios\n\n"
            "| scenario | expected |\n|---|---|\n" + rows)


_ASSERTION_TABLE = _table(
    f"| reset assert keeps sram content | {TICK} |\n"
    f"| rst glitch must not race the fetch | {TICK}(guaranteed by sync reset) |\n")

# L9/RTL naming is irrelevant here; these are generic, chip-AGNOSTIC rows.


def test_tick_only_row_takes_the_scenario_as_its_oracle():
    """THE DEFECT: a bare tick is not an oracle; the proposition it affirms is."""
    c = _by_name(_harvest(_ASSERTION_TABLE), "reset_assert_keeps_sram_content")
    assert c.get("oracle_from_assertion_row") is True, c
    assert "sram" in c["expected"].lower(), c["expected"]
    assert c["expected"].strip() != c["stimulus"].strip(), c
    assert c["assertion_affirmation"] == TICK, c


def test_tick_with_a_trailing_rationale_is_still_an_assertion_row():
    """The parenthetical is a RATIONALE, not an oracle."""
    c = _by_name(_harvest(_ASSERTION_TABLE), "rst_glitch_must_not_race_the_fetch")
    assert c.get("oracle_from_assertion_row") is True, c
    assert "glitch" in c["expected"].lower(), c["expected"]
    assert c["expected"].strip() != c["stimulus"].strip(), c


def test_a_tick_that_prefixes_a_real_oracle_is_left_alone():
    """NO-LEAK: the remainder carries the oracle; the scenario must not displace it."""
    cases = _harvest(_table(
        f"| run the compliance suite | {TICK} 100% PASS |\n"
        f"| first fetch after reset | {TICK} < 10 cycle |\n"))
    a = _by_name(cases, "run_the_compliance_suite")
    b = _by_name(cases, "first_fetch_after_reset")
    assert a.get("oracle_from_assertion_row") is not True, a
    assert a["expected"] == f"{TICK} 100% PASS", a["expected"]
    assert b.get("oracle_from_assertion_row") is not True, b
    assert b["expected"] == f"{TICK} < 10 cycle", b["expected"]


def test_a_substantive_oracle_with_no_tick_is_untouched():
    """NO-LEAK: rows that never carried an affirmation are byte-identical."""
    c = _by_name(_harvest(_table("| run the compliance suite | 100% PASS |\n")),
                 "run_the_compliance_suite")
    assert c.get("oracle_from_assertion_row") is not True, c
    assert c["expected"] == "100% PASS", c["expected"]


def test_scenario_with_no_alphanumeric_content_is_not_rescued():
    """NO-LEAK: there is no proposition to carry, so the case must still reach
    the gate as vacuous rather than be handed a fabricated oracle."""
    cases = _harvest(_table(f"| >>> <<< | {TICK} |\n"))
    assert cases, "row must still be harvested, not silently dropped"
    c = cases[0]
    assert c.get("oracle_from_assertion_row") is not True, c
    assert c["expected"] == TICK, c["expected"]


def test_an_affirmation_word_must_be_a_WHOLE_token():
    """NO-LEAK, caught on review of this change before it ran on anything.

    The affirmation alternatives include the bare `Y`.  Without a token boundary
    it matches the first letter of an ordinary oracle -- `Yields no error` reads
    as affirmation-led, its remainder carries no digit and no relation, and the
    scenario would have displaced a real oracle.  `Y_AXIS stable` needs the
    boundary to exclude `_` as well as the alphanumerics.
    """
    m = _p1()
    for cell in [TICK, TICK + "(guaranteed by sync reset)", "OK", "Yes", "Y"]:
        assert m._L10_TC_AFFIRM_LED.match(cell), f"{cell!r} is affirmation-led"
    for cell in ["Yields no error", "Yield 3 outputs", "OKAY_STATE reached",
                 "Y_AXIS stable", "PASS", "100% PASS"]:
        assert not m._L10_TC_AFFIRM_LED.match(cell), (
            f"{cell!r} is an ORACLE, not an affirmation")


def test_the_whole_token_rule_survives_end_to_end():
    """The regex rule, driven through the harvester on a real table."""
    cases = _harvest(_table(
        "| bus parity is checked | Yields no error |\n"
        "| axis reference is stable | Y_AXIS stable |\n"))
    a = _by_name(cases, "bus_parity_is_checked")
    b = _by_name(cases, "axis_reference_is_stable")
    assert a.get("oracle_from_assertion_row") is not True, a
    assert b.get("oracle_from_assertion_row") is not True, b
    assert a["expected"] == "Yields no error", a["expected"]
    assert b["expected"] == "Y_AXIS stable", b["expected"]


def test_no_assertion_row_ever_restates_its_stimulus():
    """A rewritten oracle is never byte-identical to its stimulus."""
    for c in _harvest(_ASSERTION_TABLE):
        if c.get("oracle_from_assertion_row"):
            assert c["expected"].strip() != c["stimulus"].strip(), c
