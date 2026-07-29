#!/usr/bin/env python3
"""The cell exclusion must be in force BEFORE anything can insert a cell.

vibe-ic#551, established by controlled experiment on ibex (sky130A, 47 846
instances), in vibeic-eda:0.2.45:

    exclusion at ROUTE time, from post_cts.def (probe=61)
        -> [ERROR DRT-0085] Valid access pattern combination not found
    exclusion before CTS,    from placed.def  (probe=0)
        -> 0 probe cells after CTS, DRT-0085 = 0, DRT-0073 = 0

`set_dont_use` governs the optimizer's FUTURE cell pool. Against a DEF that
already contains those cells it is inert — and the run still prints
`DONT_USE_APPLIED: 52 cells`, so the guard reads as working while the route
dies. Measured on the real artefacts:

    floorplan.def  probe=0      placed.def  probe=0      post_cts.def  probe=61

The 61 unroutable instances enter between placement and CTS, which is precisely
the window the exclusion has to precede.

The emitted TCL already gets this right — the block sits after `link_design`
and before `set_wire_rc`, resizing, CTS and routing. NOTHING KEPT IT THERE.
These tests are what makes the ordering a property rather than a coincidence,
because the failure it prevents is silent: no error, no warning, just probe
cells in the DEF and a route that cannot finish.
"""
from __future__ import annotations

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import phase3_one_shot_runner as P                            # noqa: E402


def _pnr_template() -> str:
    """The PnR TCL template as the runner writes it, with the block in place.

    COMMENTS STRIPPED. Every one of the six step names appears in the prose
    around this block — `# … governs global_route / detailed_route / the
    antenna repair loop / CTS …` and five more — so a naive scan reported all
    six as "before the exclusion" when not one of them was. That is the same
    mistake I made a day earlier in vibeic-eda, where `actions/runs` in a
    comment read as a reimplementation of the API call it was documenting.

    A check that cannot tell documentation from code has to be weakened the
    first time someone documents something, and then it means nothing.
    """
    src = pathlib.Path(P.__file__).read_text()
    i = src.index("{dont_use_block}")
    win = src[max(0, i - 4000):i + 20000]
    kept = []
    for ln in win.splitlines():
        s = ln.lstrip()
        # Python comments and TCL comments alike: the emitted template carries
        # `#` comment lines of its own, and those are not executed either.
        kept.append("" if s.startswith("#") else ln)
    return "\n".join(kept)


def test_the_exclusion_precedes_every_step_that_can_insert_a_cell():
    """resize, CTS, repair and route must all come after it.

    Ordering asserted against the TEMPLATE the runner emits, not against a
    description of it — the defect this guards is an edit that moves the block,
    and a test reading prose would not notice.
    """
    t = _pnr_template()
    here = t.index("{dont_use_block}")
    for later in ("clock_tree_synthesis", "repair_design", "repair_timing",
                  "global_route", "detailed_route", "detailed_placement"):
        pos = t.find(later, 0, here)
        assert pos == -1, (
            f"`{later}` appears BEFORE the cell exclusion. set_dont_use only "
            f"governs the optimizer's future pool, so anything it inserts "
            f"first is baked into the DEF and the exclusion is inert against "
            f"it (vibe-ic#551: 61 probe cells, DRT-0085, route never finishes)")


def test_the_exclusion_follows_link_design():
    """Before `link_design` there is no library for `set_dont_use` to act on."""
    t = _pnr_template()
    assert t.index("link_design") < t.index("{dont_use_block}")


def test_the_exclusion_reaches_the_template_at_all():
    """A block computed and never interpolated is the wiring failure that
    version of this bug would take: `_dont_use_tcl` runs, the log says nothing,
    and no cell is excluded."""
    src = pathlib.Path(P.__file__).read_text()
    assert "dont_use_block = _dont_use_tcl(pdk)" in src
    assert "{dont_use_block}" in src, "computed and never emitted"
    assert "dont_use_block=dont_use_block" in src, "never passed to the emitter"


def test_the_emitted_exclusion_covers_the_families_that_broke_the_route():
    """The two families in sky130A's own pnr_excluded.cells, plus the fallback.

    Read from the PDK at run time; the fallback is what fires when the PDK
    ships no such file, which is the state that produced #551's route failure
    on an image whose PDK had renamed the directory (openlane -> librelane).
    """
    pdk = P.PdkConfig(name="sky130A", liberty="x", tech_lef="x", cell_lef="x",
                      cell_gds="x", site="unithd", drc_deck="x",
                      pnr_exclude_cell_file="/foss/pdks/sky130A/libs.tech/"
                                            "librelane/sky130_fd_sc_hd/"
                                            "pnr_excluded.cells")
    tcl = P._dont_use_tcl(pdk)
    for fam in ("probe", "lpflow"):
        assert fam in tcl, f"the {fam} family is not in the fallback"
    assert "librelane" in tcl and "openlane" in tcl, \
        "both PDK layouts must be globbed — the rename is what broke this once"
    assert "DONT_USE_SKIPPED" in tcl, \
        "a run that excluded nothing must say so rather than look applied"
