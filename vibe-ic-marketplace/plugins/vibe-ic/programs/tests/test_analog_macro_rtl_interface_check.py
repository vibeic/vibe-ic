#!/usr/bin/env python3
"""The digital side of an analog macro's interface, which nothing compared.

`analog_hardmacro_pinname_consistency_check` asserts LEF == macro `.v` ==
`spec.json` — all three on the ANALOG side, and it passes. Nothing compared
those pins against the module the DIGITAL netlist instantiates, and on the
campaign design the two sides disagree about every block: both RTL blackboxes
declare no ground while the macro carries `vss` as a supply pin; one block's
supply is `vin` on one side and `vdd` on the other; and the modulator
disagrees about its FUNCTION (the RTL instantiates a clocked 1-bit modulator,
the analog block implements the forward path only). OpenROAD reports it as
STA-0201 warnings, and only after A8 has cleared ORD-2013.

chip/PDK-AGNOSTIC.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import analog_macro_rtl_interface_check as M  # noqa: E402


def test_module_ports_reads_the_ansi_header():
    v = ("module blk (\n"
         "    input  wire vin,   // a comment\n"
         "    inout  wire vdd,\n"
         "    output wire vout\n"
         ");\nendmodule\n")
    assert M.module_ports(v, "blk") == ["vin", "vdd", "vout"]
    assert M.module_ports(v, "other") is None


def test_module_ports_reads_the_bare_list_a_synth_writer_emits():
    v = "module blk(a, b, c);\n  input a;\n  output c;\nendmodule\n"
    assert M.module_ports(v, "blk") == ["a", "b", "c"]


def test_module_ports_survives_escaped_names_and_buses():
    v = "module \\blk (\\a[0] , b );\nendmodule\n"
    assert M.module_ports(v, "blk") == ["a", "b"]


def test_lef_pins_and_pg_pins():
    lef = ("MACRO blk\n  PIN vdd\n    USE POWER ;\n    PORT\n    END\n"
           "  END vdd\n  PIN sig\n    DIRECTION INOUT ;\n    PORT\n    END\n"
           "  END sig\nEND blk\n")
    allp, pg = M.lef_pins(lef)
    assert sorted(allp) == ["sig", "vdd"]
    assert pg == ["vdd"]


def test_compare_reports_both_directions_and_singles_out_the_rails():
    d = M.compare(["vdd", "vss", "vin", "vout"], ["vin", "vout", "clk"],
                  ["vdd", "vss"])
    assert d["missing_in_rtl"] == ["vdd", "vss"]
    assert d["extra_in_rtl"] == ["clk"]
    # a supply the digital top never connects is the one case with no
    # legitimate reading — it floats in silicon whatever either side meant.
    assert d["rails_missing_in_rtl"] == ["vdd", "vss"]


def test_agreement_is_reported_as_agreement():
    d = M.compare(["a", "b"], ["b", "a"], [])
    assert d["missing_in_rtl"] == [] and d["extra_in_rtl"] == []


def _project(tmp_path: Path, rtl: str, ports, rails) -> Path:
    p = tmp_path / "proj"
    b = p / "phase3" / "analog" / "blk"
    b.mkdir(parents=True)
    (b / "topology.json").write_text(json.dumps(
        {"ports": ports, "rails": rails}))
    (p / "phase3" / "analog" / "analog_block_list.json").write_text(
        json.dumps({"blocks": ["blk"]}))
    r = p / "phase2" / "stage1" / "rtl"
    r.mkdir(parents=True)
    (r / "top.v").write_text(rtl)
    return p


def test_end_to_end_disagreement_is_a_refusal(tmp_path: Path):
    p = _project(tmp_path, "module blk (vin, vout);\nendmodule\n",
                 ["vdd", "vss", "vin", "vout"],
                 {"vdd": "vdd", "vss": "vss"})
    r = M.check_block(p, "blk")
    assert r["compared"] and not r["agree"]
    assert r["rails_missing_in_rtl"] == ["vdd", "vss"]
    assert M.main([str(p)]) == 1


def test_end_to_end_agreement_passes(tmp_path: Path):
    p = _project(tmp_path, "module blk (vdd, vss, vin, vout);\nendmodule\n",
                 ["vdd", "vss", "vin", "vout"],
                 {"vdd": "vdd", "vss": "vss"})
    assert M.check_block(p, "blk")["agree"]
    assert M.main([str(p)]) == 0


def test_a_block_with_no_rtl_module_is_skipped_not_passed(tmp_path: Path):
    p = _project(tmp_path, "module something_else (a);\nendmodule\n",
                 ["vdd", "vin"], {"vdd": "vdd"})
    r = M.check_block(p, "blk")
    assert r["compared"] is False
    # nothing was compared, so the run is VACUOUS — never a PASS
    assert M.main([str(p)]) == 2
