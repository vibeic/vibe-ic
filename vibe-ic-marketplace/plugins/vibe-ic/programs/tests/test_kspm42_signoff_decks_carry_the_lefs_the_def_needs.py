#!/usr/bin/env python3
"""kspm42 — a re-opened DEF needs every LEF that defines a master it names.

Three sign-off decks re-open `routed.def` in a FRESH OpenROAD session — the
post-route timing repair, the real-SPEF sign-off repair, and the DRV
wire-length escalation — and each loaded exactly two LEFs, the tech LEF and the
standard-cell LEF. `read_def` is the FIRST command after them, so a DEF that
instantiates anything else loses the WHOLE step before it does any work.

MEASURED, spm x gf180mcuD, a 36-pad chip top, the run as shipped
(phase3/stage3/pnr/signoff_spef_repair.log):

    [WARNING ODB-0099] error: netlist component (u_pad_y) is not defined
    ... one per pad instance ...
    [ERROR ODB-0421] DEF parser returns an error!
    Error: signoff_spef_repair.tcl, 5 ODB-0421

— no SHIP_ marker of any kind, no routed_repaired.def, no <top>_pnr_repaired.v.
The step's own record still reads PASS ("no-op, base route kept"), because a
deck that dies at `read_def` and a repair that honestly found nothing to do are
the same shape from the outside. The no-pad arm of the SAME design on the SAME
host reaches SHIP_SIGNOFF_REPAIR_DONE, so this is the pad ring, not the design.

The same deck with the IO LEFs inserted after the std-cell LEF, nothing else
changed, against the SAME routed.def: rc=0, zero ODB-0099, zero ODB-0421,
`SHIP_SIGNOFF_REPAIR_DONE`, and both artefacts written.
"""
from __future__ import annotations
import sys
from pathlib import Path
_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import phase3_one_shot_runner as p3  # noqa: E402


class _Pdk:
    """The only PdkConfig surface `_def_reopen_extra_lefs_c` reads."""
    def __init__(self, macro_lefs):
        self.macro_lefs = list(macro_lefs)


def _def(tmp_path: Path, masters) -> Path:
    body = "\n".join(f"    - u_{i} {m} + FIXED ( 0 0 ) N ;"
                     for i, m in enumerate(masters))
    p = tmp_path / "routed.def"
    p.write_text("VERSION 5.8 ;\nCOMPONENTS %d ;\n%s\nEND COMPONENTS\n"
                 % (len(masters), body))
    return p


def _lef(tmp_path: Path, name: str, macros) -> str:
    p = tmp_path / f"{name}.lef"
    p.write_text("".join(f"MACRO {m}\n  CLASS CORE ;\nEND {m}\n" for m in macros))
    return str(p)


def _no_io(monkeypatch):
    """A PDK that ships no IO library — the ordinary state, and never fatal."""
    monkeypatch.setattr(p3, "_discover_padring_io_views",
                        lambda pdk, c: (_ for _ in ()).throw(ValueError("none")))


def test_only_lefs_defining_a_master_the_def_names_are_read(tmp_path, monkeypatch):
    """Precision in both directions. A LEF that defines a master the DEF
    instantiates is read; a LEF that defines only masters nothing instantiates
    is not — a deck must not grow every library in the PDK."""
    _no_io(monkeypatch)
    needed = _lef(tmp_path, "needed", ["MACRO_USED"])
    unused = _lef(tmp_path, "unused", ["MACRO_NEVER_INSTANTIATED"])
    d = _def(tmp_path, ["STD_CELL_A", "MACRO_USED", "STD_CELL_A"])
    got = p3._def_reopen_extra_lefs_c(d, _Pdk([needed, unused]), None)
    assert got == [needed], got


def test_a_design_needing_nothing_extra_gets_an_empty_list(tmp_path, monkeypatch):
    """THE NO-OP CONTROL. A design with no macro and no pad ring must emit the
    deck it emits today, byte for byte, so this change cannot perturb a design
    it is not for."""
    _no_io(monkeypatch)
    unused = _lef(tmp_path, "unused", ["MACRO_NEVER_INSTANTIATED"])
    d = _def(tmp_path, ["STD_CELL_A", "STD_CELL_B"])
    assert p3._def_reopen_extra_lefs_c(d, _Pdk([unused]), None) == []
    assert p3._extra_lef_read_block([]) == ""
    assert p3._extra_lef_read_block(None) == ""


def test_the_padring_io_library_is_a_candidate_like_any_macro(tmp_path, monkeypatch):
    """The pad ring is why this exists. The IO views come from the SAME
    resolver the router and the streamout use — a deck must not be able to
    disagree with them about which views exist."""
    io = _lef(tmp_path, "io_in_c", ["IO_PAD_IN"])
    monkeypatch.setattr(p3, "_discover_padring_io_views",
                        lambda pdk, c: ([io], ["/x.gds"]))
    d = _def(tmp_path, ["STD_CELL_A", "IO_PAD_IN"])
    assert p3._def_reopen_extra_lefs_c(d, _Pdk([]), None) == [io]


def test_a_def_that_cannot_be_read_contributes_nothing_and_never_raises(tmp_path,
                                                                       monkeypatch):
    """Best-effort: a missing or unparsable DEF yields [] rather than an
    exception that would take the whole step down."""
    _no_io(monkeypatch)
    assert p3._def_reopen_extra_lefs_c(tmp_path / "absent.def", _Pdk([]), None) == []
    empty = tmp_path / "empty.def"
    empty.write_text("VERSION 5.8 ;\n")
    assert p3._def_reopen_extra_lefs_c(empty, _Pdk([]), None) == []


# --- the three decks -------------------------------------------------------

def _decks(extra):
    """The three DEF-reopening decks, built with the same inputs."""
    return {
        "postroute_timing_repair": p3._build_postroute_timing_repair_tcl(
            "top", "/t.tlef", "/c.lef", "/l.lib", "/pnr", "/rep", "M",
            extra_lefs_c=extra),
        "signoff_spef_repair": p3._ship_signoff_spef_repair_tcl(
            "top", "/t.tlef", "/c.lef", "/ss.lib", "/pnr", "/cap.rules", "M",
            8, extra_lefs_c=extra),
        "drv_escalation": p3._ship_wire_length_escalation_tcl(
            "top", "/t.tlef", "/c.lef", "/ss.lib", "/pnr", "/cap.rules", "M",
            8, extra_lefs_c=extra),
    }


def test_every_def_reopening_deck_reads_the_extra_lefs_before_read_def():
    """ORDER IS THE WHOLE POINT. A `read_lef` after `read_def` is too late —
    the parse has already aborted. Pinned for all three decks at once so the
    family cannot be half-fixed."""
    for name, tcl in _decks(["/io_a.lef", "/io_b.lef"]).items():
        assert "read_lef /io_a.lef" in tcl, name
        assert "read_lef /io_b.lef" in tcl, name
        first_def = min(i for i, l in enumerate(tcl.splitlines())
                        if l.startswith("read_def "))
        last_extra = max(i for i, l in enumerate(tcl.splitlines())
                         if l.startswith("read_lef /io_"))
        assert last_extra < first_def, (
            f"{name}: an extra read_lef lands AFTER read_def, which is after "
            f"the parse it exists to keep alive")


def test_no_extra_lefs_reproduces_the_deck_byte_for_byte():
    """The other half of the no-op control, on the decks themselves."""
    none_given = _decks(None)
    empty_given = _decks([])
    for name in none_given:
        assert none_given[name] == empty_given[name], name
        assert "read_lef /io_" not in none_given[name], name


def test_the_prefix_tree_can_run_this_and_answers_wrongly():
    """THE BIDIRECTIONAL CONTROL, written so the PRE-FIX code can execute it.

    A test that raises TypeError/AttributeError against the old tree has
    observed nothing. This one falls back to the old signature, so the pre-fix
    tree produces a deck and the assertion judges THAT deck: it reads two LEFs
    and no more, which is the defect, stated as an answer rather than a crash.

    The live half of the control is not a stub at all -- the shipped
    signoff_spef_repair.log for a 36-pad chip top ends `[ERROR ODB-0421] DEF
    parser returns an error!` with no SHIP_ marker, and the identical deck with
    the IO LEFs inserted reaches SHIP_SIGNOFF_REPAIR_DONE on the same DEF."""
    builders = [
        ("postroute_timing_repair", p3._build_postroute_timing_repair_tcl,
         ("top", "/t.tlef", "/c.lef", "/l.lib", "/pnr", "/rep", "M"), {}),
        ("signoff_spef_repair", p3._ship_signoff_spef_repair_tcl,
         ("top", "/t.tlef", "/c.lef", "/ss.lib", "/pnr", "/cap.rules", "M", 8), {}),
        ("drv_escalation", p3._ship_wire_length_escalation_tcl,
         ("top", "/t.tlef", "/c.lef", "/ss.lib", "/pnr", "/cap.rules", "M", 8), {}),
    ]
    for name, fn, args, kw in builders:
        try:
            tcl = fn(*args, extra_lefs_c=["/io_a.lef"], **kw)
        except TypeError:
            tcl = fn(*args, **kw)          # the pre-fix signature
        assert "read_lef /io_a.lef" in tcl, (
            f"{name}: the deck names only the tech + std-cell LEF, so a DEF "
            f"instantiating any other master aborts ODB-0421 at read_def and "
            f"the whole step is lost")


def test_the_tech_and_cell_lef_are_never_offered_twice(tmp_path, monkeypatch):
    """The deck ALREADY reads the tech + std-cell pair. A candidate list that
    re-offers either of them would make the deck read the same library twice,
    so they are excluded here rather than trusted not to appear."""
    _no_io(monkeypatch)
    cell = _lef(tmp_path, "cells", ["STD_CELL_A"])
    tech = _lef(tmp_path, "tech", ["STD_CELL_A"])
    macro = _lef(tmp_path, "macro", ["MACRO_USED"])
    pdk = _Pdk([cell, tech, macro])
    pdk.cell_lef, pdk.tech_lef = cell, tech
    d = _def(tmp_path, ["STD_CELL_A", "MACRO_USED"])
    assert p3._def_reopen_extra_lefs_c(d, pdk, None) == [macro]
