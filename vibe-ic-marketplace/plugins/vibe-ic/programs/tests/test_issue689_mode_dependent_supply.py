"""#689 — a supply with a mode-dependent voltage was recorded as having one.

`_voltage_evidence` returned on its FIRST match, so a rail with more than one
operating voltage had one recorded and the rest dropped — under a
`voltage_status` reading "stated in the design's own documents". A true
quotation of a false summary.

The standard case is a programmable NVM's programming supply. Its own datasheet
gives the elevated voltage FOR PROGRAMMING and the core voltage FOR READING, on
the same pin, four lines apart:

    line 103:  <rail> same as 1.8V VDD for Read
    line 107:  7.5V <rail>, 1.8V VDD for Program

TWO CONCRETE WRONG ANSWERS THAT PRODUCED. `voltage_v` is read by
dynamic_ir_drop_check, ir_drop_budget_check, power_domain_signal_crossing_check,
signoff_ladder_run and phase3_one_shot_runner. A crossing check keyed on
`7.5 != 1.8` demands level shifters on paths that in read mode sit at the same
potential; an IR budget at 7.5 V is wrong for the mode the part spends its life
in. And it mis-scores the CONSEQUENCE of leaving the rail unrealised — "we
cannot burn the array" instead of "the device does not read".

MEASURED after the fix, on that datasheet shape:

    voltage_v = 7.5   complete = False
      1.8V  line 2  'VPP same as 1.8V VDD for Read'
      7.5V  line 4  '7.5V VPP'

THE FALSIFIER THE ISSUE OFFERED WAS CHECKED: `grep -rl voltage_by_mode` over
programs/ found nothing, so the field genuinely did not exist anywhere.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

_spec = importlib.util.spec_from_file_location(
    "l21_macro_supply_rail_synth", _PROGRAMS / "l21_macro_supply_rail_synth.py")
S = importlib.util.module_from_spec(_spec)
sys.modules["l21_macro_supply_rail_synth"] = S
try:
    _spec.loader.exec_module(S)
except SystemExit:
    pass

_NVM = ("Absolute maximum ratings\n"
        "VPP same as 1.8V VDD for Read\n"
        "filler line\n"
        "7.5V VPP, 1.8V VDD for Program\n")


def _doc(tmp_path, text, name="ds.txt"):
    (tmp_path / name).write_text(text)
    return tmp_path


# ── both voltages are captured ────────────────────────────────────────────
def test_both_operating_voltages_are_recorded(tmp_path):
    ev = S._voltage_evidence("VPP", _doc(tmp_path, _NVM), None)
    assert [m["voltage_v"] for m in ev["voltage_by_mode"]] == [1.8, 7.5]
    assert ev["voltage_complete"] is False


def test_voltage_v_stays_the_MAXIMUM(tmp_path):
    """Every existing consumer reads the scalar. Changing what it means would
    break them all at once; the list is what stops the information being lost."""
    ev = S._voltage_evidence("VPP", _doc(tmp_path, _NVM), None)
    assert ev["voltage_v"] == 7.5


def test_the_evidence_keeps_the_whole_clause(tmp_path):
    """`same as 1.8V VDD` states VDD's number, and the sentence asserts THIS pin
    takes it in that mode. A bare `1.8` in the evidence would look like a direct
    statement about VPP; the clause shows the attribution."""
    ev = S._voltage_evidence("VPP", _doc(tmp_path, _NVM), None)
    low = next(m for m in ev["voltage_by_mode"] if m["voltage_v"] == 1.8)
    assert "same as" in low["evidence"]["matched_text"]
    assert "VDD" in low["evidence"]["matched_text"]


# ── a single-voltage rail is unchanged ────────────────────────────────────
def test_a_single_voltage_rail_is_still_COMPLETE(tmp_path):
    """THE ACCEPT CASE. Most rails have one voltage, and marking them incomplete
    would make the new status meaningless."""
    ev = S._voltage_evidence("VDD", _doc(tmp_path, "VDD is 1.8 V\n"), None)
    assert ev["voltage_complete"] is True
    assert ev["voltage_v"] == 1.8
    assert len(ev["voltage_by_mode"]) == 1


def test_the_same_voltage_stated_twice_is_not_two_modes(tmp_path):
    """Repetition is not mode-dependence. Counting it would flag ordinary
    documents that state a rail twice."""
    ev = S._voltage_evidence(
        "VDD", _doc(tmp_path, "VDD is 1.8 V\nlater: VDD = 1.8V\n"), None)
    assert ev["voltage_complete"] is True


def test_no_statement_at_all_is_still_None(tmp_path):
    assert S._voltage_evidence("VPP", _doc(tmp_path, "nothing here\n"), None) is None


# ── the status must SAY it ────────────────────────────────────────────────
def test_the_status_says_MODE_DEPENDENT_not_just_stated():
    """`voltage_status` encoded only PROVENANCE — stated vs inferred — and had
    no representable value meaning "more than one voltage, I captured one".
    That missing value is what let the extractor be truthful about where it read
    and silent about what it dropped."""
    src = (_PROGRAMS / "l21_macro_supply_rail_synth.py").read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert "MODE-DEPENDENT" in body
    i = body.index("MODE-DEPENDENT")
    seg = body[max(0, i - 400):i + 400]
    assert "voltage_complete" in seg, "the status must be gated on completeness"


def test_the_extractor_no_longer_returns_on_the_first_hit():
    """The defect was a `return` inside the scan loop."""
    src = (_PROGRAMS / "l21_macro_supply_rail_synth.py").read_text(encoding="utf-8")
    i = src.index("def _voltage_evidence")
    seg = src[i:src.index("\ndef ", i + 10)]
    assert "found.append(" in seg
    assert "voltage_by_mode" in seg
