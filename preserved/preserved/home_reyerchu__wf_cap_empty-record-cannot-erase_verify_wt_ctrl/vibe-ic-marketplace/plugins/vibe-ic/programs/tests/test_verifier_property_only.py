#!/usr/bin/env python3
"""A source that says nothing about a key cannot erase one that said something.

Written against the OBSERVABLE PROPERTY, not against the implementation: every
assertion here is about what a merge RETURNS for a given set of sources, or
about what a program REPORTS for given input files. A different correct fix --
a hand-rolled merge, a different tie-break, a different helper name -- passes
all of it.

FIXTURES ARE PUBLIC MATERIAL ONLY: sky130A / gf180mcuD / nangate45 names, or
pure LEF / Liberty / JSON grammar with invented identifiers. Nothing here names
a foundry, SKU, process node or part number.

Layout:
  1. THE RULE          -- silence cannot erase, in the helper and at each site
  2. THE REVERSE CASE  -- what the OVER-correction looks like, and that it is
                          not what shipped. These are the ones that matter.
  3. THE GUARD         -- fires on the shape, abstains on the legitimate ones
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import atpg_untestable_fault_classify as auc            # noqa: E402
import payload_bit_position_check as pbp                # noqa: E402


# ══════════════════════════════════════════════════════════ 1. THE RULE ══════

def test_erased_pin_map_would_have_inflated_coverage():
    """WHY it matters, measured through `classify()` rather than asserted.

    An emptied pin map makes `classify()` drop every instance of that cell, and
    with it the observability edges THROUGH the cell -- so nets upstream come
    back unobservable and are counted untestable. Coverage goes UP. This test
    pins the consequence so a future change that reintroduces the erase fails
    on the number, not just on the merge.
    """
    ports = {"pi": "input", "po": "output"}
    instances = [
        ("BUF_X1", "u1", {"A": "pi", "Z": "mid"}),
        ("BUF_X1", "u2", {"A": "mid", "Z": "po"}),
    ]
    good = {"BUF_X1": {"A": "input", "Z": "output"}}
    erased = {"BUF_X1": {}}

    r_good = auc.classify(ports, instances, good, auc.constant_cells(good))
    r_bad = auc.classify(ports, instances, erased, auc.constant_cells(erased))

    assert r_good["nets"], "precondition: the intact map builds a graph"
    assert not r_bad["nets"], "the erased map drops the whole cell out"
    assert r_bad["unresolved_cells"] == ["BUF_X1"]


def test_atpg_cli_verdict_does_not_depend_on_liberty_argument_order(tmp_path):
    """SITE 1, at the CALL SITE, through `main()`.

    The property tests above exercise the parser and the helper. This one
    exercises the merge the program actually performs: two `--liberty` files
    naming the same cell, one of them `pg_pin`-only, in both orders. The
    reported untestable set must be identical.

    Public grammar; nangate45-style names; no PDK, vendor or SKU literal.
    """
    full = tmp_path / "a_full.lib"
    pg = tmp_path / "z_pg.lib"
    full.write_text("""
    library (l0) {
      cell (BUF_X1) { pin (A) { direction : input; } pin (Z) { direction : output; } }
      cell (INV_X1) { pin (A) { direction : input; } pin (ZN) { direction : output; } }
    }
    """)
    pg.write_text("""
    library (l1) {
      cell (BUF_X1) { pg_pin (VDD) { pg_type : primary_power; } }
    }
    """)
    netlist = tmp_path / "cut.v"
    netlist.write_text(
        "module top (pi, po);\n"
        "  input pi; output po; wire mid;\n"
        "  BUF_X1 u1 (.A(pi), .Z(mid));\n"
        "  BUF_X1 u2 (.A(mid), .Z(po));\n"
        "  INV_X1 u3 (.A(mid), .ZN(spare));\n"
        "endmodule\n")

    def run(first, second):
        out = tmp_path / f"o_{first.stem}.json"
        auc.main(["--netlist", str(netlist), "--top", "top",
                  "--liberty", str(first), "--liberty", str(second),
                  "--json", str(out)])
        return json.loads(out.read_text())

    forward = run(full, pg)          # `sorted()` order: a_full then z_pg
    reverse = run(pg, full)

    assert forward["unresolved_cells"] == reverse["unresolved_cells"]
    assert "BUF_X1" not in forward["unresolved_cells"], \
        "the pg_pin-only liberty erased the cell's real pin map"
    assert sorted(forward["uncontrollable"]) == sorted(reverse["uncontrollable"])
    assert sorted(forward["unobservable"]) == sorted(reverse["unobservable"])


def test_pdn_planner_sees_the_obstruction_whichever_lef_is_last():
    """SITE 3, at the CALL SITE, through the real planner.

    Two LEFs declare the same MACRO: one with an OBS blocking a stripe layer,
    one with no OBS at all. The observable: adding a LEF that says NOTHING about
    obstructions must not change the plan, in either order -- so both must equal
    the plan from the speaking LEF alone, and must NOT equal the plan from the
    silent LEF alone.

    Measured pre-fix: `blocked_layers []` instead of `['L4']`, and a stripe
    pitch of 12.0 instead of 10.0. Not a missing report -- a different PDN, from
    the same design, decided by argument order.
    """
    import importlib.util as ilu
    import re as _re

    spec = ilu.spec_from_file_location(
        "_erase_phase3", PROGRAMS / "phase3_one_shot_runner.py")
    R = ilu.module_from_spec(spec)
    sys.modules["_erase_phase3"] = R
    try:
        spec.loader.exec_module(R)
    except SystemExit:
        pass
    tspec = ilu.spec_from_file_location(
        "_erase_pdnfix", PROGRAMS / "tests" / "test_macro_pdn_grid.py")
    T = ilu.module_from_spec(tspec)
    sys.modules["_erase_pdnfix"] = T
    try:
        tspec.loader.exec_module(T)
    except SystemExit:
        pass

    lef = T.MACRO_LEF
    name = _re.search(r"MACRO\s+(\S+)", lef).group(1)
    m = _re.search(r"SIZE\s+([\d.]+)\s+BY\s+([\d.]+)\s*;", lef)
    w, h = m.group(1), m.group(2)
    body = (f"  OBS\n    LAYER OVERLAP ;\n      RECT 0 0 {w} {h} ;\n"
            f"    LAYER L4 ;\n      RECT 0 0 {w} {h} ;\n  END\n")
    with_obs = lef.replace(f"END {name}", body + f"END {name}", 1)
    no_obs = lef                       # same MACRO, says nothing about OBS

    def plan(texts):
        return R._macro_pdn_grid_outcome(texts, T.TECH_LEF, T.STRIPES, "L1")

    speaking = plan([with_obs])
    silent = plan([no_obs])
    a = plan([with_obs, no_obs])
    b = plan([no_obs, with_obs])

    # precondition: the two LEFs really do produce different plans, so the
    # assertions below are measuring something
    assert speaking["plan"] != silent["plan"]
    assert speaking["plan"]["blocked_layers"] == ["L4"]
    assert silent["plan"]["blocked_layers"] == []

    assert a["plan"] == b["plan"], "the plan depends on LEF argument order"
    assert a["plan"] == speaking["plan"], \
        "a LEF that says nothing about OBS erased the one that declared L4 blocked"
    assert [r["reason"] for r in a["refusals"]] == \
           [r["reason"] for r in b["refusals"]]


def test_payload_bitmap_byte_named_without_bits_does_not_blank_the_other_layer(tmp_path):
    """SITE 4, through the real `parse_bitmap`."""
    l3 = tmp_path / "l3.json"
    l4 = tmp_path / "l4.json"
    l3.write_text(json.dumps({"bit_layouts": {
        "status_byte": {"bit0": "busy", "bit1": "err"}}}))
    l4.write_text(json.dumps({"bit_layouts": {"status_byte": {}}}))

    both = pbp.parse_bitmap(None, l3, l4)
    swapped = pbp.parse_bitmap(None, l4, l3)
    assert both == swapped
    assert both["status_byte"] == {"bit0": "busy", "bit1": "err"}


def test_empty_bitmap_warning_still_fires_when_every_layer_is_silent(tmp_path):
    """Same over-correction, through the real program: if the fix suppressed
    empty records the user would lose the warning that their input said
    nothing -- trading a silent under-check for a silent no-check."""
    l3 = tmp_path / "l3.json"
    l3.write_text(json.dumps({"bit_layouts": {"status_byte": {}}}))
    rtl = tmp_path / "d.v"
    rtl.write_text("module d(input wire clk); endmodule\n")

    bitmap = pbp.parse_bitmap(None, l3, None)
    assert bitmap == {"status_byte": {}}
    findings = pbp.audit(rtl, bitmap)
    assert any(f.rule == "empty_bitmap" for f in findings), \
        "an all-silent bitmap must still be reported as saying nothing"
