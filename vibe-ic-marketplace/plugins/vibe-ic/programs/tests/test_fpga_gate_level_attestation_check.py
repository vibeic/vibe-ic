#!/usr/bin/env python3
"""Tests for fpga_gate_level_attestation_check.py.

Pins the BENCH-A gate-level-vs-RTL-fallback attestation:
  * gate top instantiated + std-cells present + no RTL submodule leak → PASS
  * RTL submodule names leaked into the map.rpt → FAIL (RTL fallback proof)
  * gate top absent → FAIL
  * map.rpt absent → rc 2
"""
from __future__ import annotations

import json
from pathlib import Path

# programs/ is on sys.path via conftest; import by name so the module is
# registered in sys.modules (required — it defines a @dataclass whose
# default_factory resolution needs the module to be importable by name).
import fpga_gate_level_attestation_check as mod


# A genuine gate-level map.rpt: gate top instantiated, real std-cell names,
# no RTL submodule names.
_GOOD_RPT = """
; Compilation Hierarchy
chip_top_asic:u_chip
  sg13g2_dfrbp_1 reg_q_reg
  sg13g2_nand2_1 u_nand
  DFFQX1 dff_inst
  AOI21 aoi_inst
"""

# RTL-fallback map.rpt: shows main_fsm:/rx_phy: submodule instances.
_FALLBACK_RPT = """
; Compilation Hierarchy
chip_top_asic:u_chip
  main_fsm:u_fsm
  rx_phy:u_rx
  byte_assembler:u_ba
"""

# Gate top never instantiated (Quartus compiled something else entirely).
_NO_GATE_TOP_RPT = """
; Compilation Hierarchy
some_other_top:u_other
  sg13g2_nand2_1 u_nand
"""


def _run(rpt_text: str, tmp_path: Path, gate_top="chip_top_asic"):
    rpt = tmp_path / "de10lite_top.map.rpt"
    rpt.write_text(rpt_text)
    out = tmp_path / "att.json"
    rc = mod.main(["--map-rpt", str(rpt), "--gate-top", gate_top,
                   "--json", str(out)])
    rep = json.loads(out.read_text()) if out.is_file() else None
    return rc, rep


# ----------------------------------------------------------------------
# PASS — genuine gate-level compile
# ----------------------------------------------------------------------
def test_pass_genuine_gate_level(tmp_path):
    rc, rep = _run(_GOOD_RPT, tmp_path)
    assert rc == 0
    assert rep["verdict"] == "PASS"
    assert rep["errors"] == 0


# ----------------------------------------------------------------------
# FAIL — RTL submodule names leaked (RTL fallback)
# ----------------------------------------------------------------------
def test_fail_rtl_submodule_leaked(tmp_path):
    rc, rep = _run(_FALLBACK_RPT, tmp_path)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    rules = {f["rule"] for f in rep["findings"]}
    assert "RTL_SUBMODULE_LEAKED" in rules


# ----------------------------------------------------------------------
# FAIL — gate top not instantiated at all
# ----------------------------------------------------------------------
def test_fail_gate_top_not_instantiated(tmp_path):
    rc, rep = _run(_NO_GATE_TOP_RPT, tmp_path)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    rules = {f["rule"] for f in rep["findings"]}
    assert "GATE_TOP_NOT_INSTANTIATED" in rules


# ----------------------------------------------------------------------
# WARN-only — gate top present, no std-cell evidence is a WARN not ERROR
# ----------------------------------------------------------------------
def test_warn_no_stdcell_still_passes(tmp_path):
    rpt = "chip_top_asic:u_chip\n  yosys_prim foo\n"
    rc, rep = _run(rpt, tmp_path)
    assert rc == 0
    assert rep["verdict"] == "PASS"
    rules = {f["rule"] for f in rep["findings"]}
    assert "NO_STDCELL_EVIDENCE" in rules
    assert rep["warnings"] >= 1


# ----------------------------------------------------------------------
# Edge — map.rpt absent → IO error rc 2
# ----------------------------------------------------------------------
def test_missing_map_rpt(tmp_path):
    rc = mod.main(["--map-rpt", str(tmp_path / "nope.rpt")])
    assert rc == 2
