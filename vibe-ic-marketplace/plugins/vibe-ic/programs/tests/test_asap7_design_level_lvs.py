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
import types
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))

import phase3_one_shot_runner as R      # noqa: E402
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


def _routed_project(tmp_path, top="tiny"):
    proj = tmp_path / "proj"
    (proj / "phase3/stage3/pnr").mkdir(parents=True)
    (proj / "phase2/stage2/synth").mkdir(parents=True)
    (proj / "phase3/stage3/pnr" / f"{top}.gds").write_bytes(b"\x00\x06\x00\x02GDS")
    (proj / "phase3/stage3/pnr" / f"{top}.def").write_text(
        "DESIGN tiny ;\nCOMPONENTS 1 ;\n- i0 INVX ;\nEND COMPONENTS\nEND DESIGN\n")
    (proj / "phase2/stage2/synth" / f"{top}_synth.v").write_text(
        "module tiny(); INVX i0 (); endmodule\n")
    return proj


def _mock_common(monkeypatch, verdict_json):
    monkeypatch.setattr(R, "_pdk_registry_entry",
                        lambda n: _ASAP7_REG if n == "asap7" else None)
    monkeypatch.setattr(R, "_tool_in_path", lambda c, t: True)   # klayout present
    monkeypatch.setattr(R, "_to_container_path", lambda p, c: p)
    monkeypatch.setattr(R, "_docker_exec",
                        lambda container, cmd, **kw: (0, verdict_json, ""))


def test_step_lvs_design_match_returns_pass(tmp_path, monkeypatch):
    proj = _routed_project(tmp_path)
    _mock_common(monkeypatch,
                 'A7_DESIGN_LVS {"top":"tiny","verdict":"MATCH","layout_devices":30,'
                 '"golden_devices":30,"mismatch_msgs":0,"power_shorts":0,'
                 '"power_short_locations":[],"restored_pin_labels":6}')
    pdk = types.SimpleNamespace(name="asap7", calibre_lvs=None)
    res = R.step_lvs(proj, "tiny", pdk, "vibeic-eda", upstream_pnr=None)
    assert res.status == "PASS"
    assert res.extras.get("finding") == "LVS_MATCH"
    assert res.extras.get("lvs_engine") == "asap7_device_klayout"
    assert res.extras.get("layout_devices") == 30
    # verdict artifact persisted PASS
    vj = (proj / "reports/phase3/lvs_verdict.json").read_text()
    assert '"status": "PASS"' in vj and "LVS_MATCH" in vj


def test_step_lvs_design_mismatch_returns_fail(tmp_path, monkeypatch):
    proj = _routed_project(tmp_path)
    _mock_common(monkeypatch,
                 'A7_DESIGN_LVS {"top":"tiny","verdict":"MISMATCH","layout_devices":30,'
                 '"golden_devices":30,"mismatch_msgs":12,"power_shorts":0,'
                 '"power_short_locations":[],"restored_pin_labels":6}')
    pdk = types.SimpleNamespace(name="asap7", calibre_lvs=None)
    res = R.step_lvs(proj, "tiny", pdk, "vibeic-eda", upstream_pnr=None)
    assert res.status == "FAIL"
    assert res.extras.get("finding") == "LVS_MISMATCH"
    assert res.extras.get("mismatch_msgs") == 12


def test_step_lvs_design_power_short_returns_fail(tmp_path, monkeypatch):
    proj = _routed_project(tmp_path)
    _mock_common(monkeypatch,
                 'A7_DESIGN_LVS {"top":"tiny","verdict":"MISMATCH","layout_devices":19,'
                 '"golden_devices":30,"mismatch_msgs":5,"power_shorts":1,'
                 '"power_short_locations":[{"net":"VDD","vdd_at":[1,1],"vss_at":[1,0.5]}],'
                 '"restored_pin_labels":6}')
    pdk = types.SimpleNamespace(name="asap7", calibre_lvs=None)
    res = R.step_lvs(proj, "tiny", pdk, "vibeic-eda", upstream_pnr=None)
    assert res.status == "FAIL"
    assert res.extras.get("finding") == "LVS_POWER_SHORT"
    assert res.extras.get("power_shorts") == 1


def test_step_lvs_no_verdict_marker_returns_fail(tmp_path, monkeypatch):
    # a crashed / silent in-container run (no A7_DESIGN_LVS marker) must FAIL, never
    # be swallowed as clean.
    proj = _routed_project(tmp_path)
    _mock_common(monkeypatch, "some noise but no marker\n")
    pdk = types.SimpleNamespace(name="asap7", calibre_lvs=None)
    res = R.step_lvs(proj, "tiny", pdk, "vibeic-eda", upstream_pnr=None)
    assert res.status == "FAIL"
    assert res.extras.get("finding") == "LVS_DESIGN_NO_VERDICT"


def test_step_lvs_library_only_waives_when_no_routed_design(tmp_path, monkeypatch):
    # no routed GDS + gate netlist -> library-only WAIVE (the v1.4.70 behavior stays
    # as the fallback), NOT the false netgen/magic ENV message.
    monkeypatch.setattr(R, "_pdk_registry_entry",
                        lambda n: _ASAP7_REG if n == "asap7" else None)
    monkeypatch.setattr(R, "_tool_in_path", lambda c, t: True)
    empty = tmp_path / "empty_proj"
    empty.mkdir()
    pdk = types.SimpleNamespace(name="asap7", calibre_lvs=None)
    res = R.step_lvs(empty, "tiny", pdk, "vibeic-eda", upstream_pnr=None)
    assert res.status == "WAIVED"
    assert res.extras.get("finding") == "LVS_DEVICE_LEVEL_AVAILABLE"
    assert "159/208" in res.detail
    assert "NOT an ENV gap" in res.detail


def test_step_lvs_klayout_missing_names_klayout(tmp_path, monkeypatch):
    proj = _routed_project(tmp_path)
    monkeypatch.setattr(R, "_pdk_registry_entry",
                        lambda n: _ASAP7_REG if n == "asap7" else None)
    monkeypatch.setattr(R, "_tool_in_path", lambda c, t: False)   # klayout absent
    pdk = types.SimpleNamespace(name="asap7", calibre_lvs=None)
    res = R.step_lvs(proj, "tiny", pdk, "vibeic-eda", upstream_pnr=None)
    assert res.status == "ENV_UNAVAILABLE"
    assert res.extras.get("missing_tool") == "klayout"
