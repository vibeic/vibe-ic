#!/usr/bin/env python3
"""Unit tests for programs/_pdk_via_analyzer.py.

Pins the real DRT-0234 single-cut-via guard logic: the analyzer counts
RECT shapes in each VIA block's cut LAYER, classifies single-cut (<=1
RECT) vs multi-cut, and the CLI verdict is WARN iff a cut layer has
zero single-cut vias (the exact PDK defect that makes TritonRoute
abort). Logic-pinned.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import _pdk_via_analyzer as mod

PROG = Path(__file__).resolve().parent.parent / "_pdk_via_analyzer.py"


# A single-cut VIA1 (one RECT in cut layer via1).
_SINGLE_CUT_VIA = """
VIA VIA12 DEFAULT
  LAYER met1 ;
    RECT 0 0 1 1 ;
  LAYER via1 ;
    RECT 0 0 1 1 ;
  LAYER met2 ;
    RECT 0 0 1 1 ;
END VIA12
"""

# A multi-cut VIA5 (four RECTs in cut layer via5) with NO single-cut
# variant — the exact PDK shape that breaks detailed_route.
_MULTI_CUT_VIA = """
VIA VIA56_HORI4 DEFAULT
  LAYER met5 ;
    RECT 0 0 1 1 ;
  LAYER via5 ;
    RECT 0 0 1 1 ;
    RECT 2 2 3 3 ;
    RECT 4 4 5 5 ;
    RECT 6 6 7 7 ;
  LAYER met6 ;
    RECT 0 0 1 1 ;
END VIA56_HORI4
"""


# ---------------------------------------------------------------------------
# analyze_lef — RECT counting + single/multi classification
# ---------------------------------------------------------------------------
def test_single_cut_via_classified_single():
    info = mod.analyze_lef(_SINGLE_CUT_VIA)
    assert "via1" in info
    assert info["via1"]["single_cut"] == 1
    assert info["via1"]["multi_cut"] == 0
    assert info["via1"]["total"] == 1
    assert "VIA12" in info["via1"]["single_cut_names"]


def test_multi_cut_via_classified_multi():
    info = mod.analyze_lef(_MULTI_CUT_VIA)
    assert "via5" in info
    assert info["via5"]["single_cut"] == 0
    assert info["via5"]["multi_cut"] == 1
    assert "VIA56_HORI4" in info["via5"]["multi_cut_names"]


def test_empty_text_yields_no_vias():
    assert mod.analyze_lef("") == {}


def test_garbage_text_yields_no_vias():
    assert mod.analyze_lef("this is not a LEF file at all") == {}


# ---------------------------------------------------------------------------
# cut_layers_with_single_cut + routing_layer_upper_bound
# ---------------------------------------------------------------------------
def test_single_cut_layer_set_uppercased():
    assert mod.cut_layers_with_single_cut(_SINGLE_CUT_VIA) == {"VIA1"}


def test_multi_only_layer_not_in_single_cut_set():
    assert mod.cut_layers_with_single_cut(_MULTI_CUT_VIA) == set()


# GAP#1 (round-7) corrected semantics: None == no restriction (route all);
# an integer is returned ONLY when a real gap exists (a multi-cut-only
# transition above met1). A fully-covered PDK — even one with a single
# transition — must NOT restrict (the via covers met1↔met2, no gap).
def test_routing_upper_bound_none_when_fully_covered():
    # only single-cut VIA1 present and met1↔met2 IS covered → no gap →
    # no restriction (route all present layers). Pre-GAP#1 this wrongly
    # returned 2 (off-by-one "first uncovered index") which, fed to the
    # consumer's `routing_upper < mtotal`, collapsed routing.
    assert mod.routing_layer_upper_bound(_SINGLE_CUT_VIA) is None


# A genuine middle gap: single-cut M1↔M2 and M2↔M3, but M3↔M4 multi-cut-only.
_GAP_AT_M3M4 = """
VIA M1M2 DEFAULT
  LAYER met1 ;
  LAYER via ;
    RECT 0 0 1 1 ;
  LAYER met2 ;
END M1M2
VIA M2M3 DEFAULT
  LAYER met2 ;
  LAYER via2 ;
    RECT 0 0 1 1 ;
  LAYER met3 ;
END M2M3
VIA M3M4 DEFAULT
  LAYER met3 ;
  LAYER via3 ;
    RECT 0 0 1 1 ;
    RECT 2 2 3 3 ;
  LAYER met4 ;
END M3M4
"""


def test_routing_upper_bound_restricts_at_real_gap():
    # M1↔M2, M2↔M3 single-cut; M3↔M4 multi-cut-only → restrict to met1-met3.
    assert mod.routing_layer_upper_bound(_GAP_AT_M3M4) == 3


def test_routing_upper_bound_none_when_no_single_cut():
    assert mod.routing_layer_upper_bound(_MULTI_CUT_VIA) is None


# ---------------------------------------------------------------------------
# CLI verdict — PASS (all cut layers single-cut) vs WARN (defect)
# ---------------------------------------------------------------------------
def _run(lef_text: str, tmp_path: Path):
    lef = tmp_path / "tech.lef"
    lef.write_text(lef_text)
    return subprocess.run(
        [sys.executable, str(PROG), str(lef), "--json"],
        capture_output=True, text=True,
    )


def test_cli_pass_when_single_cut_present(tmp_path):
    r = _run(_SINGLE_CUT_VIA, tmp_path)
    assert r.returncode == 0
    rep = json.loads(r.stdout)
    assert rep["verdict"] == "PASS"
    assert rep["single_cut_missing"] == []


def test_cli_warn_when_only_multi_cut(tmp_path):
    r = _run(_MULTI_CUT_VIA, tmp_path)
    assert r.returncode == 0  # analysis succeeded; verdict carries the defect
    rep = json.loads(r.stdout)
    assert rep["verdict"] == "WARN"
    assert "via5" in rep["single_cut_missing"]


def test_cli_missing_file_is_rc2(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nope.lef"), "--json"],
        capture_output=True, text=True,
    )
    assert r.returncode == 2
    assert "not found" in r.stderr.lower()
