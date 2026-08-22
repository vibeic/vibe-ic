#!/usr/bin/env python3
"""Tests for analog_netlist_pdk_check.py — SPICE netlist PDK compliance gate."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from _hostpaths import repo_path_opt  # noqa: E402

PROG = Path(__file__).resolve().parent.parent / "analog_netlist_pdk_check.py"

GF180_GOOD_NETLIST = """\
* LDO Regulator — GF180
.include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical

.subckt ldo_regulator vin vout vss
XMP1 vout gate vin vin pfet_03v3 W=20u L=4u
XMN1 gate vref vss vss nfet_03v3 W=20u L=2u
XMN2 n_out vfb vss vss nfet_03v3 W=20u L=2u
.ends
"""

GF180_BAD_BODY_NETLIST = """\
* LDO with wrong PMOS body
.include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical

.subckt ldo_bad vin vout vss
XMP1 vout gate vin 0 pfet_03v3 W=20u L=4u
XMN1 gate vref vss vss nfet_03v3 W=20u L=2u
.ends
"""

NO_INCLUDE_NETLIST = """\
* Missing model include
.subckt osc_bad vdd vss out
XMP1 out in vdd vdd pfet_03v3 W=1u L=1u
XMN1 out in vss vss nfet_03v3 W=0.5u L=1u
.ends
"""

# --- KNOWN_MODELS (UNKNOWN_PDK_MODEL) fixtures ---

# sky130 netlist using ONLY real registry device models — must PASS clean.
SKY130_GOOD_KNOWN_MODELS = """\
* diff pair — sky130, all real device models
.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice tt
.subckt diffpair vip vin vop vss vdd nbias
xm5 ntail nbias vss vss   sky130_fd_pr__nfet_01v8 w=8  l=1
xm1 nd1   vip   ntail vss  sky130_fd_pr__nfet_01v8 w=16 l=0.5
xm3 nd1   nd1   vdd  vdd   sky130_fd_pr__pfet_01v8 w=8  l=0.5
xm6 vop   nd2   vdd  vdd   sky130_fd_pr__pfet_01v8_hvt w=32 l=0.5
.ends
"""

# sky130 netlist with a genuinely-fake (typo'd) device model in-namespace.
# `sky130_fd_pr__nfet_01v9` does NOT exist — must flag UNKNOWN_PDK_MODEL.
SKY130_BAD_UNKNOWN_MODEL = """\
* diff pair — sky130, one typo'd model
.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice tt
.subckt diffpair vip vin vop vss vdd nbias
xm5 ntail nbias vss vss  sky130_fd_pr__nfet_01v8 w=8 l=1
xm1 nd1   vip   ntail vss sky130_fd_pr__nfet_01v9 w=16 l=0.5
.ends
"""

# A netlist that calls a USER-DEFINED subckt (out-of-namespace token).
# Must NOT flag UNKNOWN_PDK_MODEL — only the PDK namespace is validated.
SKY130_USER_SUBCKT_NO_FLAG = """\
* design instantiating a custom subckt + a real PDK device
.lib /foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice tt
.subckt top vin vout vdd vss
xbias nbias vss vss my_custom_bias_block
xm1 nd1 vin vss vss sky130_fd_pr__nfet_01v8 w=16 l=0.5
.ends
"""

# Unknown PDK (no recognized .lib marker) — KNOWN_MODELS must honest-skip,
# never flag a model it cannot validate.
UNKNOWN_PDK_NO_VALIDATE = """\
* netlist with a model include but no recognized PDK marker
.include /opt/my_private_pdk/models.spice
.subckt blk a b c
xm1 a b c c some_private_model w=1 l=1
.ends
"""


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "report.json")],
        capture_output=True, text=True,
    )


def _load_report(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


# -- Test: PASS with correct GF180 netlist --

def test_pass_correct_pdk(tmp_path):
    d = tmp_path / "phase3" / "analog" / "ldo"
    d.mkdir(parents=True)
    (d / "ldo.sp").write_text(GF180_GOOD_NETLIST)
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["files_pass"] == 1


# -- Test: FAIL with wrong PMOS body connection --

def test_fail_wrong_body(tmp_path):
    d = tmp_path / "phase3" / "analog" / "ldo"
    d.mkdir(parents=True)
    (d / "ldo.sp").write_text(GF180_BAD_BODY_NETLIST)
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("PMOS_BODY_TO_VSS" in f["rule"] for f in errors)


# -- Test: FAIL with no model include --

def test_fail_no_model_include(tmp_path):
    d = tmp_path / "phase3" / "analog" / "osc"
    d.mkdir(parents=True)
    (d / "osc.sp").write_text(NO_INCLUDE_NETLIST)
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("NO_MODEL_INCLUDE" in f["rule"] for f in errors)


# -- Test: self-skip when no .sp files --

def test_skip_no_sp(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 2      # #521 — VACUOUS (rc 2): the gate examined nothing.
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True


# -- Test: exit 2 on non-existent directory --

def test_exit2_bad_dir(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nonexistent")],
        capture_output=True, text=True,
    )
    assert r.returncode == 2


# ===================================================================
# KNOWN_MODELS / UNKNOWN_PDK_MODEL validation (registry-driven)
# ===================================================================

# -- PASS: all device models are real sky130 registry devices --

def test_known_models_pass(tmp_path):
    d = tmp_path / "phase3" / "analog" / "diffpair"
    d.mkdir(parents=True)
    (d / "diffpair.sp").write_text(SKY130_GOOD_KNOWN_MODELS)
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["unknown_pdk_model_errors"] == 0
    assert not any(f["rule"] == "UNKNOWN_PDK_MODEL" for f in rpt["findings"])


# -- FAIL: a genuinely-fake in-namespace model token is flagged --

def test_known_models_fail_unknown(tmp_path):
    d = tmp_path / "phase3" / "analog" / "diffpair"
    d.mkdir(parents=True)
    (d / "diffpair.sp").write_text(SKY130_BAD_UNKNOWN_MODEL)
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    unknown = [f for f in errors if f["rule"] == "UNKNOWN_PDK_MODEL"]
    assert len(unknown) == 1
    assert "sky130_fd_pr__nfet_01v9" in unknown[0]["message"]
    assert rpt["summary"]["unknown_pdk_model_errors"] == 1


# -- No false positive on user-defined (out-of-namespace) subckt calls --

def test_known_models_no_flag_user_subckt(tmp_path):
    d = tmp_path / "phase3" / "analog" / "top"
    d.mkdir(parents=True)
    (d / "top.sp").write_text(SKY130_USER_SUBCKT_NO_FLAG)
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert not any(f["rule"] == "UNKNOWN_PDK_MODEL" for f in rpt["findings"])


# -- Missing data: unknown PDK => honest skip of KNOWN_MODELS, no flag --

def test_known_models_unknown_pdk_skips(tmp_path):
    d = tmp_path / "phase3" / "analog" / "blk"
    d.mkdir(parents=True)
    (d / "blk.sp").write_text(UNKNOWN_PDK_NO_VALIDATE)
    r = _run(tmp_path)
    # Model include present + no body error + unknown PDK => no UNKNOWN_PDK_MODEL
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert not any(f["rule"] == "UNKNOWN_PDK_MODEL" for f in rpt["findings"])
    assert rpt["summary"]["unknown_pdk_model_errors"] == 0


# -- GF180 existing good netlist still passes (bare nfet_03v3/pfet_03v3) --

def test_known_models_gf180_bare_pass(tmp_path):
    d = tmp_path / "phase3" / "analog" / "ldo"
    d.mkdir(parents=True)
    (d / "ldo.sp").write_text(GF180_GOOD_NETLIST)
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["unknown_pdk_model_errors"] == 0


# -- MANDATORY corpus sweep: the REAL adc pilot must stay 0 UNKNOWN_PDK_MODEL --

CORPUS = repo_path_opt(".claude/worktrees/cap-crc/benchmark_clean/u_hawaii_adc_v0125_fresh")


@pytest.mark.skipif(not CORPUS.is_dir(), reason="real adc corpus not present")
def test_corpus_sweep_zero_false_positive(tmp_path):
    out = tmp_path / "corpus.json"
    r = subprocess.run(
        [sys.executable, str(PROG), str(CORPUS), "--json", str(out)],
        capture_output=True, text=True,
    )
    rpt = json.loads(out.read_text())
    fp = [f for f in rpt["findings"] if f["rule"] == "UNKNOWN_PDK_MODEL"]
    assert fp == [], f"false positives on real corpus: {fp}"
    assert rpt["summary"]["unknown_pdk_model_errors"] == 0
    assert rpt["passed"] is True
    assert r.returncode == 0
