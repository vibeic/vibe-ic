"""test_issue543_every_resizing_path_excludes_unroutable_cells.py

A do-not-use list that binds on one resizer and not the others is not a list,
it is a coincidence.

WHAT WENT WRONG (vibe-ic#543)
=============================
v1.2.86 added `_dont_use_family_fallback_tcl()` — a `get_lib_cells`-based
exclusion of the `__probe` / `__probec` / `__lpflow_` / `__dly*` families —
because the resizer had inserted `sky130_fd_sc_hd__probe_p_8` as a slew buffer
and TritonRoute cannot generate a pin-access pattern for a probe cell. Its
docstring names the exact failure: `[ERROR DRT-0085] Valid access pattern
combination not found`, swallowed as NONFATAL, leaving a DEF with connectivity
and no `+ ROUTED` geometry.

It was emitted into `pnr.tcl` and nowhere else. THREE other paths resize:

    _ship_signoff_spef_repair_tcl   post-route real-SPEF setup repair
    _ship_wire_length_escalation_tcl  wire-length escalation repair
    _build_eco_repair_tcl           the multi-corner ECO

MEASURED on ibex x sky130A, one run: 4 instances of `probe_p_8` in the repaired
netlist, 1 in the ECO netlist, and `DRT-0085` four times in the repair log —
once pre-reroute and once per convergence iteration, each swallowed by its own
`catch`. The step still published `SHIP_WNS_POSTROUTE`, a name that says
post-REROUTE, from a design whose reroute never completed; sign-off then
recorded the resulting violation as "a genuine process-corner floor".

WHY THIS TEST DRIVES THE EMITTERS
=================================
It asserts on the Tcl these functions actually return, not on the presence of a
call in the source. It also ignores COMMENT lines when locating commands: the
emitted Tcl carries `#` lines that mention `repair_design`, and a first
implementation of this check matched one of those and reported the guard as
mis-ordered when it was not. The probe has to be able to tell a command from a
sentence about a command.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as R  # noqa: E402

_SHIP_ARGS = dict(top="t", tech_lef_c="/a.tlef", cell_lef_c="/b.lef",
                  ss_liberty_c="/ss.lib", pnr_dir_c="/pnr", max_captable_c="/cap",
                  metal_prefix="met", thread_count=8, filler_masters=[])

#: Every emitter that can run `repair_design` / `repair_timing`, with the kwargs
#: that build it. `pnr.tcl`'s builder is not here because it has carried the
#: guard since v1.2.86 — these are the three that did not.
RESIZING_EMITTERS = [
    ("_ship_signoff_spef_repair_tcl", _SHIP_ARGS),
    ("_ship_wire_length_escalation_tcl", _SHIP_ARGS),
    ("_build_eco_repair_tcl", dict(top="t", tech_lef_c="/a.tlef",
                                   cell_lef_c="/b.lef", liberty_c="/ss.lib",
                                   pnr_dir_c="/pnr", eco_dir_c="/eco",
                                   metal_prefix="met",
                                   corner_libs={"ss": "/ss.lib"})),
]


def _first_command_line(tcl: str, token: str):
    """Index of the first NON-COMMENT line carrying `token`, or None.

    Comment-blind matching is the whole reason this helper exists — see the
    module docstring.
    """
    for n, line in enumerate(tcl.splitlines()):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if token in s:
            return n
    return None


def test_the_fallback_still_excludes_the_family_that_broke_routing():
    """FALSIFIABILITY ANCHOR. Every assertion below is about emitting this
    helper; if the helper stopped naming the probe family, they would all still
    pass while excluding nothing that matters."""
    tcl = R._dont_use_family_fallback_tcl()
    assert "set_dont_use" in tcl
    assert "__probe_" in tcl, (
        "the fallback no longer excludes the probe family — the cell that "
        "produced DRT-0085 would be back in every resizer's pool")


@pytest.mark.parametrize("fn_name,kwargs", RESIZING_EMITTERS,
                         ids=[n for n, _ in RESIZING_EMITTERS])
def test_resizing_path_excludes_unroutable_masters_before_it_resizes(fn_name, kwargs):
    tcl = getattr(R, fn_name)(**kwargs)

    n_du = _first_command_line(tcl, "set_dont_use")
    assert n_du is not None, (
        f"{fn_name} emits no set_dont_use: it can insert an unroutable "
        f"characterization master and detailed_route will die with DRT-0085")

    assert "__probe_" in tcl, (
        f"{fn_name} emits set_dont_use without the probe family — the specific "
        f"master measured breaking the reroute on ibex")

    resizes = [n for n in (_first_command_line(tcl, "repair_design"),
                           _first_command_line(tcl, "repair_timing"))
               if n is not None]
    assert resizes, (
        f"{fn_name} no longer resizes; if that is deliberate, drop it from "
        f"RESIZING_EMITTERS rather than leaving a test that proves nothing")

    assert n_du < min(resizes), (
        f"{fn_name} sets the do-not-use list at line {n_du}, AFTER its first "
        f"resize at line {min(resizes)} — a pool restriction that lands after "
        f"the pick is not a restriction")
