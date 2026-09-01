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


# ---------------------------------------------------------------------------
# vibe-ic#2010 — the three hygiene findings on this checker, each pinned by a
# control that FAILS against the v1.15.49 code and passes after.
# ---------------------------------------------------------------------------

def test_a_stale_header_quoted_in_a_comment_does_not_mint_the_port_list():
    """Item 3 (declaration scans strip comments). `_MODULE_RE` is anchored at
    line start and a block comment that quotes a retired header puts `module
    blk (` at a line start too; scanned raw, the FIRST match won and the
    retired list was returned. MEASURED against v1.15.49: ['x', 'y']."""
    v = ("/* the old\n"
         " module blk (x, y);\n"
         " was retired with the forward-path-only topology */\n"
         "module blk (\n"
         "    input  wire vin,\n"
         "    inout  wire vdd,\n"
         "    output wire vout\n"
         ");\nendmodule\n")
    assert M.module_ports(v, "blk") == ["vin", "vdd", "vout"]
    # The `//` form was NOT red on v1.15.49 (measured: ['a', 'b'] — the
    # line-anchored regex never reaches past the `//`); it is asserted so the
    # blanker cannot regress the case that already worked.
    v2 = "// module blk (p, q);\nmodule blk (a, b);\nendmodule\n"
    assert M.module_ports(v2, "blk") == ["a", "b"]


def test_the_json_report_is_written_atomically_and_carries_the_verdict(
        tmp_path: Path):
    """Item 4 (declared reports are written atomically). The `--json`
    destination goes through `_atomic_artefact`, so no temp artefact survives
    and the report names its verdict the way its A8 siblings do."""
    import _atomic_artefact as _aa
    p = _project(tmp_path, "module blk (vdd, vss, vin, vout);\nendmodule\n",
                 ["vdd", "vss", "vin", "vout"],
                 {"vdd": "vdd", "vss": "vss"})
    out = tmp_path / "reports" / "a8_macro_rtl_interface.json"
    out.parent.mkdir(parents=True)
    assert M.main([str(p), "--json", str(out)]) == 0
    doc = json.loads(out.read_text())
    assert doc["verdict"] == "PASS" and doc["rc"] == 0
    assert doc["blocks"][0]["agree"] is True
    assert not [f for f in out.parent.iterdir() if _aa.is_temp_artefact(f)]
    # the vacuous case is typed in the same document
    p2 = _project(tmp_path / "v", "module other (a);\nendmodule\n",
                  ["vdd", "vin"], {"vdd": "vdd"})
    out2 = tmp_path / "v.json"
    assert M.main([str(p2), "--json", str(out2)]) == 2
    assert json.loads(out2.read_text())["verdict"] == "VACUOUS_PASS"


def test_the_vacuous_exit_carries_the_rc_independent_sentinel(tmp_path: Path,
                                                                capsys):
    """`_vacuous_exit.announce_vacuous` on stderr: the disclosure channel the
    flow auditor reads regardless of rc, so this gate is credited in the
    VACUOUS tier and never as a pass over the design."""
    p = _project(tmp_path, "module other (a);\nendmodule\n",
                 ["vdd", "vin"], {"vdd": "vdd"})
    assert M.main([str(p)]) == 2
    assert "VACUOUS_PASS:" in capsys.readouterr().err


def test_the_gate_is_declared_in_the_flows_a8_step():
    """Items 1-2 (checker execution wiring / gates are wired to something).
    v1.15.49 shipped this checker run by nothing but this test file; it is
    now a clause of the A8 gate — the step that produces the LEF it reads —
    so the flow auditor invokes it on every analog run."""
    import yaml
    flow = Path(__file__).resolve().parents[2] / "flow" / "phase1_phase2_phase3.yaml"
    doc = yaml.safe_load(flow.read_text())

    def _find(o):
        if isinstance(o, dict):
            if o.get("id") == "A8":
                return o
            for v in o.values():
                r = _find(v)
                if r:
                    return r
        if isinstance(o, list):
            for v in o:
                r = _find(v)
                if r:
                    return r
        return None

    a8 = _find(doc)
    assert a8 is not None
    clauses = [c.get("program_exit_zero", "") for c in a8["gate"]["all_of"]]
    assert any(c.startswith("analog_macro_rtl_interface_check ") for c in clauses), clauses
    # BLOCKING — declared as `program_exit_zero`, not advisory/optional
    assert not any("advisory" in k or "optional" in k
                   for c in a8["gate"]["all_of"] for k in c
                   if "analog_macro_rtl_interface_check" in str(c[k]))
