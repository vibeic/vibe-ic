#!/usr/bin/env python3
"""One rule, one yosys line, two producers — and only one of them was held to it.

THE RULE ALREADY EXISTED, tested, in this repo:

    test_issue457_synth_area_stats_emit::test_does_not_invent_an_area_unit
        "The tool prints the figure in the cell library's own unit and never
         restates it; naming a concrete unit here would be an invention."

It was asserted of `synth_area_stats_emit` and of nothing else. `_yosys_stat`
parses the SAME log line —

    Chip area for module '\\top': 5841.196200

— with its own regex, and wrote it to a field whose NAME asserted square
micrometres. So the identical number was unit-asserted by one producer and
explicitly unit-unknown by the other, in one tree, describing one design.

WHY THE NAME IS THE LIE AND THE NUMBER IS NOT. yosys computes that line by
summing each cell's `area` from the Liberty it loaded, so the figure carries
that library's area unit — and Liberty has NO area unit to declare. Its `units`
group carries time, voltage, current, capacitance, resistance and power; `area`
is a bare number. Nothing in the input says micrometres, so nothing downstream
may say it either.

AND IT PROPAGATED, which is what makes it worth a gate rather than a rename.
`synth_netlist_check` read `("chip_area_um2", "chip_area")` first-present-wins
into a field whose name asserted the unit again — so the deliberately-unitless
figure was laundered into a micrometre name by being copied. That is
ART-POWER-FIGURES-X1000 one axis over: a figure that acquires a unit by moving
between fields, with no measurement anywhere in the chain.

WHAT THIS FILE PINS. Not the rename — a rename is undone by the next person who
finds the old name convenient. It pins the RULE, over both producers and the
consumer, in the form the repo already stated it: a name may not assert a unit
the artefact does not establish.

WHAT IT DOES NOT CLAIM. Not that the figure is NOT square micrometres. Measured
on two open PDKs in the shipped EDA image, every standard cell present in both
the Liberty and the cell LEF agrees to within rounding, so for those libraries
it IS. That is a per-library MEASUREMENT and this is an arbitrary library; the
gate `area_total_vs_budget_check` refuses exactly that generalisation, and this
file refuses it the same way rather than differently.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent

#: A yosys stat capture in the `-liberty` shape, which is the only shape that
#: carries an area line at all.
_LIBERTY_LOG = """
=== spm ===

   Number of wires:                 42
   Number of cells:                349
     349 5.84E+03 cells

   Chip area for module '\\spm': 5841.196200
"""


def _mod(name: str):
    saved = list(sys.path)
    sys.path.insert(0, str(_PROGRAMS))
    try:
        spec = importlib.util.spec_from_file_location(
            f"_{name}_areaunit", _PROGRAMS / f"{name}.py")
        m = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = m
        spec.loader.exec_module(m)
        return m
    finally:
        sys.path[:] = saved


#: A field name asserts a unit when it ENDS in one. `um2`/`um^2` anywhere in a
#: name is the shape that matters; a substring match on "um" alone would fire on
#: `column`, `number`, `sum`, so the pattern is anchored to a unit suffix.
_ASSERTS_UNIT = re.compile(r"(?:^|_)u(?:m|M)\^?2$|_um2$|_um_2$")


def _unit_asserting_keys(d: dict) -> list:
    return sorted(k for k in d if _ASSERTS_UNIT.search(k))


# ────────────────────────────────────────── the rule, over BOTH producers

def test_the_stat_parser_does_not_assert_the_unit_in_a_field_name():
    """`_yosys_stat` is the producer that escaped the rule."""
    ys = _mod("_yosys_stat")
    parsed = ys.parse_stat_block(_LIBERTY_LOG)
    assert parsed is not None, "the fixture no longer parses; fix the fixture"
    assert parsed["chip_area"] == pytest.approx(5841.1962)
    offenders = _unit_asserting_keys(parsed)
    assert not offenders, (
        f"_yosys_stat.parse_stat_block emits {offenders}, whose name(s) assert "
        f"a unit the yosys line does not carry. Liberty declares no area unit, "
        f"so the figure's unit is unestablished — record it in "
        f"`chip_area_unit`, never in the name")


def test_the_parser_states_the_unit_is_unestablished_rather_than_omitting_it():
    """An ABSENT unit and an UNESTABLISHED one read identically to a consumer
    that only checks for a key. The sentence is carried explicitly."""
    ys = _mod("_yosys_stat")
    parsed = ys.parse_stat_block(_LIBERTY_LOG)
    assert parsed["chip_area_unit"] == ys.AREA_UNIT_UNESTABLISHED
    assert "um" not in parsed["chip_area_unit"].lower(), (
        "the unestablished-unit sentence must not itself name a unit")


def test_both_producers_say_the_same_thing_about_the_same_number():
    """THE POINT. Two producers parse one yosys line; a reader who consults
    either must get the same answer about its unit. Asserted on the shared
    CONSTANT, not on two equal string literals — two copies of a sentence are
    two things that can drift, and this file would not notice."""
    ys = _mod("_yosys_stat")
    emit = _mod("synth_area_stats_emit")
    src = (_PROGRAMS / "synth_area_stats_emit.py").read_text()
    assert "_ystat.AREA_UNIT_UNESTABLISHED" in src, (
        "synth_area_stats_emit no longer shares the one unit sentence with "
        "_yosys_stat; a second copy can drift and this test cannot see it")
    assert emit._ystat.AREA_UNIT_UNESTABLISHED == ys.AREA_UNIT_UNESTABLISHED


# ──────────────────────────────────────────────── and over the CONSUMER

def test_the_consumer_does_not_relabel_the_figure_as_micrometres():
    """The laundering step. `synth_netlist_check` copied whichever key was
    present into a field whose name asserted the unit again — so the figure
    gained micrometres by being MOVED, with no measurement anywhere."""
    src = (_PROGRAMS / "synth_netlist_check.py").read_text()
    tree_keys = re.findall(r'info\[\"(\w+)\"\]', src)
    offenders = sorted({k for k in tree_keys if _ASSERTS_UNIT.search(k)})
    assert not offenders, (
        f"synth_netlist_check records {offenders}; a figure whose unit is "
        f"unestablished must not be written into a field whose name states one")


def test_the_consumer_still_reads_an_artefact_written_before_the_rename():
    """BACK-COMPAT, asserted rather than hoped. A stats.json written by an
    older plugin carries the old key; refusing to read it would turn this
    correction into a data-loss event on every pre-existing run tree."""
    src = (_PROGRAMS / "synth_netlist_check.py").read_text()
    # Anchored on the AREA assignment, not on the first `_first_present` in
    # the file: there are several, and the first is the cell-count lookup. The
    # first draft of this test matched that one and failed with a message about
    # `cells`, which is the right failure for the wrong reason.
    m = re.search(r'area,\s*area_field\s*=\s*_first_present\(rec, \(([^)]*)\)\)',
                  src, re.DOTALL)
    assert m, "the area-field lookup has moved; re-derive this assertion"
    order = [s.strip().strip('"\'') for s in m.group(1).split(",") if s.strip()]
    assert order[0] == "chip_area", (
        f"lookup order is {order}; the honest key must be tried FIRST, or a "
        f"fresh artefact carrying both would be matched by the legacy name")
    assert "chip_area_um2" in order, (
        f"lookup order is {order}; the legacy key must still be READ so "
        f"artefacts written before the rename are not silently dropped")


# ─────────────────────────────────────────────────────────── THE CONTROL

def test_the_control_the_detector_fires_on_a_unit_asserting_name():
    """Every assertion above says "no offending key was found". That family is
    satisfied completely by a detector that matches nothing, so this proves the
    pattern is live — and that it does NOT fire on ordinary words containing
    the same letters, which is what a naive substring match would do."""
    assert _unit_asserting_keys({"chip_area_um2": 1.0}) == ["chip_area_um2"]
    assert _unit_asserting_keys({"die_area_um^2": 1.0}) == ["die_area_um^2"]
    for innocent in ("column_step", "number_of_cells", "sum", "cells",
                     "chip_area", "chip_area_unit", "maximum"):
        assert _unit_asserting_keys({innocent: 1}) == [], innocent


def test_the_control_a_generic_log_still_reports_no_area_at_all():
    """The other direction: without `-liberty` yosys prints no area line, and
    the parser must report None rather than a zero. A fabricated 0.0 would pass
    every assertion above while being the worst possible answer."""
    ys = _mod("_yosys_stat")
    parsed = ys.parse_stat_block(
        "=== spm ===\n\n   Number of cells:                349\n")
    assert parsed is not None
    assert parsed["chip_area"] is None, (
        "no area line must yield None, never 0.0 — a fabricated zero is a "
        "measurement nobody made")
    assert parsed["chip_area_unit"] == ys.AREA_UNIT_UNESTABLISHED


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve()), "-v"]))
