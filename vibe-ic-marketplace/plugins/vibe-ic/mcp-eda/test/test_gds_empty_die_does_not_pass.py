#!/usr/bin/env python3
"""eda_gds must not report PASS on a DEF with no components — an empty die.

MEASURED (192.168.1.121, container vibeic-eda, KLayout, sky130A). Single-variable
A/B: the same DEF eda_pnr wrote, with its `COMPONENTS 28 ;` block emptied to
`COMPONENTS 0 ;`. Nothing else was touched — the DIEAREA is identical, so even a
bounding-box check would not separate them.

  control  mcp_pnr.def         -> {"success":true,"cells":456,"lib_cells":446}
  planted  mcp_pnr_NOCOMP.def  -> {"success":true,"cells":447,"lib_cells":446}

  Ground truth, re-read from the two written GDS:
    control  cnt_instances = 28    planted  cnt_instances = 0   <- EMPTY DIE

Both wrote manifest `step:"gds_generation", status:"PASS"` with `cells` present,
so REQUIRED_METRICS.gds_generation = [{key:"cells"}] was SATISFIED by the empty
one. `cells` counts cell DEFINITIONS in the merged layout, 446 of which come from
the PDK library: it is ~98% library and ~2% design, moving only 456->447 between
a real chip and nothing at all. It is a library size, not a design size. And
`MERGE_OK` is printed unconditionally by the MCP's own KLayout script and then
tested for — a self-echoed marker, not a measurement.

The fix counts the placed INSTANCES of the DEF's own top cell, anchored on the
DEF's `DESIGN <name> ;` line. That anchor is exact and deliberately NOT a
heuristic: "the top cell with the most instances" selects the PDK's
sky130_fd_sc_hd__macro_sparecell (7 instances) on the emptied DEF and would
report a plausible non-zero count for an empty die.

  after the fix, measured:
    control  success:true,  top_cell:cnt, top_insts:28, design_cells:10, PASS
    planted  success:FALSE, top_cell:cnt, top_insts:0,  design_cells:1,  FAIL
    pdn      success:true,  top_cell:cnt, top_insts:58, design_cells:13, PASS
"""
import re
from pathlib import Path

MCP_ROOT = Path(__file__).resolve().parents[1]
SRC = (MCP_ROOT / "src" / "index.js").read_text()
METRICS = (MCP_ROOT / "src" / "lib" / "manifest_metrics.mjs").read_text()


def _tool(name: str) -> str:
    """The whole tool body: from its name to the next server.tool( registration."""
    i = SRC.find(f'"{name}"')
    assert i > 0, f"tool {name} not found"
    j = SRC.find("server.tool(", i)
    return SRC[i:j if j > 0 else len(SRC)]


def test_gds_measures_placed_instances_of_the_designs_own_top_cell():
    t = _tool("eda_gds")
    assert "GDS_TOP_INSTS=" in t, "eda_gds does not count placed instances"
    assert "each_inst()" in t
    # anchored on the DEF's DESIGN line, not a most-instances heuristic
    assert "DESIGN" in t and "cell_by_name" in t
    assert "top_cells" not in t, (
        "a top-cell heuristic is back — it selects a PDK library cell with 7 "
        "instances on an emptied DEF and reports a plausible non-zero count"
    )


def test_an_empty_die_is_not_a_success():
    t = _tool("eda_gds")
    assert "const emptyDie = topInsts === 0;" in t
    assert "const gdsOk = cellsMatch != null && mergeOk && instsMeasured && !emptyDie;" in t
    assert "success: gdsOk," in t, "the verdict is not conjoined with the instance count"
    # every derived verdict must move with it, not just the returned boolean
    assert "measured: gdsOk," in t
    assert "wrote: gdsOk ? [output_gds] : []," in t
    assert "exitCode: gdsOk ? 0 : 1," in t
    assert "EMPTY DIE" in t, "the failure does not say what is wrong"


def test_an_unidentifiable_top_cell_is_not_measured_rather_than_bad():
    """Absent must render as neither good nor bad."""
    t = _tool("eda_gds")
    assert "GDS_TOP_CELL_UNKNOWN" in t
    assert "instsMeasured" in t
    assert "NOT_MEASURED" in t
    # top_insts is recorded as null (absent), not as 0 (a measured empty die)
    assert "top_insts: instsMeasured ? topInsts : null," in t


def test_top_insts_is_a_required_metric_for_gds_generation():
    """So an unmeasurable run is INCONCLUSIVE, never PASS."""
    m = re.search(r"gds_generation:\s*\[([^\]]*)\]", METRICS)
    assert m, "gds_generation has no REQUIRED_METRICS entry"
    keys = re.findall(r'key:\s*"(\w+)"', m.group(1))
    assert "top_insts" in keys, (
        f"gds_generation requires {keys} — `cells` alone is ~98% PDK library and "
        f"was satisfied by an empty die"
    )
    assert "cells" in keys, "the existing cells requirement must not be dropped"
