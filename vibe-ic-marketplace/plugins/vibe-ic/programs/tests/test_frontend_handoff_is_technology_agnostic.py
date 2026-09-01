#!/usr/bin/env python3
"""The pre-PnR handoff gate could not see a third PDK's netlist, mapped or not.

MEASURED. `_has_gate_netlist`'s predicate was a regex of English gate words
plus two vendors' cell-name prefixes. On an open PDK that is neither, it
answered NO to a correctly technology-mapped netlist (46 standard cells, zero
generic primitives, 1144.85 um^2) AND NO to the unmapped one that preceded it.
The design was told "run synthesis (Step 10)" after it had synthesised, and the
generic netlist it DID have — `$_NAND_`, `$_NOR_`, `$_NOT_`, `$_DFF_P_` and
nothing else — was never named as the problem. The placer named it later, one
master at a time: `ORD-2013 LEF master $_NOT_ not found`.

chip/PDK-AGNOSTIC: the assertions below use a made-up cell prefix on purpose.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import frontend_backend_handoff_check as F  # noqa: E402


GENERIC = """module top(a, y);
  input a;
  output y;
  wire _0_;
  \\$_NOT_  _1_ (.A(a), .Y(_0_));
  \\$_DFF_P_ _2_ (.C(a), .D(_0_), .Q(y));
  blkbox u_m (.p(y));
endmodule
"""

MAPPED = """module top(a, y);
  input a;
  output y;
  wire _0_;
  wibble_inv_1 _1_ (.A(a), .Y(_0_));
  wibble_dff_1 _2_ (.C(a), .D(_0_), .Q(y));
  blkbox u_m (.p(y));
endmodule
"""

HIERARCHY = """module leaf(a, y);
  input a;
  output y;
endmodule
module top(a, y);
  input a;
  output y;
  leaf u_l (.a(a), .y(y));
endmodule
"""


def test_a_mapped_netlist_is_recognised_without_knowing_the_vendor():
    tech, generic = F.netlist_cell_kinds(MAPPED)
    assert generic == set()
    assert "wibble_inv_1" in tech and "wibble_dff_1" in tech


def test_a_generic_netlist_is_named_as_generic():
    tech, generic = F.netlist_cell_kinds(GENERIC)
    assert generic == {"$_NOT_", "$_DFF_P_"}


def test_a_blackbox_alone_does_not_make_a_netlist_gate_level():
    """`blkbox` is instantiated and not defined here, so it looks like a
    technology cell — and on the campaign design the two ANALOG macros made the
    all-generic netlist look gate-level on exactly that reasoning. Any generic
    primitive present disqualifies the file, whatever else it carries."""
    tech, generic = F.netlist_cell_kinds(GENERIC)
    assert "blkbox" in tech and generic


def test_the_designs_own_hierarchy_is_not_a_technology_cell():
    tech, generic = F.netlist_cell_kinds(HIERARCHY)
    assert tech == set() and generic == set()


def _proj(tmp_path: Path, text: str) -> Path:
    import _path_layout as _pl
    p = tmp_path / "proj"
    d = _pl.synth_dir(p)
    d.mkdir(parents=True)
    (d / "netlist.v").write_text(text)
    return p


def test_the_mapped_netlist_is_found_and_the_generic_one_is_refused(
        tmp_path: Path):
    pm = _proj(tmp_path / "m", MAPPED)
    assert [f.name for f in F._has_gate_netlist(pm)] == ["netlist.v"]
    assert F.netlists_carrying_generic_cells(pm) == []

    pg = _proj(tmp_path / "g", GENERIC)
    assert F._has_gate_netlist(pg) == []
    named = F.netlists_carrying_generic_cells(pg)
    assert len(named) == 1 and named[0][1] == {"$_NOT_", "$_DFF_P_"}
