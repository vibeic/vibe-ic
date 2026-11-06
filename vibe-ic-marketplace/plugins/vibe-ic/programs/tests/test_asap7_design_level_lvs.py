"""#182 — DESIGN-level ASAP7 device-LVS.

Two dimensions, both container-free (no `pya`):
  1. The golden-expander (`asap7_finfet_lvs.build_golden_netlist` /
     `_resolve_cdl_paths`) — expands a gate netlist into a device-level golden by
     substituting each std-cell instance's CDL .SUBCKT. Pure text, unit-testable.
  2. The `step_lvs` dispatch — when asap7 has a device_lvs_program AND a routed
     design GDS + gate netlist are present, it must RUN the design-level LVS and
     return a REAL PASS(match)/FAIL(mismatch or power short); with no routed design
     it WAIVEs (library-only). The in-container extract+compare is mocked at
     `_docker_exec` (the actual KLayout run is verified separately in vibeic-eda).
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))

import asap7_finfet_lvs as A            # noqa: E402


# ------------------------------------------------------------ golden-expander unit
def test_build_golden_expands_each_instance(tmp_path):
    cdl = tmp_path / "cells.cdl"
    cdl.write_text(
        ".SUBCKT INVX A VDD VSS Y\n"
        "MM0 Y A VSS VSS nmos_rvt w=81.0n l=20n nfin=3\n"
        "MM1 Y A VDD VDD pmos_rvt w=81.0n l=20n nfin=3\n"
        ".ENDS\n"
        ".SUBCKT NAND2 A B VDD VSS Y\n"
        "MM0 net A VSS VSS nmos_rvt w=54.0n l=20n nfin=2\n"
        "MM1 Y B net VSS nmos_rvt w=54.0n l=20n nfin=2\n"
        "MM2 Y A VDD VDD pmos_rvt w=54.0n l=20n nfin=2\n"
        ".ENDS\n")
    gate = tmp_path / "top.v"
    gate.write_text(
        "module top(input a, input b, output y);\n"
        " wire w1;\n"
        " INVX g0 (.A(a), .Y(w1));\n"
        " NAND2 g1 (.A(w1), .B(b), .Y(y));\n"
        "endmodule\n")
    out = tmp_path / "golden.spice"
    A.build_golden_netlist(str(gate), [str(cdl)], str(out))
    txt = out.read_text()
    # top emitted as a subckt with the design I/O ports (supply VDD/VSS globalized)
    assert ".SUBCKT top" in txt
    # every std-cell instance expanded into an X-card referencing its CDL subckt
    assert "Xg0" in txt and "INVX" in txt
    assert "Xg1" in txt and "NAND2" in txt
    # the device-bearing CDL is referenced (inlined by the comparer's reader)
    assert ".include" in txt.lower()


def test_build_golden_concatenates_multiple_cdl_flavors(tmp_path):
    c1 = tmp_path / "r.cdl"
    c1.write_text(".SUBCKT INVX_R A VDD VSS Y\n"
                  "MM0 Y A VSS VSS nmos_rvt w=81n l=20n\n.ENDS\n")
    c2 = tmp_path / "l.cdl"
    c2.write_text(".SUBCKT BUFX_L A VDD VSS Y\n"
                  "MM0 Y A VSS VSS nmos_rvt w=81n l=20n\n.ENDS\n")
    gate = tmp_path / "top.v"
    gate.write_text("module top(input a, output y);\n"
                    " INVX_R g0 (.A(a), .Y(y));\n"
                    "endmodule\n")
    out = tmp_path / "g.spice"
    A.build_golden_netlist(str(gate), [str(c1), str(c2)], str(out))
    concat = Path(str(out) + ".cells.cdl")
    assert concat.is_file()
    cc = concat.read_text()
    assert "INVX_R" in cc and "BUFX_L" in cc      # both flavors concatenated


def test_resolve_cdl_paths(tmp_path):
    f = tmp_path / "x.cdl"; f.write_text("* cdl\n")
    assert A._resolve_cdl_paths(str(f), None) == [str(f)]
    d = tmp_path / "cdldir"; d.mkdir()
    (d / "r.cdl").write_text("x"); (d / "l.cdl").write_text("x")
    (d / "readme.txt").write_text("not a cdl")
    got = A._resolve_cdl_paths(None, str(d))
    assert got == sorted([str(d / "l.cdl"), str(d / "r.cdl")])  # only *.cdl, sorted
    assert A._resolve_cdl_paths(None, None) == []               # nothing supplied


# ------------------------------------------------------------ step_lvs dispatch
_ASAP7_REG = {
    "name": "asap7",
    "container_path": "/foss/pdks/asap7",
    "device_lvs_program": "asap7_finfet_lvs.py",
    "cdl_netlist": "libs.tech/cdl/asap7sc7p5t_28_R.cdl",
    "klayout_lvs_tech": "libs.tech/klayout/lvs/asap7.lyt",
    "device_lvs_verified": {"compared": 208, "match": 159, "proven_negative": True},
}
