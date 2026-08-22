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

WHAT WAS CORRECTED HERE (2026-08-05)
====================================
41c49f94d re-pointed `_probe_family_reached` from the literal `"__probe_" in
tcl` to `re.fullmatch` over the emitted pattern tokens, and the landing recorded
this file as passing on the pre-landing tree e3aa9b126. MEASURED, it does not
pass there and it does not fail there either: all four tests DIE with

    re.error: nothing to repeat at position 0

because e3aa9b126 emits GLOBS (`*__probe_*`), and a glob is not a regex. So the
file did discriminate the landing, but by crashing — an error whose message
names Python's regex parser and says nothing about pin access, cell pools or
OpenSTA.

The predicate below now models what OpenSTA actually does with what was emitted
— glob mode is case-SENSITIVE and ignores `-nocase` (measured: `[WARNING
STA-0358] -nocase ignored without -regexp`), regex mode fullmatches the whole
cell name — so both trees get an ANSWER, and the pre-landing tree gets an
AssertionError that names the cell it fails to reach.
"""
from __future__ import annotations

import fnmatch
import re
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
    missed = _unreached_probe_cells(tcl)
    assert not missed, (
        f"the fallback does not reach {missed} — the cell that produced "
        f"DRT-0085 is back in every resizer's pool while the run still prints "
        f"DONT_USE_FALLBACK_APPLIED")


def test_the_exclusion_is_matched_the_only_way_openSTA_can_match_it():
    """MEASURED in-container on a commercial 180nm library: OpenSTA honours
    `-nocase` ONLY in regexp mode. In glob mode it prints `[WARNING STA-0358]
    -nocase ignored without -regexp` and matches case-SENSITIVELY —
    `get_lib_cells -nocase -quiet *dly*` returned 0 cells while `-quiet *DLY*`
    returned 4. A block that asks for case-insensitivity while passing globs is
    therefore a block that silently matches nothing on half the libraries in
    the world, and prints that it ran.
    """
    tcl = R._dont_use_family_fallback_tcl()
    flags = re.search(r"get_lib_cells((?: -\w+)*) \$_du_pat", tcl)
    assert flags, tcl
    assert "-regexp" in flags.group(1), (
        f"the do-not-use lookup passes{flags.group(1)!r}: case-insensitive "
        f"matching needs -regexp, and without it OpenSTA drops -nocase and "
        f"matches case-sensitively")


#: the SAME probe family in the two naming conventions the flow has met: the
#: exact master measured breaking the reroute on ibex, and a bare upper-case
#: commercial spelling of the same thing.
_PROBE_CELLS = ("sky130_fd_sc_hd__probe_p_8", "PROBE_X1")


def _unreached_probe_cells(tcl: str):
    """Which of `_PROBE_CELLS` the emitted do-not-use block FAILS to reach.

    Asserted on BEHAVIOUR, not on the `__probe_` spelling. The original pin was
    the literal `"__probe_" in tcl`, and that literal is the OPEN-PDK
    ``<lib>__<fn>`` convention — the very anchoring that made the pattern list
    match ZERO cells on a commercial library while the run still printed
    DONT_USE_FALLBACK_APPLIED. Pinning the spelling would have re-imposed the
    defect on every emitter this file guards.

    The patterns are evaluated the way OpenSTA evaluates them, from the FLAGS
    the block actually passes to `get_lib_cells`:

      * `-regexp`  -> the pattern is a regex and is anchored to the WHOLE cell
                      name (measured: `dly` -> 0 cells, `.*dly.*` -> 4);
      * no flag    -> the pattern is a GLOB, and `-nocase` is IGNORED with
                      `[WARNING STA-0358] -nocase ignored without -regexp`, so
                      matching is case-SENSITIVE however the flag is spelled.

    A pattern set that is not valid under its OWN declared mode reaches nothing,
    which is reported as "reaches nothing" rather than raised — an exception
    here would name Python's regex parser instead of the defect.
    """
    m = re.search(r"foreach _du_pat \{([^}]*)\}", tcl)
    if not m:
        return list(_PROBE_CELLS)
    pats = m.group(1).split()
    flags = re.search(r"get_lib_cells((?: -\w+)*) \$_du_pat", tcl)
    flagtext = flags.group(1) if flags else ""
    regexp = "-regexp" in flagtext
    nocase = "-nocase" in flagtext and regexp   # -nocase alone is dropped

    def reaches(pat: str, cell: str) -> bool:
        if regexp:
            try:
                return bool(re.fullmatch(pat, cell,
                                         re.IGNORECASE if nocase else 0))
            except re.error:
                return False          # OpenSTA would reject it too
        return fnmatch.fnmatchcase(cell, pat)

    return [c for c in _PROBE_CELLS
            if not any(reaches(p, c) for p in pats)]


def _probe_family_reached(tcl: str) -> bool:
    return not _unreached_probe_cells(tcl)


@pytest.mark.parametrize("fn_name,kwargs", RESIZING_EMITTERS,
                         ids=[n for n, _ in RESIZING_EMITTERS])
def test_resizing_path_excludes_unroutable_masters_before_it_resizes(fn_name, kwargs):
    tcl = getattr(R, fn_name)(**kwargs)

    n_du = _first_command_line(tcl, "set_dont_use")
    assert n_du is not None, (
        f"{fn_name} emits no set_dont_use: it can insert an unroutable "
        f"characterization master and detailed_route will die with DRT-0085")

    missed = _unreached_probe_cells(tcl)
    assert not missed, (
        f"{fn_name} emits set_dont_use but its pattern set does not reach "
        f"{missed} — the specific master measured breaking the reroute on ibex, "
        f"and/or the same family under a commercial naming convention")

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
