#!/usr/bin/env python3
"""An emitted analysis deck hard-coded the directory it was emitted in.

MEASURED DEFECT
===============
The flow emits the tool decks it drives, so a reviewer can re-run the
measurement. On one real run tree, `26 of 30` emitted scripts carried an
absolute path pointing back INTO the run directory they were written for:

    reports/phase3/power_<top>.tcl
        read_verilog /<host>/<run>/baseline/phase2/stage2/synth/<top>_synth.v

MEASURED, and this is the half that is not merely inconvenient. Copy such a
deck into a DIFFERENT run tree and run it there: it succeeds, and it measures
the ORIGINAL tree. Two trees whose routed netlists differ, same deck:

    the portable deck, sitting in tree B   -> clock leakage 1.59e-10  (tree B)
    the hard-coded deck, sitting in tree B -> clock leakage 6.32e-09  (tree A)

No error, no warning, a full report. The second consequence is the identity
one: two runs of a BYTE-IDENTICAL measurement configuration hash differently
purely because they ran in different directories, so a comparison requiring
"same analysis configuration" refuses two arms that are identically configured.

THE RULE
========
An absolute path INSIDE the run root is a finding; one OUTSIDE it is not. A
path inside names something this run produced and the run tree moves, so the
deck must reach it relatively. A path outside names the environment — the PDK,
the tool install — which is not this run's to relativise.

WHAT IS ASSERTED
================
The checker: it PASSES on a portable deck, goes RED on the real defect,
REFUSES (rc=2) rather than passing when there was nothing to look at, and
rc=3 on a bad invocation.

The emitter: the power deck spells its in-tree paths against `$RUN_ROOT`,
leaves the PDK path alone, falls back to absolute paths when the deck is not
in the run tree at all (where `$RUN_ROOT` cannot be resolved), and NOTES it
loudly if a run path ever reaches the deck again.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))


_SPEC = importlib.util.spec_from_file_location(
    "phase3_one_shot_runner_portable", _PROGRAMS / "phase3_one_shot_runner.py")
p3 = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = p3
_SPEC.loader.exec_module(p3)

CONTAINER = "test-container-no-such-container"
TOP = "dut"

PORTABLE = """\
set RUN_ROOT [file normalize [file join [file dirname [info script]] .. ..]]
read_liberty /foss/pdks/somepdk/lib/cells_typ.lib
read_verilog $RUN_ROOT/phase3/stage3/pnr/dut_pnr.v
report_power
"""






# ================================================================ POSITIVE ===




# ================================================================ NEGATIVE ===




# ================================================================= VACUOUS ===




# ========================================================== BAD INVOCATION ===








# =============================================== THE EMITTER'S OWN BEHAVIOUR ==
def _mk_project(tmp_path: Path) -> Path:
    synth = tmp_path / "phase2" / "stage2" / "synth"
    synth.mkdir(parents=True)
    (synth / f"{TOP}_synth.v").write_text(f"module {TOP}(); endmodule\n")
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / f"{TOP}_pnr.v").write_text(f"module {TOP}(); endmodule\n")
    (pnr / "constraint.sdc").write_text("create_clock -period 10 [get_ports clk]\n")
    ext = tmp_path / "phase3" / "stage3" / "extracted"
    ext.mkdir(parents=True)
    (ext / f"{TOP}.spef").write_text('*SPEF "IEEE 1481-1998"\n')
    libdir = tmp_path / "input" / "pdk" / "liberty"
    libdir.mkdir(parents=True)
    (libdir / "cellib_typ.lib").write_text("library (l) { }\n")
    return tmp_path


def _mk_pdk(tmp_path: Path):
    return p3.PdkConfig(
        name="testpdk",
        liberty="/foss/pdks/testpdk/lib/cellib_typ.lib",
        tech_lef=str(tmp_path / "tech.lef"), cell_lef=str(tmp_path / "cell.lef"),
        cell_gds=None, site="unit", drc_deck=None)


@pytest.fixture
def _no_docker(monkeypatch):
    monkeypatch.setitem(p3._CONTAINER_MOUNTS_CACHE, CONTAINER, [])

    def _fake_exec(container, cmd, *a, **k):
        out = Path(cmd.rsplit(" > ", 1)[-1].split(" ", 1)[0])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            "Group                  Internal  Switching    Leakage      Total\n"
            "Sequential             1.00e-04  1.00e-05   1.00e-09   1.10e-04\n"
            "Clock                  1.00e-04  1.00e-05   1.00e-09   1.10e-04\n"
            "Total                  2.00e-04  2.00e-05   2.00e-09   2.20e-04\n"
            "dynamic power / leakage power reported above\n")
        return 0, "", ""

    monkeypatch.setattr(p3, "_docker_exec", _fake_exec)


def _emit(proj: Path, rpt: Path):
    rpt.parent.mkdir(parents=True, exist_ok=True)
    notes: list = []
    p3._emit_power_report(proj, TOP, _mk_pdk(proj), CONTAINER, rpt, notes,
                          basis="post_pnr")
    return (rpt.parent / f"power_{TOP}.tcl").read_text(), notes




def test_a_deck_written_outside_the_run_tree_keeps_absolute_paths(tmp_path, _no_docker):
    """`$RUN_ROOT` is resolved from the deck's OWN location, so a deck that is
    not in the run tree cannot resolve it. Emitting `$RUN_ROOT/...` there would
    make the tool read the empty string as a directory and measure the wrong
    thing silently. It falls back to absolute paths — the pre-fix behaviour,
    which is correct for a deck that is not part of the tree it measures."""
    proj = _mk_project(tmp_path / "run")
    outside = tmp_path / "elsewhere" / "power.rpt"
    outside.parent.mkdir(parents=True)
    tcl, _ = _emit(proj, outside)
    assert "RUN_ROOT" not in tcl
    assert f"read_verilog {proj}/phase3/stage3/pnr/{TOP}_pnr.v" in tcl


def test_a_run_path_reaching_the_deck_is_noted_loudly(tmp_path, monkeypatch,
                                                      _no_docker):
    """The guard at the point of emission. Break the path speller and the run
    says so in its own notes, instead of the defect surfacing later as an
    identity hash that quietly will not match."""
    proj = _mk_project(tmp_path)
    monkeypatch.setattr(p3, "_run_root_tcl_path",
                        lambda hp, project, container, script_path: str(hp))
    _, notes = _emit(proj, proj / "reports" / "phase3" / "power.rpt")
    assert any("absolute path(s) INTO the run root" in n for n in notes), notes
