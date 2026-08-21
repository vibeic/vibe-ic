#!/usr/bin/env python3
"""The two MULTI-CORNER sign-off STA reports must say what stage they describe.

THE DEFECT, AS THE TIMING LANE MEASURED IT
==========================================
`grep -n 'puts .*STA_BASIS' programs/phase3_one_shot_runner.py` at `bb90724dc`::

    34252:  STA_BASIS: POST_ROUTE_SPEF   <- _emit_spef_sta        (SINGLE corner)
    34935:  STA_BASIS: {basis}           <- _emit_multi_corner_sta
    38644:  STA_BASIS: {basis}           <- _emit_aging_sta_report
    the multi-corner SPEF emitter   -> 0 occurrences
    the multi-corner process-OCV emitter -> 0 occurrences

The single-corner report disclosed its stage. The two reports that carry the
ACTUAL SIGN-OFF CORNERS -- `sta_spef_multicorner.rpt` and
`sta_mcorner_ocv.rpt` -- disclosed nothing, so `_ppa/timing.py::_stage_for`
recorded `stage: null` plus a reason for every row it read out of them. It
refuses to infer a stage from a filename on purpose: the moment a pre-layout
report lands in the same directory, an inferred stage would let an estimate be
compared against sign-off evidence. So the fix belongs in the step's own tool,
which is what this file pins.

HOW THIS PROVES IT
==================
By PRODUCING the reports, not by reading the emitter's source. Each emitter
writes a real `.tcl`; the fake `_docker_exec` here runs that `.tcl` through a
real `tclsh` with the STA verbs stubbed out (`unknown` returns the empty
string), so `open`/`puts`/`close`/`catch` are the genuine article and the
`.rpt` on disk afterwards is the emitter's own bytes. The assertions are made
on that file, and then the file is handed to the real downstream reader
(`_ppa.backends.opensta` -> `_ppa.timing._stage_for`) to show the `stage: null`
row is gone.

THE OCV STAMP IS NOT A COPY OF THE SINGLE-CORNER ONE. That emitter's SPEF is
per corner and may be absent, so the stanza stamps `POST_ROUTE_NO_SPEF` when it
read no parasitics and `PRE_LAYOUT_ESTIMATE` when it also fell back to the
synth netlist. Rounding either up to `POST_ROUTE_SPEF` would be the flattering
lie the stamp exists to prevent, and all three cases are covered below.

Chip-, PDK- and vendor-AGNOSTIC: the fixture PDK names no foundry, node or SKU.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase3_one_shot_runner as P  # noqa: E402
import _sta_basis  # noqa: E402
from _ppa import timing as _ppa_timing  # noqa: E402
from _ppa.backends import opensta as _opensta  # noqa: E402

_TCLSH = shutil.which("tclsh")

pytestmark = pytest.mark.skipif(
    _TCLSH is None,
    reason="tclsh is not installed, so the STA decks this runner emits were "
           "NOT executed and no report was produced in this session. This is "
           "a SKIP and not a pass: nothing here looked.")

TOP = "core_top"


def _mk_pdk() -> "P.PdkConfig":
    """A fixture PDK. `tech_lef` must contain `/libs.ref/` so the PDK root is
    derivable; every other value is a placeholder path."""
    return P.PdkConfig(
        name="openpdk",
        liberty="/pdk/openpdk/libs.ref/stdcells/lib/typ.lib",
        tech_lef="/pdk/openpdk/libs.ref/stdcells/techlef/tech.tlef",
        cell_lef="/pdk/openpdk/libs.ref/stdcells/lef/cells.lef",
        cell_gds="/pdk/openpdk/cells.gds", site="unit",
        drc_deck="/pdk/openpdk/drc.lydrc", metal_prefix="met")


def _tcl_exec(recorder):
    """A `_docker_exec` that RUNS the deck the emitter just wrote.

    `unknown` is redefined so every STA verb (`read_liberty`, `link_design`,
    `report_worst_slack ... >> file`, ...) evaluates to the empty string, while
    `open` / `puts` / `close` / `catch` / `if` stay real. What lands on disk is
    therefore the emitter's own report text, produced by the emitter's own
    recipe.
    """
    def fake(container, cmd, timeout=1800, **kw):
        marker = kw.get("marker")
        assert marker, ("the emitter ran a container without naming the deck "
                        "it wrote; there is nothing to execute")
        deck = Path(marker)
        assert deck.is_file(), "deck %s was never written" % deck
        recorder.append(deck)
        driver = deck.with_suffix(".driver.tcl")
        driver.write_text('proc unknown {args} { return "" }\n'
                          'source %s\n' % deck)
        r = subprocess.run([_TCLSH, str(driver)],
                           capture_output=True, text=True)
        assert r.returncode == 0, (
            "tclsh refused the emitted deck %s: %s" % (deck, r.stderr))
        return (0, r.stdout, r.stderr)
    return fake


@pytest.fixture()
def project(tmp_path, monkeypatch):
    """A tree with the artefacts both emitters require, and host paths that
    resolve unchanged 'inside the container' (no mounts -> identity)."""
    monkeypatch.setattr(P, "_container_mounts", lambda c: [])
    pnr = P._pl.pnr_dir(tmp_path)
    pnr.mkdir(parents=True)
    (pnr / f"{TOP}_pnr.v").write_text("module %s(); endmodule\n" % TOP)
    (pnr / "constraint.sdc").write_text(
        "create_clock -name clk -period 10.0 [get_ports clk]\n")
    sta = P._pl.sta_dir(tmp_path)
    sta.mkdir(parents=True)
    for corner in ("max", "min"):
        (sta / f"{TOP}.{corner}.spef").write_text("*SPEF \"IEEE 1481-1998\"\n")
    return tmp_path


def _corner_spefs(project):
    sta = P._pl.sta_dir(project)
    return {c: sta / f"{TOP}.{c}.spef" for c in ("max", "min")}


def _corner_libs():
    return {"SS": "/pdk/openpdk/libs.ref/stdcells/lib/slow.lib",
            "FF": "/pdk/openpdk/libs.ref/stdcells/lib/fast.lib"}


def _stanzas(text):
    """The report's per-corner sections, split on the `===` banner."""
    return [b for b in text.split("=== ")[1:]]


# ======================================================================
# REPORT 1 — sta_spef_multicorner.rpt
# ======================================================================
@pytest.fixture()
def spef_multicorner_report(project, monkeypatch):
    decks = []
    monkeypatch.setattr(P, "_docker_exec", _tcl_exec(decks))
    rpt = P._pl.sta_dir(project) / "sta_spef_multicorner.rpt"
    notes = []
    res = P._emit_corner_spef_sta(
        project, TOP, _mk_pdk(), "c", _corner_spefs(project), rpt, notes,
        corner_libs=_corner_libs())
    assert res["ok"], "the emitter produced no report at all: %s" % notes
    assert decks, "no deck was executed"
    return rpt.read_text()


def test_the_multicorner_spef_report_was_actually_produced(
        spef_multicorner_report):
    """Non-vacuity: the assertions below are made on a file with content."""
    text = spef_multicorner_report
    assert "# Multi-corner SPEF STA" in text
    assert len(_stanzas(text)) == 2, (
        "expected a SETUP and a HOLD stanza, got %d" % len(_stanzas(text)))


def test_the_multicorner_spef_report_declares_its_basis(
        spef_multicorner_report):
    text = spef_multicorner_report
    assert "STA_BASIS: POST_ROUTE_SPEF" in text, (
        "the multi-corner SPEF sign-off report does not say what stage it "
        "describes, so every row read out of it carries stage=null")
    assert _sta_basis.declared_basis(text) == "POST_ROUTE"


def test_every_stanza_of_the_multicorner_spef_report_declares_its_basis(
        spef_multicorner_report):
    """One stamp at the top of a two-corner report would leave the second
    corner's numbers undeclared once the two are read separately."""
    for stanza in _stanzas(spef_multicorner_report):
        assert "STA_BASIS: POST_ROUTE_SPEF" in stanza
        assert "STA_BASIS_LIBERTY: " in stanza


def test_the_multicorner_spef_stamp_names_the_liberty_it_read(
        spef_multicorner_report, ):
    assert ("STA_BASIS_LIBERTY: /pdk/openpdk/libs.ref/stdcells/lib/typ.lib"
            in spef_multicorner_report), (
        "the stamp must name the liberty this stanza actually read -- the "
        "RC axis reads ONE process library across its corners, and a basis "
        "line that does not say which one is a basis nobody can check")


# ======================================================================
# REPORT 2 — sta_mcorner_ocv.rpt
# ======================================================================
def _emit_ocv(project, monkeypatch, *, spefs, nom_spef=None,
              drop_routed_netlist=False):
    decks = []
    monkeypatch.setattr(P, "_docker_exec", _tcl_exec(decks))
    if drop_routed_netlist:
        (P._pl.pnr_dir(project) / f"{TOP}_pnr.v").unlink()
        synth = P._pl.synth_dir(project)
        synth.mkdir(parents=True, exist_ok=True)
        (synth / f"{TOP}_synth.v").write_text(
            "module %s(); endmodule\n" % TOP)
    rpt = P._pl.sta_dir(project) / "sta_mcorner_ocv.rpt"
    notes = []
    ok = P._emit_mcorner_ocv_sta(project, TOP, _mk_pdk(), "c", _corner_libs(),
                                 spefs, nom_spef, rpt, notes)
    assert ok, "the OCV emitter produced no report at all: %s" % notes
    return rpt.read_text()


def test_the_mcorner_ocv_report_was_actually_produced(project, monkeypatch):
    text = _emit_ocv(project, monkeypatch, spefs=_corner_spefs(project))
    assert "OCV_DERATE_APPLIED" in text
    assert len(_stanzas(text)) == 2


def test_the_mcorner_ocv_report_declares_its_basis(project, monkeypatch):
    text = _emit_ocv(project, monkeypatch, spefs=_corner_spefs(project))
    assert "STA_BASIS: POST_ROUTE_SPEF" in text, (
        "the multi-corner process-OCV sign-off report -- the one that carries "
        "the slow-corner verdict -- does not say what stage it describes")
    assert _sta_basis.declared_basis(text) == "POST_ROUTE"
    for stanza in _stanzas(text):
        assert "STA_BASIS: POST_ROUTE_SPEF" in stanza
        assert "STA_BASIS_LIBERTY: " in stanza


def test_the_mcorner_ocv_stamp_names_the_per_corner_liberty(project,
                                                            monkeypatch):
    """This emitter varies the LIBRARY per corner, so its stamp must too. A
    stamp copied from the single-corner emitter would name one library for a
    report that read two, which is the collapse the disclosure block already
    warns about elsewhere in this report."""
    text = _emit_ocv(project, monkeypatch, spefs=_corner_spefs(project))
    libs = _corner_libs()
    assert "STA_BASIS_LIBERTY: %s" % libs["SS"] in text
    assert "STA_BASIS_LIBERTY: %s" % libs["FF"] in text


def test_the_ocv_stamp_says_no_spef_when_it_read_none(project, monkeypatch):
    """§4.05 -- the report never claims parasitics it did not read.

    `POST_ROUTE_NO_SPEF` is an already-recognised stamp value and a DIFFERENT
    stage from `POST_ROUTE_SPEF` to `_ppa/timing.py`; rounding it up would put
    unextracted timing into the extracted bucket.
    """
    text = _emit_ocv(project, monkeypatch, spefs={}, nom_spef=None)
    assert "STA_BASIS: POST_ROUTE_NO_SPEF" in text
    assert "STA_BASIS: POST_ROUTE_SPEF" not in text
    assert _sta_basis.declared_basis(text) == "POST_ROUTE"


def test_the_ocv_stamp_says_pre_layout_when_it_read_the_synth_netlist(
        project, monkeypatch):
    """No SPEF and no routed netlist is a PRE-LAYOUT estimate. Stamping
    POST_ROUTE there would let an estimate be compared against sign-off
    evidence -- the exact confusion the stamp exists to prevent."""
    text = _emit_ocv(project, monkeypatch, spefs={}, nom_spef=None,
                     drop_routed_netlist=True)
    assert "STA_BASIS: PRE_LAYOUT_ESTIMATE" in text
    assert "POST_ROUTE" not in text
    assert _sta_basis.declared_basis(text) == "PRE_LAYOUT"


# ======================================================================
# THE CONSEQUENCE — the downstream reader that had to record stage=null
# ======================================================================
@pytest.mark.parametrize("which", ["spef_multicorner", "mcorner_ocv"])
def test_the_ppa_timing_reader_now_gets_a_stage(project, monkeypatch, which):
    if which == "spef_multicorner":
        decks = []
        monkeypatch.setattr(P, "_docker_exec", _tcl_exec(decks))
        rpt = P._pl.sta_dir(project) / "sta_spef_multicorner.rpt"
        assert P._emit_corner_spef_sta(
            project, TOP, _mk_pdk(), "c", _corner_spefs(project), rpt, [],
            corner_libs=_corner_libs())["ok"]
        text = rpt.read_text()
    else:
        text = _emit_ocv(project, monkeypatch, spefs=_corner_spefs(project))

    report = _opensta.parse_report(text, path="%s.rpt" % which)
    assert report.basis_stamp == "POST_ROUTE_SPEF", (
        "the shipped parser did not pick the stamp out of the produced report")
    stage, gap = _ppa_timing._stage_for(report)
    assert gap is None, gap
    assert stage == "post_route_extracted", (
        "the multi-corner sign-off rows still carry stage=%r" % stage)


def test_the_reader_still_degrades_loudly_on_a_report_with_no_stamp():
    """CONTROL. The stage is read from the stamp and never from the filename,
    so an unstamped report must still come back null-with-a-reason. If this
    ever goes green-by-inference the fix above has been undone somewhere
    downstream."""
    report = _opensta.parse_report(
        "=== SETUP (max-RC corner, SPEF=max, liberty=/pdk/x.lib) ===\n"
        "worst slack max -1.71\n",
        path="sta_spef_multicorner.rpt")
    stage, gap = _ppa_timing._stage_for(report)
    assert stage is None
    assert gap and "STA_BASIS" in gap
