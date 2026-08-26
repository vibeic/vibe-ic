"""Post-layout LEC: the standard cells were loaded TWICE, so nothing was proven.

THE DEFECT (measured, long-standing — the published spm specimen ships it)
=========================================================================
`build_yosys_equiv_script` read the Liberty and then read the PDK's blackbox
Verilog for the SAME library. Both files declare the same standard cells, and
plain `read_verilog -lib` OVERWRITES an existing module, so Yosys refused:

    sky130_fd_sc_hd__blackbox.v:37: ERROR: Re-definition of module
    `\\sky130_fd_sc_hd__a2bb2o_1'!

The whole proof aborted -> `lec_post_layout.json` verdict RUN_ERROR, yosys_rc 1,
proven_points null. Equivalence was never proven for any routed netlist.

WHICH SOURCE THE PROOF NEEDS
----------------------------
The Liberty is the ONLY source that carries cell FUNCTION; the blackbox Verilog
declares the same cells as EMPTY modules and exists solely to name the cells the
Liberty does NOT model (fill / tap / endcap / diode / IO pads) so `hierarchy`
does not abort. So neither source may be dropped and the Liberty must WIN:
`-nooverwrite` makes the blackbox read purely ADDITIVE. Silencing the collision
the other way (letting the stub win) would replace every functional model with a
function-less box and the proof would become vacuous in the worst way — a
NAND-for-NOR swap would "prove".

TWO MORE THINGS THE SAME PROOF NEEDED TO PRODUCE A REAL NUMBER
--------------------------------------------------------------
(b) GOLD was hard-coded to `<top>_synth.v`, the PRE-DFT netlist, while PnR
    routes `post_dft_netlist.v` on any design with a scan chain. `equiv_make`
    then aborts "Can't match gate port `shift_gate' to a gold port" — another
    RUN_ERROR that says nothing about the routed logic. Gold is now the netlist
    `pnr_input_netlist` says PnR actually routed.
(c) `_synthesize_physical_cell_stubs` decided which cells to blackbox by reading
    the Liberty with a plain HOST `Path(...).read_text()`. The Liberty lives
    inside the EDA container, so that raised OSError, the "cells the Liberty
    models" set was EMPTY, and the generated stub file blackboxed every cell in
    the design (MEASURED on spm x sky130A: 46 stubs, nand2 / a211oi / mux2
    included). That file is read into the same proof.

Every test below drives the REAL shipped functions.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGS))

import phase3_one_shot_runner as R  # noqa: E402
import lec_post_layout_check as LEC  # noqa: E402


TOP = "widget"
BB = "/pdk/libs.ref/sc/verilog/sc__blackbox.v"
LIB = "/pdk/libs.ref/sc/lib/sc__tt.lib"


# ---------------------------------------------------------------------------
# (a) THE REDEFINITION — the blackbox read must never overwrite a Liberty cell
#
# MUTATION THESE CATCH: restore `read_verilog -lib {q}` in
# `build_yosys_equiv_script` / `_read_blackbox_cmd`.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("functional", [True, False])
def test_blackbox_verilog_can_never_overwrite_a_liberty_cell(functional):
    ys = LEC.build_yosys_equiv_script("gold.v", "gate.v", LIB, TOP,
                                      blackbox_v=[BB, "/w/stubs.v"],
                                      functional_lib=functional)
    reads = [ln for ln in ys.splitlines() if ln.startswith("read_verilog -lib")]
    assert reads, "the blackbox inputs must still be read — dropping them " \
                  "leaves fill/tap/pads undefined and hierarchy aborts"
    for ln in reads:
        assert "-nooverwrite" in ln, (
            f"{ln!r} lets an EMPTY blackbox module replace the Liberty cell of "
            f"the same name; Yosys refuses the collision outright "
            f"('Re-definition of module') and the whole proof aborts")


@pytest.mark.parametrize("functional", [True, False])
def test_the_liberty_is_read_before_every_blackbox_file(functional):
    """`-nooverwrite` KEEPS whatever is already defined, so the source that
    carries FUNCTION has to be read first for the priority to be the right way
    round."""
    ys = LEC.build_yosys_equiv_script("gold.v", "gate.v", LIB, TOP,
                                      blackbox_v=[BB], functional_lib=functional)
    lines = ys.splitlines()
    lib_at = [i for i, ln in enumerate(lines) if ln.startswith("read_liberty")]
    bb_at = [i for i, ln in enumerate(lines) if ln.startswith("read_verilog -lib")]
    assert lib_at and bb_at
    for b in bb_at:
        assert any(l < b for l in lib_at), \
            "a blackbox file is read before any read_liberty on its side"


def test_a_redefinition_abort_is_a_run_error_never_a_pass():
    """The exact transcript the defect produced (specimen v1.10.18_sky130A).
    A recipe that cannot even load its inputs must not report equivalence."""
    log = (
        "1. Executing Liberty frontend: /pdk/sc__tt.lib\n"
        "Imported 428 cell types from liberty file.\n"
        "3. Executing Verilog-2005 frontend: /pdk/sc__blackbox.v\n"
        "sc__blackbox.v:37: ERROR: Re-definition of module `\\sc__a2bb2o_1'!\n")
    parsed = LEC.parse_equiv_log(log)
    assert parsed["verdict"] == LEC.V_RUN_ERROR
    assert parsed["equivalent"] is False
    assert parsed["proven"] is None and parsed["total"] is None
    assert LEC.evaluate_report({
        "verdict": parsed["verdict"], "total_points": parsed["total"],
        "proven_points": parsed["proven"], "unproven_points": parsed["unproven"],
        "equivalent": parsed["equivalent"], "skipped": False,
    })["result"] == "FAIL"


# ---------------------------------------------------------------------------
# helpers for the runner-level tests
# ---------------------------------------------------------------------------

def _pdk(liberty: str, lef: str) -> R.PdkConfig:
    return R.PdkConfig(name="testpdk", liberty=liberty, tech_lef=lef,
                       cell_lef=lef, cell_gds=None, site="unit", drc_deck=None)


@pytest.fixture()
def stub_container(monkeypatch):
    """Neutralise the container round-trips; the decisions under test are pure
    python. rc is settable so a test can make yosys 'fail'."""
    def _fake_exec(container, cmd, timeout=1800, **kw):
        return (_fake_exec.rc, "", "")
    _fake_exec.rc = 0
    monkeypatch.setattr(R, "_docker_exec", _fake_exec)
    monkeypatch.setattr(R, "_docker_exec_raw", _fake_exec)
    monkeypatch.setattr(R, "_discover_blackbox_verilog", lambda *a, **k: [])
    monkeypatch.setattr(R, "_to_container_path", lambda p, c: str(p))
    return _fake_exec


def _scan_project(tmp_path: Path, with_chain: bool = True) -> Path:
    """A routed project whose PnR input was the POST-DFT netlist (the shape the
    hard-coded `<top>_synth.v` gold got wrong)."""
    pnr = R._pl.pnr_dir(tmp_path)
    synth = R._pl.synth_dir(tmp_path)
    for d in (pnr, synth):
        d.mkdir(parents=True, exist_ok=True)
    (synth / f"{TOP}_synth.v").write_text(
        f"module {TOP}(clk, a, y);\n  input clk;\n  input a;\n  output y;\n"
        f"endmodule\n")
    (synth / "post_dft_netlist.v").write_text(
        f"module {TOP}(clk, a, y, sin, shift, sout);\n  input clk;\n"
        f"  input a;\n  output y;\n  input sin;\n  input shift;\n"
        f"  output sout;\nendmodule\n")
    (pnr / f"{TOP}_pnr.v").write_text(
        f"module {TOP}(clk, a, y, sin, shift, sout);\n  input clk;\n"
        f"  input a;\n  output y;\n  input sin;\n  input shift;\n"
        f"  output sout;\nendmodule\n")
    (pnr / f"{TOP}.def").write_text("DIEAREA ( 0 0 ) ( 100 100 ) ;\n")
    meta = tmp_path / "reports/phase2/dft"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "scan_chain.json").write_text(json.dumps({
        "published": bool(with_chain),
        "chain_length_matches_flop_count": bool(with_chain),
        "dft_ports": ["sin", "shift", "sout"],
        "internal_chain_length": 65, "boundary_chain_length": 34,
        "area_instances_delta": 201, "area_instances_delta_pct": 70.0,
    }))
    return tmp_path


def _emit(project: Path, pdk, monkeypatch, out: Path):
    notes: list = []
    monkeypatch.setattr(R, "_synthesize_physical_cell_stubs",
                        lambda *a, **k: None)
    verdict = R._emit_lec_post_layout(project, TOP, pdk, "nocontainer",
                                      out, out.with_suffix(".rpt"), notes)
    return verdict, json.loads(out.read_text()), notes


# ---------------------------------------------------------------------------
# (b) GOLD — the reference has to be the netlist PnR actually routed
#
# MUTATION THESE CATCH: restore `gold = synth_out / f"{top}_synth.v"`.
# ---------------------------------------------------------------------------

def test_gold_is_the_netlist_pnr_actually_routed(tmp_path, stub_container,
                                                 monkeypatch):
    lib = tmp_path / "sc__tt.lib"
    lib.write_text("library(t){ cell (\"AND2\") {} }\n")
    project = _scan_project(tmp_path, with_chain=True)
    _v, doc, _n = _emit(project, _pdk(str(lib), str(tmp_path / "c.lef")),
                        monkeypatch, tmp_path / "out.json")
    assert Path(doc["gold"]).name == "post_dft_netlist.v", (
        "gold was the PRE-DFT netlist while the gate is the routed POST-DFT "
        "one; equiv_make cannot match the scan ports and the proof aborts")
    assert doc["gold_kind"] == "post_dft"


def test_gold_is_unchanged_when_no_scan_chain_was_inserted(tmp_path,
                                                           stub_container,
                                                           monkeypatch):
    """A design with no measured chain routes `<top>_synth.v`; the gold must
    follow it there, i.e. the fix widens nothing."""
    lib = tmp_path / "sc__tt.lib"
    lib.write_text("library(t){ cell (\"AND2\") {} }\n")
    project = _scan_project(tmp_path, with_chain=False)
    _v, doc, _n = _emit(project, _pdk(str(lib), str(tmp_path / "c.lef")),
                        monkeypatch, tmp_path / "out.json")
    assert Path(doc["gold"]).name == f"{TOP}_synth.v"
    assert doc["gold_kind"] == "synth"


# ---------------------------------------------------------------------------
# (c) STUBS — only for cells the Liberty genuinely does not model
#
# MUTATION THESE CATCH: restore `Path(pdk.liberty).read_text(...)` (host-only)
# in `_synthesize_physical_cell_stubs`.
# ---------------------------------------------------------------------------

def _stub_inputs(tmp_path: Path):
    lef = tmp_path / "cells.lef"
    lef.write_text(
        "MACRO sc__nand2_1\n  PIN A END A\n  PIN B END B\n  PIN Y END Y\n"
        "END sc__nand2_1\n"
        "MACRO sc__fill_1\n  PIN VPWR END VPWR\n END sc__fill_1\n")
    gate = tmp_path / "routed.v"
    gate.write_text(
        f"module {TOP}(a);\n input a;\n sc__nand2_1 u0 (.A(a), .B(a), .Y(w));\n"
        f" sc__fill_1 f0 ();\nendmodule\n")
    return lef, gate


def test_stubs_cover_only_the_cells_the_liberty_does_not_model(tmp_path,
                                                               monkeypatch):
    """The Liberty is readable ONLY inside the container (the real deployment).
    A stub for a cell the Liberty models would swap a functional model for an
    empty box in the very proof that needs the function."""
    lef, gate = _stub_inputs(tmp_path)
    liberty = "/foss/pdks/testpdk/libs.ref/sc/lib/sc__tt.lib"  # host: absent
    monkeypatch.setattr(
        R, "_container_file_text",
        lambda c, p: 'library(t){ cell ("sc__nand2_1") { } }\n'
        if p == liberty else None)
    out = tmp_path / "outdir"
    stub = R._synthesize_physical_cell_stubs(
        _pdk(liberty, str(lef)), TOP, gate, "somecontainer", out)
    assert stub, "the physical-only cell still needs a stub"
    text = Path(stub).read_text()
    assert "module sc__fill_1" in text, "fill has no Liberty model — stub it"
    assert "sc__nand2_1" not in text, (
        "the Liberty models nand2; stubbing it replaces its FUNCTION with an "
        "empty blackbox and the equivalence proof stops proving anything")


def test_no_stub_is_written_when_the_liberty_cannot_be_read(tmp_path,
                                                            monkeypatch):
    """Unknown which cells are modelled -> stub NOTHING. A genuinely undefined
    cell then aborts yosys and the gate refuses, which is honest; stubbing
    everything would have been a silent false pass."""
    lef, gate = _stub_inputs(tmp_path)
    monkeypatch.setattr(R, "_container_file_text", lambda c, p: None)
    stub = R._synthesize_physical_cell_stubs(
        _pdk("/nowhere/sc__tt.lib", str(lef)), TOP, gate, "somecontainer",
        tmp_path / "outdir")
    assert stub is None


# ---------------------------------------------------------------------------
# (d) THE CHECK MUST STILL REFUSE WHEN IT GENUINELY CANNOT RUN
# ---------------------------------------------------------------------------

def test_missing_routed_netlist_is_an_honest_skip_never_a_pass(tmp_path,
                                                               stub_container,
                                                               monkeypatch):
    lib = tmp_path / "sc__tt.lib"
    lib.write_text("library(t){ cell (\"AND2\") {} }\n")
    project = _scan_project(tmp_path, with_chain=True)
    (R._pl.pnr_dir(project) / f"{TOP}_pnr.v").unlink()
    verdict, doc, _n = _emit(project, _pdk(str(lib), str(tmp_path / "c.lef")),
                             monkeypatch, tmp_path / "out.json")
    assert verdict == "SKIP" and doc["skipped"] is True
    assert doc.get("skip_reason")
    assert LEC.evaluate_report(doc)["result"] == "SKIP"


def test_unreadable_liberty_refuses_instead_of_passing(tmp_path,
                                                       stub_container,
                                                       monkeypatch):
    """A liberty that is not there is an INPUT defect: the emit must keep the
    SOUND recipe, yosys must fail, and the artefact must carry RUN_ERROR."""
    stub_container.rc = 1
    project = _scan_project(tmp_path, with_chain=True)
    verdict, doc, notes = _emit(
        project, _pdk(str(tmp_path / "absent.lib"), str(tmp_path / "c.lef")),
        monkeypatch, tmp_path / "out.json")
    assert verdict == LEC.V_RUN_ERROR
    assert doc["equivalent"] is False and doc["proven_points"] is None
    assert doc["lec_recipe"] == "functional", (
        "a missing liberty must NOT buy the unsound -lib compare")
    assert LEC.evaluate_report(doc)["result"] == "FAIL"


# ---------------------------------------------------------------------------
# (e) THE ANTI-VACUITY LINE — a run that compares nothing is not a pass
# ---------------------------------------------------------------------------

def test_a_clean_run_that_compared_nothing_is_not_a_pass():
    doc = {"verdict": LEC.V_PASS, "total_points": 0, "proven_points": 0,
           "unproven_points": 0, "equivalent": True, "skipped": False}
    assert LEC.evaluate_report(doc)["result"] == "FAIL"


def test_measured_spm_numbers_pass_clean_and_fail_when_mutated():
    """The two ends actually measured on the spm run with the fixed recipe:
    455/455 proven on the routed netlist, and 451/454 with ONE cell function
    swapped in a copy of it."""
    clean = {"verdict": LEC.V_PASS, "total_points": 455, "proven_points": 455,
             "unproven_points": 0, "equivalent": True, "skipped": False}
    assert LEC.evaluate_report(clean)["result"] == "PASS"
    mutated = {"verdict": LEC.V_UNPROVEN, "total_points": 454,
               "proven_points": 451, "unproven_points": 3,
               "equivalent": False, "skipped": False}
    assert LEC.evaluate_report(mutated)["result"] == "FAIL"
