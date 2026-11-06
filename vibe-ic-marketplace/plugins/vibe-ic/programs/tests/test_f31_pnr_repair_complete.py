"""F31: step 17's `pnr_timing_repair_completeness_check` judges timing sessions,
not every file that matches `pnr*.tcl`.

Measured on spm (run23, direct) and on the LibreLane 15->20 chain: the gate ran
in directory mode on `phase3/stage3/pnr` and FAILED on two decks that place and
optimise nothing:

  * `pnr_antenna_isolated_retry.tcl` (v1.24.64, #2626): the scoped antenna ECO.
    It restores the routed pre-repair ODB, runs `repair_antennas` and
    `detailed_route -nets <targets>`, and refuses itself if any existing cell
    moved. It FAILed for missing `set_wire_rc` / `repair_design` /
    `repair_timing -setup`.
  * `pnr_cts_head.tcl` (T98, #2697), when placement was ingested from
    LibreLane: `read_def placed.def`, parasitics, a pre-CTS checkpoint. The
    setup chain runs in `pnr_cts_tail.tcl`, which PASSed.

Every deck that placed or optimised carried the chain (pnr.tcl, the rollback /
SDR / adopt tails, the CTS tail). The decks here are emitted by the REAL
producers (`_antenna_isolated_scoped_retry_tcl`, `librelane_cts_hold.head_deck`
/ `tail_deck`), and the gate is the real `main()`.

The negative controls pin that nothing got weaker: a checkpoint deck that
repairs or places without the chain still FAILs, a routing-only deck that
restores nothing is still audited, a directory holding only non-timing decks is
the disclosed-skip tier (rc 2, never PASS), and a deck named on the command line
is always audited.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(PROGRAMS / "tests"))
gate = importlib.import_module("pnr_timing_repair_completeness_check")


def _run(d: Path, tmp_path: Path):
    out = tmp_path / "rep.json"
    rc = gate.main([str(d), "--json", str(out)])
    rep = json.loads(out.read_text()) if out.is_file() else None
    return rc, rep


# ---------------------------------------------------------------- the defect


# ------------------------------------------------- nothing got weaker: controls


@pytest.mark.parametrize("body", [
    # the sha256 silicon-DOA shape, resumed from a checkpoint
    "read_db /p/pnr/ckpt.odb\ncatch {repair_timing -hold}\ndetailed_route\n",
    # a checkpoint session that re-places without any repair
    "read_def /p/pnr/placed.def\ndetailed_placement\nglobal_route\n"
    "detailed_route\n",
    # a deck that BUILDS the design and reads a floorplan DEF, then only routes
    "read_verilog /p/netlist.v\nlink_design top\nread_def /p/floorplan.def\n"
    "global_route\ndetailed_route\n",
    # a checkpoint session that resizes for DRV only
    "read_db /p/pnr/ckpt.odb\nset_wire_rc -layer Metal1\nrepair_design\n"
    "detailed_route\n",
])
def test_a_checkpoint_deck_that_repairs_or_places_is_still_audited(
        tmp_path, body):
    d = tmp_path / "pnr"
    d.mkdir()
    (d / "pnr_eco.tcl").write_text(body)
    rc, rep = _run(d, tmp_path)
    assert rc == 1, rep
    assert rep["script"].endswith("pnr_eco.tcl")
    assert rep.get("not_timing_sessions", []) == []


def test_a_routing_deck_that_restores_nothing_is_still_audited(tmp_path):
    d = tmp_path / "pnr"
    d.mkdir()
    (d / "pnr_route.tcl").write_text("global_route\ndetailed_route\n")
    rc, rep = _run(d, tmp_path)
    assert rc == 1
    assert rep["script"].endswith("pnr_route.tcl")
