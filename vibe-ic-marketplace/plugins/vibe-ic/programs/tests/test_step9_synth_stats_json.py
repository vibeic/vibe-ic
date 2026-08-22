#!/usr/bin/env python3
"""Step 9 — `phase2/stage2/synth/stats.json` must be producible.

DEFECT (measured on v1.7.36 against ~/campaign_pr427/spm/converge_ihp-sg13g2)
----------------------------------------------------------------------------
`flow/phase1_phase2_phase3.yaml` step 9 declares

    phase2/stage2/synth/area.rpt OR phase2/stage2/synth/stats.json

as a required output. A whole-tree grep found ZERO producers for either path
under `phase2/stage2/synth` — every `area.rpt` producer in the plugin writes
the phase-3 OpenROAD one. After #455 made `required_outputs` ALL-of-N, the real
run reported:

    · [MISSING] Step  9: Synthesis (Yosys → mapped netlist)
        └─ required_outputs missing:
           ['phase2/stage2/synth/area.rpt OR phase2/stage2/synth/stats.json']
           (satisfied: 1/2 ...)

on a project whose synthesis genuinely succeeded — yosys had printed the cell
count AND the chip area into `phase2/stage2/synth/synth.log`, and nothing
persisted them.

These tests pin the parser against the REAL log shapes measured on that run
(both the generic `446 cells` block from design_one_shot_runner's yosys.log and
the liberty-annotated `349 5.84E+03 cells` + `Chip area for module` block from
phase3's synth.log), and pin the anti-fabrication contract.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import _yosys_stat as ys


# Verbatim tails of the two stat blocks on
# ~/campaign_pr427/spm/converge_ihp-sg13g2 (phase2/stage2/synth/*.log).
LIBERTY_LOG = """\
10. Printing statistics.

=== spm ===

        +----------Local Count, excluding submodules.
        |        +-Local Area, excluding submodules.
        |        |
      292        - wires
      385        - wire bits
        7        - public wires
      100        - public wire bits
        5        - ports
       36        - port bits
      349 5.84E+03 cells
        6   54.432   sg13g2_a21oi_1
       31  336.307   sg13g2_a22oi_1
        6   76.205   sg13g2_and3_1
       64 3.14E+03   sg13g2_dfrbpq_1
       26  188.698   sg13g2_nand2_1
       57  413.683   sg13g2_nor2_1
        1    9.072   sg13g2_nor2b_1
       37  335.664   sg13g2_nor3_1
       64  464.486   sg13g2_tiehi
       52   754.79   sg13g2_xnor2_1
        5   72.576   sg13g2_xor2_1

   Chip area for module '\\spm': 5841.196200
     of which used for sequential elements: 3135.283200 (53.68%)

11. Executing Verilog backend.
"""

GENERIC_LOG = """\
=== spm ===

        +----------Local Count, excluding submodules.
        |
      708 wires
      863 wire bits
        9 public wires
      164 public wire bits
        5 ports
       36 port bits
      446 cells
       64   $_DFF_P_
      221   $_NAND_
      127   $_NOR_
       34   $_NOT_

End of script.
"""

LABELLED_LOG = """\
=== top ===

   Number of wires:                 12
   Number of cells:                 87
     sky130_fd_sc_hd__nand2_1       40
     sky130_fd_sc_hd__dfxtp_1       47
"""


# ---------------------------------------------------------------------------
# Parser — pinned against the REAL logs from the reference run
# ---------------------------------------------------------------------------

def test_parses_liberty_annotated_stat_block():
    s = ys.parse_stat_block(LIBERTY_LOG)
    assert s is not None
    assert s["cells"] == 349
    assert s["top_module"] == "spm"
    assert s["chip_area"] == pytest.approx(5841.1962)
    assert s["cell_histogram"]["sg13g2_dfrbpq_1"] == 64
    assert s["cell_histogram"]["sg13g2_xor2_1"] == 5
    # metric rows are NOT cell types
    for metric in ("wires", "ports", "cells"):
        assert metric not in s["cell_histogram"]


def test_parses_bare_generic_stat_block():
    s = ys.parse_stat_block(GENERIC_LOG)
    assert s is not None
    assert s["cells"] == 446
    assert s["top_module"] == "spm"
    assert s["chip_area"] is None
    assert s["cell_histogram"] == {"$_DFF_P_": 64, "$_NAND_": 221,
                                   "$_NOR_": 127, "$_NOT_": 34}


def test_parses_classic_labelled_stat_block():
    s = ys.parse_stat_block(LABELLED_LOG)
    assert s is not None
    assert s["cells"] == 87
    assert s["cells_source"] == "number_of_cells"


def test_takes_the_last_stat_block_when_several_are_printed():
    s = ys.parse_stat_block(GENERIC_LOG + "\n" + LIBERTY_LOG)
    assert s["cells"] == 349
    assert s["chip_area"] == pytest.approx(5841.1962)


# ---------------------------------------------------------------------------
# ANTI-FABRICATION — no stat block means no artefact, never a measured zero
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "",
    None,
    "ERROR: yosys aborted\n",
    # the docker-fallback path can return rc=0 with an empty stdout capture
    "  \n\n",
])
def test_no_stat_block_yields_no_payload(text):
    assert ys.parse_stat_block(text) is None
    assert ys.build_stats_payload(
        text or "", log_rel="l", netlist_rel="n", tool="yosys") is None


def test_a_measured_zero_is_not_the_same_as_no_measurement():
    s = ys.parse_stat_block("=== empty ===\n        0 cells\n")
    assert s is not None and s["cells"] == 0


def test_payload_carries_its_own_provenance():
    p = ys.build_stats_payload(
        LIBERTY_LOG,
        log_rel="phase2/stage2/synth/synth.log",
        netlist_rel="phase2/stage2/synth/spm_synth.v",
        tool="yosys", frontend="read_verilog_v2005", liberty="/pdk/sg13g2.lib")
    assert p["measured_from"] == "phase2/stage2/synth/synth.log"
    assert p["netlist"] == "phase2/stage2/synth/spm_synth.v"
    assert p["tool"] == "yosys"
    assert p["synth_frontend"] == "read_verilog_v2005"
    assert p["liberty"] == "/pdk/sg13g2.lib"
    assert p["cells"] == 349
    # serialisable — this is written verbatim to stats.json
    json.dumps(p)


# ---------------------------------------------------------------------------
# Producers — both synth steps must emit the declared artefact
# ---------------------------------------------------------------------------

def test_emit_writes_the_declared_artefact(tmp_path):
    """Behavioural: the shared emitter both producers call really writes
    phase2/stage2/synth/stats.json, carrying the tool's own numbers."""
    synth = tmp_path / "phase2/stage2/synth"
    written = ys.emit_stats_json(
        synth, LIBERTY_LOG,
        log_rel="phase2/stage2/synth/synth.log",
        netlist_rel="phase2/stage2/synth/netlist.v", tool="yosys")
    assert written == synth / "stats.json"
    on_disk = json.loads(written.read_text())
    assert on_disk["cells"] == 349
    assert on_disk["chip_area"] == pytest.approx(5841.1962)


def test_emit_writes_nothing_when_nothing_was_measured(tmp_path):
    """Anti-fabrication, behaviourally: an empty capture (the docker-fallback
    rc=0 case) must leave NO artefact behind."""
    synth = tmp_path / "phase2/stage2/synth"
    synth.mkdir(parents=True)
    assert ys.emit_stats_json(
        synth, "", log_rel="l", netlist_rel="n", tool="yosys") is None
    assert not (synth / "stats.json").exists()


def _synth_source(func_name: str, module_file: str) -> str:
    import inspect
    import importlib
    mod = importlib.import_module(module_file)
    return inspect.getsource(getattr(mod, func_name))


def test_design_runner_synth_emits_stats_json():
    """Wiring: the phase-2 synth producer must go through the shared emitter.
    (Driving yosys itself needs the container, so the call site is asserted
    structurally; `test_emit_writes_the_declared_artefact` covers behaviour.)"""
    src = _synth_source("step_yosys_synth", "design_one_shot_runner")
    assert "emit_stats_json" in src, (
        "design_one_shot_runner.step_yosys_synth must persist the yosys stat "
        "block it already measures as phase2/stage2/synth/stats.json")


def test_phase3_synth_persists_the_area_figure_it_measured():
    """Same PROPERTY as the phase-2 test above — step 9's declared artefact gets
    written — but deliberately not the same MECHANISM.

    This originally asserted `emit_stats_json`, i.e. that phase3 went through
    the same shared emitter as design_one_shot_runner. While this branch was in
    flight, #457 (v1.7.43) landed `synth_area_stats_emit`, which closes the
    phase-3 half of step 9 independently: it lifts the area figure out of the
    synthesis log into `<synth>/area.rpt`, the OTHER alternative step 9's
    required_outputs accepts, and REFUSES to write when the log carries only
    per-module locals rather than guessing. Keeping a second emitter here would
    be duplicate producers for one declaration, so the rebase took #457's.

    The test now asserts the property both satisfy, so neither implementation is
    pinned: whichever emitter phase-3 synth uses, it must persist the figure it
    already measured into one of step 9's declared paths, and must have a
    refuse-rather-than-guess path so an unmeasurable run leaves step 9 honestly
    MISSING instead of gaining a fabricated zero."""
    src = _synth_source("step_synth", "phase3_one_shot_runner")
    assert ("emit_stats_json" in src) or ("emit_for_run" in src), (
        "phase3_one_shot_runner.step_synth must persist the synthesis area/stat "
        "figure it already measures into one of step 9's declared artefacts "
        "(stats.json via _yosys_stat, or area.rpt via synth_area_stats_emit)")
    assert "_area_stats is not None" in src or "if _stats" in src, (
        "the emitter's refusal must be handled: a run whose log carries no "
        "usable figure must leave the artefact absent, not write a guess")


def test_stats_json_satisfies_step9_required_outputs(tmp_path):
    """End-to-end on the declaration: writing the payload at the declared path
    clears step 9's `area.rpt OR stats.json` entry."""
    import yaml
    import flow_compliance_check as fcc

    flow = (Path(__file__).resolve().parents[2]
            / "flow" / "phase1_phase2_phase3.yaml")
    doc = yaml.safe_load(flow.read_text())
    step9 = [s for s in doc["steps"] if str(s["id"]) == "9"][0]
    decl = [o for o in step9["required_outputs"] if "stats.json" in o]
    assert decl, "step 9 no longer declares stats.json — update this test"

    proj = tmp_path / "proj"
    synth = proj / "phase2/stage2/synth"
    synth.mkdir(parents=True)
    (synth / "netlist.v").write_text("module spm(); endmodule\n")

    def missing():
        out = []
        for entry in step9["required_outputs"]:
            if not any(fcc._glob_first(proj, alt.strip())
                       for alt in entry.split(" OR ")):
                out.append(entry)
        return out

    assert decl[0] in missing(), "precondition: stats.json absent"
    payload = ys.build_stats_payload(
        LIBERTY_LOG, log_rel="phase2/stage2/synth/synth.log",
        netlist_rel="phase2/stage2/synth/netlist.v", tool="yosys")
    (synth / "stats.json").write_text(json.dumps(payload, indent=2) + "\n")
    assert missing() == []


# ---------------------------------------------------------------------------
# DIRECTION-1 GUARDS — behaviour that must NOT change
# ---------------------------------------------------------------------------

def test_guard_existing_cell_count_parser_unchanged():
    """`_parse_yosys_stat_cells` (#737) keeps its exact contract — the new
    module is additive, it does not replace it."""
    import design_one_shot_runner as dr
    assert dr._parse_yosys_stat_cells(GENERIC_LOG) == 446
    assert dr._parse_yosys_stat_cells(LABELLED_LOG) == 87
    assert dr._parse_yosys_stat_cells("") is None
    assert dr._parse_yosys_stat_cells("no stat here") is None


def test_guard_step9_gate_legs_unchanged():
    """The netlist + synth_netlist_check + provenance_check legs must stay:
    a stats.json must never become a substitute for them."""
    import yaml
    flow = (Path(__file__).resolve().parents[2]
            / "flow" / "phase1_phase2_phase3.yaml")
    doc = yaml.safe_load(flow.read_text())
    step9 = [s for s in doc["steps"] if str(s["id"]) == "9"][0]
    blob = json.dumps(step9["gate"])
    assert "phase2/stage2/synth/netlist.v" in blob
    assert "synth_netlist_check" in blob
    assert "provenance_check" in blob


def test_guard_phase3_area_rpt_readers_keep_their_source():
    """hid 7's risk note: do NOT redirect the existing readers.
    `utilization_band_check` must keep reading the phase-3 PnR area.rpt and
    `foundry_handoff_pack_gen` must keep parsing synth.log."""
    import inspect
    import utilization_band_check as ubc
    import foundry_handoff_pack_gen as fhpg
    ubc_src = inspect.getsource(ubc)
    assert "phase3/stage3/pnr/area.rpt" in ubc_src
    assert "phase2/stage2/synth/stats.json" not in ubc_src
    assert "synth.log" in inspect.getsource(fhpg)
