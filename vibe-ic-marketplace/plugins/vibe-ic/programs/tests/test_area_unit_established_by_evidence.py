#!/usr/bin/env python3
"""The area figure's unit, established from evidence — and refused otherwise.

WHY THIS EXISTS. `area_total_vs_budget_check` compares a synthesised cell area
against a die area declared in MICROMETRES, and could never do it: yosys writes
that figure by summing each cell's Liberty `area`, Liberty declares no area unit
(its `units` group carries time, voltage, current, capacitance, resistance and
power), so the producer honestly recorded "cell-library area unit" and the gate
honestly refused. A correct refusal, and a permanent one: the gate's only
reachable verdict was rc 2 INCOMPLETE.

THE EVIDENCE. A cell's LEF `SIZE w BY h` is in microns by the LEF spec, so
`w * h` is its footprint in um^2, and `pdk_registry.json` already resolves both
`liberty_glob` and `cell_lef_glob` for every PDK it carries. Agreement between
the two over a library's cells MEASURES that the Liberty's area unit is um^2.

MEASURED in the shipped EDA image (vibeic-eda 0.2.26) over all five libraries
the registry resolves — recorded here because these tests do not require the
image, and a number nobody can reproduce from this file is not evidence:

    library  cells   liberty_area / lef_um2        verdict
      A       428    0.999547 .. 1.000000          established
      B       229    1.000000 .. 1.000000          established
      C        84    0.996528 .. 1.111111          established, 1 outlier
      D       135    0.500000 .. 1.000000          established, 1 outlier
      E        42    1.000000 .. 1.000000          established
    and the registry's sixth entry declares no assets -> refused, correctly.

A's count was first published as 405. That was this parser's UNDERCOUNT, not
the library's size: an invented 4000-byte window past each `cell (` header
dropped 23 cells whose `area` sits at offsets 5649..10625, after large pin
blocks. The ratios were unaffected and the conclusion held, which is exactly
why it went unnoticed — and exactly the danger, because a parser that drops 5%
of a library can drop the one cell that DISAGREES, and the disagreement is the
whole signal. Another lane caught it by re-deriving the count and getting 428.
The window is gone; the block is bounded by the next cell, which is what the
grammar says.

THE RULE, AND WHY IT IS NOT FITTED TO THAT ANSWER. C and D each carry exactly
ONE disagreeing cell — D's is a FILLER cell at exactly 0.5, C's is one scan flop
at exactly 10/9 — in libraries where every other cell is exactly 1.000000. A
filler's Liberty area is not its footprint; that is a per-cell modelling
difference and says nothing about the library's unit. A UNIT error looks nothing
like it: every area came out of the same multiplication, so it is a COMMON
FACTOR across the whole population.

So the predicate is about the distribution, not its extremes — median AND
interquartile spread both within tolerance. The controls below prove that choice
discriminates: a library at a common 1000x is REFUSED on the centre, and a
library split between two units is REFUSED on the spread, even though a
median-only rule would have accepted the second. Neither control is a library
this repo ships; both are constructed to break the rule, which is the only way
to show it can be broken.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent


def _au():
    saved = list(sys.path)
    sys.path.insert(0, str(_PROGRAMS))
    try:
        spec = importlib.util.spec_from_file_location(
            "_area_unit_t", _PROGRAMS / "_area_unit.py")
        m = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = m
        spec.loader.exec_module(m)
        return m
    finally:
        sys.path[:] = saved


def _lib(cells: dict) -> str:
    """A minimal Liberty carrying one `area` per cell."""
    body = "\n".join(
        f'  cell ("{n}") {{\n    area : {a} ;\n  }}' for n, a in cells.items())
    return "library (t) {\n" + body + "\n}\n"


def _lef(cells: dict) -> str:
    """A minimal cell LEF carrying one `SIZE w BY h` per macro, in microns."""
    out = []
    for n, (w, h) in cells.items():
        out.append(f"MACRO {n}\n  SIZE {w} BY {h} ;\nEND {n}\n")
    return "\n".join(out)


def _write(tmp: Path, lib_cells: dict, lef_cells: dict):
    lp, fp = tmp / "t.lib", tmp / "t.lef"
    lp.write_text(_lib(lib_cells))
    fp.write_text(_lef(lef_cells))
    return lp, fp


#: Twelve cells, above the module's MIN_CELLS floor.
_N = 12


def _agreeing(scale: float = 1.0):
    """`(liberty, lef)` cell dicts whose ratio is `scale` for every cell."""
    lef = {f"c{i}": (1.0 + i * 0.1, 2.0) for i in range(_N)}
    lib = {n: (w * h) * scale for n, (w, h) in lef.items()}
    return lib, lef


# ────────────────────────────────────────────────────── it ESTABLISHES

def test_a_library_whose_cells_agree_establishes_square_micrometres(tmp_path):
    au = _au()
    lib, lef = _agreeing()
    r = au.derive(*_write(tmp_path, lib, lef))
    assert r["established"] is True, r
    assert r["unit"] == au.UM2
    assert r["unit"] in ("um^2",), "the spelling must be one the gate recognises"
    assert r["cells_compared"] == _N
    assert r["cells_outside_tolerance"] == 0


def test_the_established_unit_is_a_spelling_the_gate_accepts():
    """A unit this module proves and the consuming gate does not recognise
    would be a measurement thrown away at the last step."""
    au = _au()
    saved = list(sys.path)
    sys.path.insert(0, str(_PROGRAMS))
    try:
        spec = importlib.util.spec_from_file_location(
            "_agate_t", _PROGRAMS / "area_total_vs_budget_check.py")
        gate = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = gate
        spec.loader.exec_module(gate)
    finally:
        sys.path[:] = saved
    assert any(s.lower() == au.UM2.lower() for s in gate._UM2_SPELLINGS), (
        f"{au.UM2!r} is not in area_total_vs_budget_check._UM2_SPELLINGS, so a "
        f"unit this module establishes would still be refused downstream")


def test_one_odd_cell_does_not_unmake_the_librarys_unit(tmp_path):
    """The measured case: a FILLER cell at exactly 0.5 among cells at 1.0. Its
    Liberty area is not its footprint, which says nothing about the unit."""
    au = _au()
    lib, lef = _agreeing()
    odd = "c0"
    lib[odd] = lib[odd] * 0.5
    r = au.derive(*_write(tmp_path, lib, lef))
    assert r["established"] is True, r
    assert r["cells_outside_tolerance"] == 1
    assert [o["cell"] for o in r["outliers"]] == [odd], (
        "the outlier must be DISCLOSED by name, not silently dropped")


def test_an_established_record_still_says_how_many_cells_disagreed(tmp_path):
    """"I established the unit" and "I established the unit and one cell
    disagrees" must not produce the same record."""
    au = _au()
    lib, lef = _agreeing()
    clean = au.derive(*_write(tmp_path / "a", lib, lef)) if (
        tmp_path / "a").mkdir() is None else None
    lib2 = dict(lib); lib2["c0"] *= 0.5
    dirty = au.derive(*_write(tmp_path / "b", lib2, lef)) if (
        tmp_path / "b").mkdir() is None else None
    assert clean["established"] and dirty["established"]
    assert clean["cells_outside_tolerance"] == 0
    assert dirty["cells_outside_tolerance"] == 1
    assert clean["reason"] != dirty["reason"]


# ═══════════════════════════════════════════════ THE CONTROLS — it REFUSES
#
# Everything above says "established". A deriver that established everything
# would satisfy all of it, and would be far worse than the honest refusal it
# replaced. These are the inputs it must reject.

def test_the_control_a_common_factor_is_refused_as_a_unit_error(tmp_path):
    """THE ONE THAT MATTERS. Every cell off by the SAME 1000x — which is what a
    unit difference actually looks like, and the ART-POWER-FIGURES-X1000 shape
    one axis over. It must not be accepted and must not be scaled away."""
    au = _au()
    lib, lef = _agreeing(scale=1000.0)
    r = au.derive(*_write(tmp_path, lib, lef))
    assert r["established"] is False, r
    assert r["unit"] is None
    assert "centred on 1000" in r["reason"], r["reason"]
    assert "not scaled to fit" in r["reason"]


def test_the_control_a_thousandth_is_refused_too(tmp_path):
    """The other direction, so the refusal is not one-sided."""
    au = _au()
    lib, lef = _agreeing(scale=0.001)
    r = au.derive(*_write(tmp_path, lib, lef))
    assert r["established"] is False and r["unit"] is None, r


def test_the_control_an_even_split_is_refused_on_the_centre(tmp_path):
    """Half at 1 and half at 1000: the median lands between them, so the CENTRE
    clause refuses it. Recorded as its own case because the first draft of this
    file expected the spread clause here and was wrong about which one fires."""
    au = _au()
    lib, lef = _agreeing()
    for i in range(_N // 2):
        lib[f"c{i}"] *= 1000.0
    r = au.derive(*_write(tmp_path, lib, lef))
    assert r["established"] is False, r
    assert "centred on" in r["reason"], r["reason"]


def test_the_control_the_coherence_clause_can_actually_refuse(tmp_path):
    """A CLAUSE THAT CANNOT FIRE IS NOT A GUARD.

    The centre clause catches an even split, so the spread clause needs its own
    reachable case or it is unfalsifiable decoration. This is it: a MAJORITY at
    1.0 keeps the median inside tolerance, while a large minority elsewhere
    makes the library state no single unit. A median-only rule accepts this
    tree; the spread is what refuses it, and this proves that branch is live."""
    au = _au()
    lib, lef = _agreeing()
    for i in range(7, _N):            # 7 cells at 1.0, 5 far away
        lib[f"c{i}"] *= 1000.0
    r = au.derive(*_write(tmp_path, lib, lef))
    assert abs(r["ratio_median"] - 1.0) <= au.DEFAULT_TOLERANCE, (
        f"median is {r['ratio_median']}, so this fixture no longer isolates "
        f"the coherence clause and the clause may be unreachable again")
    assert r["established"] is False, r
    assert "do not cohere" in r["reason"], r["reason"]


def test_the_control_too_few_comparable_cells_is_not_a_measurement(tmp_path):
    """Agreement over one or two cells is a coincidence. The refusal must name
    the shortfall rather than report a confident unit from nearly no data."""
    au = _au()
    lef = {"c0": (1.0, 2.0), "c1": (2.0, 2.0)}
    lib = {n: w * h for n, (w, h) in lef.items()}
    r = au.derive(*_write(tmp_path, lib, lef))
    assert r["established"] is False
    assert r["cells_compared"] == 2
    assert "coincidence" in r["reason"]


def test_the_control_a_missing_file_is_refused_and_named(tmp_path):
    """"I could not look" must never print what "I looked and it agreed"
    prints, and it must say WHICH file it could not read."""
    au = _au()
    lib, lef = _agreeing()
    lp, fp = _write(tmp_path, lib, lef)
    r1 = au.derive(lp, tmp_path / "absent.lef")
    assert r1["established"] is False and "cell LEF" in r1["reason"]
    r2 = au.derive(tmp_path / "absent.lib", fp)
    assert r2["established"] is False and "Liberty" in r2["reason"]
    r3 = au.derive(None, None)
    assert r3["established"] is False and r3["unit"] is None


def test_the_control_no_cell_in_common_is_refused(tmp_path):
    """Two files describing DIFFERENT libraries share no cell. Comparing them
    would be comparing nothing, and reporting a unit from it would be a verdict
    over an empty population."""
    au = _au()
    lef = {f"a{i}": (1.0, 2.0) for i in range(_N)}
    lib = {f"b{i}": 2.0 for i in range(_N)}
    r = au.derive(*_write(tmp_path, lib, lef))
    assert r["established"] is False
    assert r["cells_compared"] == 0


# ────────────────────────────────────────── the registry resolution half

def test_the_registry_resolves_a_cell_lef_for_the_libraries_it_owns():
    """The cell LEF is found by asking the REGISTRY which PDK owns the Liberty,
    not by guessing a directory layout beside it. Asserted on the registry's
    own shape, offline: the assets must be declared for the resolution to be
    possible at all."""
    reg = json.loads((_PROGRAMS / "pdk_registry.json").read_text())["pdks"]
    with_assets = [e for e in reg
                   if e.get("liberty_glob") and e.get("cell_lef_glob")]
    assert len(with_assets) >= 5, (
        f"only {len(with_assets)} registry entr(ies) declare both a "
        f"liberty_glob and a cell_lef_glob; the cross-check needs both, and "
        f"5 declared them when this was written")


def test_the_control_an_unowned_liberty_resolves_to_nothing(tmp_path):
    """A Liberty no registry entry owns must yield no cell LEF and a reason —
    never a LEF belonging to some other library, which would compare two
    unrelated files and call the result a unit."""
    au = _au()
    stray = tmp_path / "stray.lib"
    stray.write_text(_lib({"c0": 1.0}))
    lef, why = au.resolve_from_registry(stray, _PROGRAMS / "pdk_registry.json")
    assert lef is None
    assert "no registry entry declares a Liberty layout matching" in why


def test_the_control_an_unreadable_registry_is_refused_not_guessed(tmp_path):
    au = _au()
    lef, why = au.resolve_from_registry(tmp_path / "x.lib", tmp_path / "absent.json")
    assert lef is None and "could not be read" in why


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve()), "-v"]))


# ══════════════════════════════════════════════ END TO END, THROUGH THE EMITTER
#
# Everything above tests `derive` directly. What has to be true is that the
# PRODUCER writes the established unit into the artefact the GATE reads, so the
# chain is exercised whole — with the PDK layout built FROM the registry's own
# globs rather than from a hardcoded directory name, so it follows the registry
# if the registry moves.

def _stage_pdk(root: Path, liberty_glob: str, cell_lef_glob: str,
               lib_cells: dict, lef_cells: dict):
    """A PDK tree matching the registry's declared layout, at an arbitrary root.

    This is what proves the root is recovered from the SUPPLIED Liberty rather
    than from the registry's `container_path`: nothing here sits where the
    registry says the real PDK does.
    """
    lp = root / liberty_glob.replace("*", "x")
    fp = root / cell_lef_glob.replace("*", "x")
    lp.parent.mkdir(parents=True, exist_ok=True)
    fp.parent.mkdir(parents=True, exist_ok=True)
    lp.write_text(_lib(lib_cells))
    fp.write_text(_lef(lef_cells))
    return lp


def _a_registry_entry_with_assets():
    reg = json.loads((_PROGRAMS / "pdk_registry.json").read_text())["pdks"]
    for e in reg:
        if e.get("liberty_glob") and e.get("cell_lef_glob"):
            return e
    raise AssertionError("no registry entry declares both globs")


def _emitter():
    saved = list(sys.path)
    sys.path.insert(0, str(_PROGRAMS))
    try:
        spec = importlib.util.spec_from_file_location(
            "_sas_t", _PROGRAMS / "synth_area_stats_emit.py")
        m = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = m
        spec.loader.exec_module(m)
        return m
    finally:
        sys.path[:] = saved


def _synth_run(project: Path, cell: str, per_area: float, n: int):
    """A yosys log and netlist that survive the emitter's own corroboration.

    The emitter REFUTES a figure no independent source agrees with, so a log
    that states a cell count and tabulates nothing is discarded — correctly.
    This writes the histogram row and the matching netlist so the figure is
    corroborated and the emitter actually produces an artefact.
    """
    sd = project / "phase2" / "stage2" / "synth"
    sd.mkdir(parents=True, exist_ok=True)
    total = per_area * n
    log = sd / "yosys.log"
    log.write_text(
        f"=== chip_top ===\n\n   Number of wires:                 88\n"
        f"   Number of cells:                {n}\n"
        f"     {n} {total:.6f} cells\n"
        f"     {n} {total:.6f}   {cell}\n\n"
        f"   Chip area for module '\\chip_top': {total:.6f}\n")
    nl = sd / "netlist.v"
    nl.write_text("module chip_top();\n"
                  + "".join(f"  {cell} u{i} ();\n" for i in range(n))
                  + "endmodule\n")
    return log, nl, total


def test_end_to_end_the_emitter_writes_the_established_unit(tmp_path):
    """The producer must put the MEASUREMENT in the artefact, not just be able
    to make it. Without this, `derive` could be perfect and the gate would
    still read the unestablished sentence forever."""
    sas = _emitter()
    e = _a_registry_entry_with_assets()
    cell, per = "c0", 4.0
    lib_cells = {f"c{i}": (2.0 + i) * 2.0 for i in range(_N)}
    lef_cells = {f"c{i}": (2.0 + i, 2.0) for i in range(_N)}
    liberty = _stage_pdk(tmp_path / "pdk", e["liberty_glob"],
                         e["cell_lef_glob"], lib_cells, lef_cells)
    project = tmp_path / "proj"
    log, nl, total = _synth_run(project, cell, per, 349)

    out = sas.emit_for_run(project, log, nl, liberty=liberty)
    assert out is not None, "the emitter refused; the fixture is not corroborated"
    rep = json.loads(Path(out).read_text())
    assert rep["chip_area"] == pytest.approx(total)
    assert rep["chip_area_unit"] == _au().UM2, rep["chip_area_unit"]
    ev = rep["chip_area_unit_evidence"]
    assert ev["established"] is True
    assert ev["cells_compared"] == _N


def test_end_to_end_no_library_leaves_the_unit_exactly_as_it_was(tmp_path):
    """THE INVARIANT THAT MAKES THIS SAFE TO LAND. A run that cannot reach a
    library must produce byte-identical unit text to before this existed — a
    missing PDK may never become an assumed unit."""
    sas = _emitter()
    ys_saved = list(sys.path)
    sys.path.insert(0, str(_PROGRAMS))
    try:
        spec = importlib.util.spec_from_file_location(
            "_ys_e2e", _PROGRAMS / "_yosys_stat.py")
        ys = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = ys
        spec.loader.exec_module(ys)
    finally:
        sys.path[:] = ys_saved
    project = tmp_path / "proj"
    log, nl, total = _synth_run(project, "c0", 4.0, 349)
    out = sas.emit_for_run(project, log, nl)          # no liberty at all
    assert out is not None
    rep = json.loads(Path(out).read_text())
    assert rep["chip_area_unit"] == ys.AREA_UNIT_UNESTABLISHED
    assert rep["chip_area_unit_evidence"]["established"] is False
    assert "did not report which library" in \
        rep["chip_area_unit_evidence"]["reason"]


def test_end_to_end_an_unresolvable_library_also_leaves_it_unestablished(tmp_path):
    """The second refusal path through the producer: a library real enough to
    read but belonging to no declared layout. It must refuse, and it must say
    so in the artefact rather than silently writing the honest sentence with no
    record of having tried."""
    sas = _emitter()
    stray = tmp_path / "stray.lib"
    stray.write_text(_lib({f"c{i}": 4.0 for i in range(_N)}))
    project = tmp_path / "proj"
    log, nl, _ = _synth_run(project, "c0", 4.0, 349)
    out = sas.emit_for_run(project, log, nl, liberty=stray)
    assert out is not None
    ev = json.loads(Path(out).read_text())["chip_area_unit_evidence"]
    assert ev["established"] is False
    assert "no registry entry declares a Liberty layout" in ev["reason"]


def test_a_cell_whose_area_sits_far_into_its_block_is_still_read(tmp_path):
    """THE REGRESSION, and it was invisible for the worst reason.

    The parser used to look a fixed 4000 characters past each `cell (` header.
    On a shipped library that dropped 23 of 428 cells whose `area` sits at
    offsets 5649..10625, behind large pin blocks — and NOTHING looked wrong,
    because the surviving 405 all agreed and the verdict was unchanged.

    That is the danger this pins: the module's entire signal is DISAGREEMENT,
    so a parser that silently drops part of a library can drop the one cell
    that disagrees and turn a refusal into an establishment. The block is now
    bounded by the next cell, which is what the grammar says; a byte count is a
    guess about how big a cell happens to be.

    The fixture reproduces the shape rather than the library: one cell padded
    past any plausible fixed window, and its area on the far side.
    """
    au = _au()
    pad = "\n".join(f'    /* filler attribute {i} */' for i in range(2000))
    lib = (tmp_path / "t.lib")
    lib.write_text(
        'library (t) {\n'
        '  cell ("near") {\n    area : 4.0 ;\n  }\n'
        f'  cell ("far") {{\n{pad}\n    area : 8.0 ;\n  }}\n'
        '}\n')
    got = au.liberty_areas(lib.read_text())
    assert got.get("near") == 4.0, got
    assert got.get("far") == 8.0, (
        "a cell whose `area` sits past a fixed byte window was dropped; the "
        "parser has reacquired an invented bound, and the cell it drops next "
        "may be the one that disagrees")
    assert len(got) == 2


def test_an_area_is_never_attributed_to_the_wrong_cell(tmp_path):
    """The other direction of the same boundary. Removing the byte window must
    not let a cell with NO area of its own inherit the next cell's — which is
    what an unbounded search would do, and it would be worse than dropping it:
    a fabricated area compares as real."""
    au = _au()
    lib = (tmp_path / "t.lib")
    lib.write_text(
        'library (t) {\n'
        '  cell ("no_area_here") {\n    foo : 1 ;\n  }\n'
        '  cell ("has_area") {\n    area : 9.0 ;\n  }\n'
        '}\n')
    got = au.liberty_areas(lib.read_text())
    assert "no_area_here" not in got, (
        f"a cell with no area of its own was given one: {got}")
    assert got["has_area"] == 9.0
