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

import json
import sys
from pathlib import Path


_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent


#: Twelve cells, above the module's MIN_CELLS floor.
_N = 12


# ────────────────────────────────────────────────────── it ESTABLISHES


# ═══════════════════════════════════════════════ THE CONTROLS — it REFUSES
#
# Everything above says "established". A deriver that established everything
# would satisfy all of it, and would be far worse than the honest refusal it
# replaced. These are the inputs it must reject.


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


# ══════════════════════════════════════════════ END TO END, THROUGH THE EMITTER
#
# Everything above tests `derive` directly. What has to be true is that the
# PRODUCER writes the established unit into the artefact the GATE reads, so the
# chain is exercised whole — with the PDK layout built FROM the registry's own
# globs rather than from a hardcoded directory name, so it follows the registry
# if the registry moves.
