#!/usr/bin/env python3
"""Tests for floorplan_pdn_check.py — Step 15 (Floorplan + PDN) substance gate.

Pins the anti-fabrication contract: the checker parses the REAL OpenROAD
floorplan.def + pnr.tcl/log and verifies substance (non-degenerate
DIEAREA, >=1 ROW, >=1 COMPONENT, measured-utilization in (0,100]%, PDN
strap evidence). It must:
  * PASS a substantively-good floorplan,
  * FAIL the real backend failure this guards (no PG straps — a bare
    pdn.done marker is not strap evidence),
  * FAIL honestly on absent / empty / garbage floorplan.def,
  * never fabricate a utilization (falls back to COMPONENTS>0 when no log).
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "floorplan_pdn_check.py"

_spec = importlib.util.spec_from_file_location("floorplan_pdn_check", _PROG)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


# ----------------------------------------------------------------------
# fixture builders
# ----------------------------------------------------------------------
def _pnr_dir(project: Path) -> Path:
    d = project / "phase3" / "stage3" / "pnr"
    d.mkdir(parents=True, exist_ok=True)
    return d


_GOOD_FLOORPLAN = """\
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN chip_top ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 200000 200000 ) ;
ROW ROW_0 unithd 10120 10880 N DO 369 BY 1 STEP 460 0 ;
ROW ROW_1 unithd 10120 13600 FS DO 369 BY 1 STEP 460 0 ;
ROW ROW_2 unithd 10120 16320 N DO 369 BY 1 STEP 460 0 ;
COMPONENTS 3 ;
    - _0459_ sky130_fd_sc_hd__clkinv_1 ;
    - _0460_ sky130_fd_sc_hd__nand2_1 ;
    - _0461_ sky130_fd_sc_hd__dfxtp_1 ;
END COMPONENTS
END DESIGN
"""

_GOOD_PNR_TCL = """\
read_lef tech.lef
read_def floorplan.def
set_voltage_domain -name CORE -power VPWR -ground VGND
define_pdn_grid -name grid -voltage_domains CORE
add_pdn_stripe -grid grid -layer met1 -width 0.48 -pitch 5.44 -offset 0 -followpins
add_pdn_stripe -grid grid -layer met4 -width 1.6 -pitch 40.0 -offset 8.0
add_pdn_connect -grid grid -layers {met1 met4}
pdngen
"""

# A real OpenROAD log fragment carrying a measured utilization. The
# checker reads this value verbatim and validates the (0,100]% bound — it
# does NOT invent the number.
_GOOD_LOG = """\
[INFO IFP-0102] Core area:                        28624.954 um^2
[INFO IFP-0104] Effective utilization:                0.181
[INFO GPL-0019] Utilization:                    20.499 %
"""


def _write(d: Path, name: str, text: str):
    (d / name).write_text(text)


def _run(project: Path):
    out_json = project / "report.json"
    rc = mod.main([str(project), "--json", str(out_json)])
    report = json.loads(out_json.read_text()) if out_json.is_file() else None
    return rc, report


def _rules(report):
    return {f["rule"] for f in report["findings"]}


# ----------------------------------------------------------------------
# PASS — good substance (real-shaped artefacts)
# ----------------------------------------------------------------------
def test_pass_good_floorplan_with_pdn_tcl_and_log(tmp_path):
    d = _pnr_dir(tmp_path)
    _write(d, "floorplan.def", _GOOD_FLOORPLAN)
    _write(d, "pnr.tcl", _GOOD_PNR_TCL)
    _write(d, "openroad.log", _GOOD_LOG)
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "PASS"
    assert rep["die_area_units"] == 200000 * 200000
    assert rep["n_rows"] == 3
    assert rep["n_components"] == 3
    # GPL-0019 percent is preferred over IFP fraction.
    assert rep["utilization_pct"] == pytest.approx(20.499)
    assert "PDN_STRAPS_OK" in _rules(rep)
    assert "UTILIZATION_OK" in _rules(rep)


def test_pass_pdn_evidence_from_specialnets_def(tmp_path):
    """No pnr.tcl PDN commands, but a later DEF carries PG SPECIALNETS."""
    d = _pnr_dir(tmp_path)
    _write(d, "floorplan.def", _GOOD_FLOORPLAN)
    # pnr.tcl WITHOUT any pdn command:
    _write(d, "pnr.tcl", "read_lef tech.lef\nread_def floorplan.def\n")
    _write(d, "routed.def",
           "VERSION 5.8 ;\nDESIGN chip_top ;\n"
           "SPECIALNETS 2 ;\n"
           "    - VGND ( _1059_ VNB ) + USE GROUND ;\n"
           "    - VPWR ( _1059_ VPB ) + USE POWER ;\n"
           "END SPECIALNETS\nEND DESIGN\n")
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "PASS"
    assert "PDN_STRAPS_OK" in _rules(rep)
    assert "SPECIALNETS" in rep["pdn_evidence"]


def test_pass_util_not_derivable_falls_back_to_components(tmp_path):
    """No log utilization → checker must NOT fabricate one; falls back to
    COMPONENTS>0 and still PASSes a good floorplan."""
    d = _pnr_dir(tmp_path)
    _write(d, "floorplan.def", _GOOD_FLOORPLAN)
    _write(d, "pnr.tcl", _GOOD_PNR_TCL)
    # no openroad.log
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "PASS"
    assert rep["utilization_pct"] is None
    assert "UTILIZATION_NOT_DERIVABLE" in _rules(rep)


# ----------------------------------------------------------------------
# FAIL — the real backend failure this gate guards
# ----------------------------------------------------------------------
def test_fail_no_pdn_straps_bare_done_marker(tmp_path):
    """The real failure the old files_exist gate masked: floorplan.def +
    pdn.done both exist, so file-presence 'passed', but there is NO actual
    power grid (no add_pdn_stripe, no SPECIALNETS). Must FAIL."""
    d = _pnr_dir(tmp_path)
    _write(d, "floorplan.def", _GOOD_FLOORPLAN)
    # Older make_tracks+global_route flow: pnr.tcl has no pdngen, and a
    # bare pdn.done marker is dropped to satisfy file presence.
    _write(d, "pnr.tcl", "read_lef tech.lef\nread_def floorplan.def\n"
                         "make_tracks\nglobal_route\n")
    _write(d, "pdn.done", "# PDN inserted by OpenROAD make_tracks\n")
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    assert "NO_PDN_STRAPS" in _rules(rep)


def test_fail_degenerate_diearea(tmp_path):
    """Zero-area DIEAREA — empty floorplan that file-presence would pass."""
    d = _pnr_dir(tmp_path)
    bad = _GOOD_FLOORPLAN.replace(
        "DIEAREA ( 0 0 ) ( 200000 200000 ) ;",
        "DIEAREA ( 0 0 ) ( 0 0 ) ;")
    _write(d, "floorplan.def", bad)
    _write(d, "pnr.tcl", _GOOD_PNR_TCL)
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    assert "DEGENERATE_DIEAREA" in _rules(rep)


def test_fail_no_rows(tmp_path):
    d = _pnr_dir(tmp_path)
    bad = "\n".join(
        ln for ln in _GOOD_FLOORPLAN.splitlines()
        if not ln.startswith("ROW "))
    _write(d, "floorplan.def", bad + "\n")
    _write(d, "pnr.tcl", _GOOD_PNR_TCL)
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    assert "NO_CORE_ROWS" in _rules(rep)


def test_fail_zero_components(tmp_path):
    d = _pnr_dir(tmp_path)
    bad = """\
VERSION 5.8 ;
DESIGN chip_top ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 200000 200000 ) ;
ROW ROW_0 unithd 10120 10880 N DO 369 BY 1 STEP 460 0 ;
COMPONENTS 0 ;
END COMPONENTS
END DESIGN
"""
    _write(d, "floorplan.def", bad)
    _write(d, "pnr.tcl", _GOOD_PNR_TCL)
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    assert "NO_COMPONENTS" in _rules(rep)


def test_fail_absurd_utilization(tmp_path):
    """Log reports >100% utilization — physically impossible; FAIL."""
    d = _pnr_dir(tmp_path)
    _write(d, "floorplan.def", _GOOD_FLOORPLAN)
    _write(d, "pnr.tcl", _GOOD_PNR_TCL)
    _write(d, "openroad.log",
           "[INFO GPL-0019] Utilization:                   137.400 %\n")
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    assert "ABSURD_UTILIZATION" in _rules(rep)


# ----------------------------------------------------------------------
# Honesty on missing / garbage data — never a vacuous PASS
# ----------------------------------------------------------------------
def test_fail_missing_floorplan_def(tmp_path):
    _pnr_dir(tmp_path)  # dir exists but no floorplan.def
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    assert "FLOORPLAN_DEF_MISSING" in _rules(rep)


def test_fail_empty_floorplan_def(tmp_path):
    d = _pnr_dir(tmp_path)
    _write(d, "floorplan.def", "   \n\n")
    _write(d, "pnr.tcl", _GOOD_PNR_TCL)
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    assert "FLOORPLAN_DEF_UNPARSEABLE" in _rules(rep)


def test_fail_garbage_floorplan_def(tmp_path):
    """Non-DEF garbage — no DIEAREA, no ROW, no COMPONENTS → FAIL, not pass."""
    d = _pnr_dir(tmp_path)
    _write(d, "floorplan.def", "this is not a DEF file at all\nrandom bytes\n")
    _write(d, "pnr.tcl", _GOOD_PNR_TCL)
    rc, rep = _run(tmp_path)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    rules = _rules(rep)
    assert "NO_DIEAREA" in rules
    assert "NO_CORE_ROWS" in rules
    assert "NO_COMPONENTS" in rules


def test_skip_project_dir_not_found(tmp_path):
    missing = tmp_path / "does_not_exist"
    rc = mod.main([str(missing)])
    assert rc == 2


def test_waived_when_floorplan_absent_but_waiver_present(tmp_path):
    _pnr_dir(tmp_path)
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waived_steps": [
            {"id": "floorplan_pdn", "ticket": "WAIVE-FP-001",
             "reason": "non-production smoke run, no PnR"}
        ]
    }))
    rc, rep = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "WAIVED"
    assert "STEP_WAIVED" in _rules(rep)
