"""Per-corner multi-corner STA must time the ROUTED netlist, or say it did not.

The defect (measured on a reused-IP CPU core on an open PDK, plugin v1.5.78):
`_emit_multi_corner_sta`'s docstring said the reports were run "against the
routed netlist", but the code read `<synth>/<top>_synth.v` — the PRE-PnR
synthesis netlist — and read NO SPEF. The emitted
`phase3/stage3/sta/per_corner/sta_<CORNER>.rpt` files are consumed as the
EVIDENCE that a multi-corner sign-off STA was performed (`eda_report_audit`
treats a populated per_corner/ as the multi-corner claim;
`sta_corner_record_completeness_check` reads the same tree).

Raw evidence of the size of the mislabel on that cell, all from one run:
  * per-corner TT report (synth netlist, no SPEF)        : wns -18.76 ns
  * OpenROAD's own post-global-route repair result        : WNS  -3.857 ns
  * shipped post-route SPEF sign-off                      : wns -19.60 ns
The per-corner number matched neither the optimizer's view nor the shipped
sign-off; it was a pre-layout number filed in a post-route sign-off path.

The mislabel is dangerous in BOTH directions. On a design PnR improves it reads
pessimistic; on a design PnR degrades — the normal case once real interconnect
RC lands — it reads OPTIMISTIC, i.e. it can present a corner as MET that the
routed design violates. That is a false certificate, so these tests assert the
precedence AND the self-disclosure.
"""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase3_one_shot_runner as R  # noqa: E402

TOP = "my_core"


def _mk(project: Path, *, routed=False, synth=False, spef=False,
        pnr_spef=False):
    pnr = R._pl.pnr_dir(project)
    syn = R._pl.synth_dir(project)
    pnr.mkdir(parents=True, exist_ok=True)
    syn.mkdir(parents=True, exist_ok=True)
    (pnr / "constraint.sdc").write_text("create_clock -period 10 [get_ports clk]\n")
    if routed:
        (pnr / f"{TOP}_pnr.v").write_text("// routed\n")
    if synth:
        (syn / f"{TOP}_synth.v").write_text("// synth\n")
    if spef:
        ex = project / "phase3/stage3/extracted"
        ex.mkdir(parents=True, exist_ok=True)
        (ex / f"{TOP}.spef").write_text("*SPEF\n")
    if pnr_spef:
        (pnr / "post_route_repair.spef").write_text("*SPEF\n")
    return project


# ── precedence ───────────────────────────────────────────────────────────────
def test_routed_netlist_and_spef_win(tmp_path):
    _mk(tmp_path, routed=True, synth=True, spef=True)
    netlist, spef_map, basis, note = R._multi_corner_sta_inputs(tmp_path, TOP)
    assert netlist.name == f"{TOP}_pnr.v", "timed the synth netlist, not the routed one"
    assert spef_map["*"].name == f"{TOP}.spef"
    assert basis == "POST_ROUTE_SPEF"
    assert note


def test_routed_netlist_used_even_when_synth_also_present(tmp_path):
    """The regression guard for the exact defect: both files exist (the normal
    state at canonicalize time) and the routed one MUST win."""
    _mk(tmp_path, routed=True, synth=True)
    netlist, spef_map, basis, _ = R._multi_corner_sta_inputs(tmp_path, TOP)
    assert netlist.name == f"{TOP}_pnr.v"
    assert spef_map == {}
    assert basis == "POST_ROUTE_NO_SPEF"


def test_pnr_spef_is_accepted_as_fallback_parasitics(tmp_path):
    _mk(tmp_path, routed=True, pnr_spef=True)
    _, spef_map, basis, _ = R._multi_corner_sta_inputs(tmp_path, TOP)
    assert spef_map["*"].name == "post_route_repair.spef"
    assert basis == "POST_ROUTE_SPEF"


def test_synth_only_falls_back_but_is_labelled_pre_layout(tmp_path):
    _mk(tmp_path, synth=True)
    netlist, spef_map, basis, note = R._multi_corner_sta_inputs(tmp_path, TOP)
    assert netlist.name == f"{TOP}_synth.v"
    assert spef_map == {}
    assert basis == "PRE_LAYOUT_ESTIMATE", (
        "a pre-PnR netlist must never be reported under a post-route basis")
    low = note.lower()
    assert "pre-layout" in low and "not post-route sign-off" in low
    assert "may violate" in low


def test_each_liberty_corner_is_paired_with_its_own_rc_corner(tmp_path):
    """A real multi-corner sign-off varies the RC corner WITH the liberty
    corner: slow liberty + max-RC is the setup corner, fast liberty + min-RC is
    the hold corner. Annotating every liberty corner with the SAME nominal SPEF
    silently drops the RC dimension of the sweep."""
    _mk(tmp_path, routed=True, spef=True)
    sc = tmp_path / "phase3/stage3/extracted/spef_corners"
    sc.mkdir(parents=True, exist_ok=True)
    for suffix in ("max", "min", "nom"):
        (sc / f"{TOP}.{suffix}.spef").write_text("*SPEF\n")
    _, spef_map, basis, note = R._multi_corner_sta_inputs(tmp_path, TOP)
    assert basis == "POST_ROUTE_SPEF"
    assert spef_map["SS"].name == f"{TOP}.max.spef", "slow liberty needs max-RC"
    assert spef_map["FF"].name == f"{TOP}.min.spef", "fast liberty needs min-RC"
    assert spef_map["TT"].name == f"{TOP}.nom.spef"
    assert "SS->" in note and "FF->" in note


def test_corner_without_its_own_extraction_falls_back_to_nominal(tmp_path):
    _mk(tmp_path, routed=True, spef=True)
    sc = tmp_path / "phase3/stage3/extracted/spef_corners"
    sc.mkdir(parents=True, exist_ok=True)
    (sc / f"{TOP}.max.spef").write_text("*SPEF\n")   # only the setup corner
    _, spef_map, _, _ = R._multi_corner_sta_inputs(tmp_path, TOP)
    assert spef_map["SS"].name == f"{TOP}.max.spef"
    assert "FF" not in spef_map          # resolved via the "*" fallback
    assert spef_map["*"].name == f"{TOP}.spef"


def test_nothing_present_is_missing(tmp_path):
    (tmp_path / "x").mkdir()
    netlist, spef_map, basis, _ = R._multi_corner_sta_inputs(tmp_path, TOP)
    assert netlist is None and spef_map == {} and basis == "MISSING"


# ── the emitted artifact must carry its own limitation ───────────────────────
def _emit(project, monkeypatch, notes):
    """Drive _emit_multi_corner_sta with the container call stubbed out, and
    return the generated tcl text.

    The stub MUST also create the .rpt the real OpenSTA would have written:
    the existing #437(c) guard deletes the whole per_corner/ tree when no
    corner report lands (so an empty dir can never stand as a multi-corner
    claim), which would take the tcl with it."""
    out = project / "phase3/stage3/sta/per_corner"
    out.mkdir(parents=True, exist_ok=True)
    captured = {}

    def fake_exec(container, cmd, **kw):
        for tcl in out.glob("sta_*.tcl"):
            captured["tcl"] = tcl.read_text()
            (out / (tcl.stem + ".rpt")).write_text("wns max -1.0\n")
        return (0, "", "")

    monkeypatch.setattr(R, "_docker_exec", fake_exec)
    monkeypatch.setattr(R, "_to_container_path", lambda p, c: str(p))

    class _Pdk:
        macro_libs: list = []
        name = "testpdk"
        liberty = ""
    lib_dir = project / "libs"
    lib_dir.mkdir(parents=True, exist_ok=True)
    lib = lib_dir / "cells__tt_025C_1v80.lib"
    lib.write_text("library(t){}")
    assert R._emit_multi_corner_sta(project, TOP, _Pdk(), "c", [lib], out, notes)
    return captured["tcl"]


def test_emitted_tcl_reads_spef_and_stamps_post_route_basis(tmp_path, monkeypatch):
    _mk(tmp_path, routed=True, synth=True, spef=True)
    notes = []
    tcl = _emit(tmp_path, monkeypatch, notes)
    assert "read_spef" in tcl, "extracted parasitics were not annotated"
    assert f"{TOP}_pnr.v" in tcl and f"{TOP}_synth.v" not in tcl
    assert "STA_BASIS: POST_ROUTE_SPEF" in tcl
    assert any("basis=POST_ROUTE_SPEF" in n for n in notes)


def test_emitted_tcl_stamps_pre_layout_when_only_synth_exists(tmp_path, monkeypatch):
    """The fallback is allowed — silently presenting it as sign-off is not."""
    _mk(tmp_path, synth=True)
    notes = []
    tcl = _emit(tmp_path, monkeypatch, notes)
    assert "read_spef" not in tcl
    assert "STA_BASIS: PRE_LAYOUT_ESTIMATE" in tcl
    assert "STA_BASIS_NOTE:" in tcl
    assert any("PRE_LAYOUT_ESTIMATE" in n for n in notes)


def test_docstring_no_longer_claims_routed_unconditionally():
    """The original docstring asserted 'against the routed netlist' while the
    code read the synth netlist. Guard the doc/code agreement."""
    doc = R._emit_multi_corner_sta.__doc__ or ""
    assert "PRE_LAYOUT_ESTIMATE" in doc, (
        "the emitter's contract must state the fallback basis it can emit")
