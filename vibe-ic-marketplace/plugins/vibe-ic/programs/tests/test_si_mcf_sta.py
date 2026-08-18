#!/usr/bin/env python3
"""Pure-helper unit tests for si_mcf_sta.py (SI-aware STA via MCF bounding).

Covers every deterministic, tool-free helper:
  * coupling_pairs        — *CAP coupling entries -> aggressor/victim + Cc
  * windows_overlap       — overlap logic + unknown-window conservatism
  * mcf_for_pair          — the MCF formula per corner + window gating
  * net_windows_from_timing — per-pin arrival JSON -> per-net window
  * victim_folded_caps    — per-net MCF-bounded fold + worst aggressor
  * floor_folded_caps     — window-independent lower bound
  * rewrite_spef_folded   — coupling dropped, fold added, header rewritten,
                            MCF=1 self-fold reproduces the original total
  * net_grounded_totals / count_coupling_caps
  * independent_recount   — self-consistent PASS + false-clean recount FAIL
  * worst_setup_hold      — OpenSTA report parse
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import si_mcf_sta as M  # noqa: E402


# A minimal 2-net coupling SPEF: victim *1 (vic) and aggressor *2 (agg), one
# coupling cap Cc=0.1 pF between them, each net carrying 0.2 pF of ground cap.
SPEF = """*SPEF "ieee 1481-1999"
*DESIGN "t"
*VERSION "1.0"
*DIVIDER /
*DELIMITER :
*BUS_DELIMITER []
*T_UNIT 1 NS
*C_UNIT 1 PF
*R_UNIT 1 OHM
*L_UNIT 1 HENRY

*NAME_MAP
*1 vic
*2 agg

*D_NET *1 0.3
*CONN
*I inv1:Z O *D BUF
*I ff1:D I *D DFF
*CAP
1 inv1:Z 0.1
2 ff1:D 0.1
3 ff1:D agg2:A 0.1
*RES
1 inv1:Z ff1:D 10
*END

*D_NET *2 0.2
*CONN
*I inv2:Z O *D BUF
*I agg2:A I *D DFF
*CAP
1 inv2:Z 0.1
2 agg2:A 0.1
*RES
1 inv2:Z agg2:A 10
*END
"""


# --------------------------------------------------------------------------
# coupling_pairs
# --------------------------------------------------------------------------
def test_coupling_pairs_extracts_pair_and_cc():
    pairs = M.coupling_pairs(SPEF)
    assert pairs == {("*1", "*2"): 0.1}


def test_coupling_pairs_accepts_preparsed_dict():
    sp = M.parse_spef(SPEF)
    assert M.coupling_pairs(sp) == {("*1", "*2"): 0.1}


# --------------------------------------------------------------------------
# windows_overlap
# --------------------------------------------------------------------------
def test_windows_overlap_basic():
    assert M.windows_overlap((0.0, 1.0), (0.5, 1.5)) is True
    assert M.windows_overlap((0.0, 1.0), (2.0, 3.0)) is False
    # touching at the boundary counts as overlap
    assert M.windows_overlap((0.0, 1.0), (1.0, 2.0)) is True


def test_windows_overlap_unknown_is_conservative():
    # unknown window => cannot prove decoupling => assume overlap
    assert M.windows_overlap(None, (2.0, 3.0)) is True
    assert M.windows_overlap((0.0, 1.0), None) is True


def test_windows_overlap_guard_band():
    # 0.4 gap; a 0.5 guard makes them overlap, no guard does not
    assert M.windows_overlap((0.0, 1.0), (1.4, 2.0)) is False
    assert M.windows_overlap((0.0, 1.0), (1.4, 2.0), guard_ns=0.5) is True


# --------------------------------------------------------------------------
# mcf_for_pair
# --------------------------------------------------------------------------
def test_mcf_setup_overlap_is_two():
    assert M.mcf_for_pair((0.0, 1.0), (0.5, 1.5), "setup") == 2.0


def test_mcf_setup_decoupled_is_one():
    assert M.mcf_for_pair((0.0, 1.0), (2.0, 3.0), "setup") == 1.0


def test_mcf_hold_overlap_is_zero():
    assert M.mcf_for_pair((0.0, 1.0), (0.5, 1.5), "hold") == 0.0


def test_mcf_hold_decoupled_is_one():
    assert M.mcf_for_pair((0.0, 1.0), (2.0, 3.0), "hold") == 1.0


def test_mcf_unknown_window_setup_is_two():
    # unknown window => assume overlap => worst-case MCF (never optimistic)
    assert M.mcf_for_pair(None, None, "setup") == 2.0
    assert M.mcf_for_pair(None, None, "hold") == 0.0


def test_mcf_bad_corner_raises():
    import pytest
    with pytest.raises(ValueError):
        M.mcf_for_pair((0.0, 1.0), (0.5, 1.5), "typ")


# --------------------------------------------------------------------------
# net_windows_from_timing
# --------------------------------------------------------------------------
def test_net_windows_from_timing_union_and_slew_pad():
    timing = {"pins": {
        "inv1:Z": {"arr_rise_min": 1.0, "arr_rise_max": 1.2,
                   "arr_fall_min": 0.9, "arr_fall_max": 1.1,
                   "slew_rise_max": 0.1, "slew_fall_max": 0.05},
    }}
    w = M.net_windows_from_timing(timing, {"*1": ["inv1:Z"]})
    # union of rise/fall arrivals = (0.9, 1.2), trailing edge padded by max slew 0.1
    assert w["*1"] == (0.9, 1.3)


def test_net_windows_from_timing_no_driver_pin_is_none():
    w = M.net_windows_from_timing({"pins": {}}, {"*1": ["missing:Z"]})
    assert w["*1"] is None


# --------------------------------------------------------------------------
# victim_folded_caps  +  floor_folded_caps
# --------------------------------------------------------------------------
def test_victim_folded_setup_folds_both_nets_at_mcf2():
    pairs = {("*1", "*2"): 0.1}
    windows = {"*1": (0.0, 1.0), "*2": (0.5, 1.5)}  # overlap
    folded, worst = M.victim_folded_caps(pairs, windows, "setup")
    assert folded == {"*1": 0.2, "*2": 0.2}          # 0.1 * 2 on each victim
    assert worst["*1"]["aggressor"] == "*2"
    assert worst["*1"]["mcf"] == 2.0


def test_victim_folded_hold_overlap_is_zero():
    pairs = {("*1", "*2"): 0.1}
    windows = {"*1": (0.0, 1.0), "*2": (0.5, 1.5)}
    folded, _ = M.victim_folded_caps(pairs, windows, "hold")
    assert folded == {"*1": 0.0, "*2": 0.0}


def test_victim_folded_decoupled_setup_is_mcf1():
    pairs = {("*1", "*2"): 0.1}
    windows = {"*1": (0.0, 1.0), "*2": (5.0, 6.0)}   # no overlap
    folded, _ = M.victim_folded_caps(pairs, windows, "setup")
    assert folded == {"*1": 0.1, "*2": 0.1}          # 0.1 * 1 (quiet)


def test_floor_folded_caps():
    pairs = {("*1", "*2"): 0.1}
    assert M.floor_folded_caps(pairs, "setup") == {"*1": 0.1, "*2": 0.1}
    assert M.floor_folded_caps(pairs, "hold") == {"*1": 0.0, "*2": 0.0}


# --------------------------------------------------------------------------
# rewrite_spef_folded
# --------------------------------------------------------------------------
def test_rewrite_drops_coupling_and_adds_ground_fold():
    folded = {"*1": 0.2, "*2": 0.2}   # setup MCF=2
    text, stats = M.rewrite_spef_folded(SPEF, folded, "setup")
    assert stats["coupling_caps_dropped"] == 1
    assert stats["nets_folded"] == 2
    assert stats["nets_no_repnode"] == 0
    # the bounded SPEF has NO coupling caps left
    assert M.count_coupling_caps(text) == 0
    # each net's grounded total rose by its fold (0.2 -> 0.4)
    g = M.net_grounded_totals(text)
    assert abs(g["*1"] - 0.4) < 1e-9
    assert abs(g["*2"] - 0.4) < 1e-9
    # header total rewritten to grounded + fold
    assert "*D_NET *1 0.4" in text


def test_rewrite_mcf1_reproduces_original_total():
    # MCF=1 self-fold: coupling moved to ground, header total UNCHANGED.
    folded = {"*1": 0.1, "*2": 0.1}
    text, _ = M.rewrite_spef_folded(SPEF, folded, "anchor")
    assert M.count_coupling_caps(text) == 0
    g = M.net_grounded_totals(text)
    # *1 original header total was 0.3 (0.2 grounded + 0.1 coupling); the MCF=1
    # self-fold moves the coupling to ground, reproducing that 0.3 exactly.
    assert abs(g["*1"] - 0.3) < 1e-9


def test_rewrite_mcf1_net2_total_matches():
    folded = {"*1": 0.1, "*2": 0.1}
    text, _ = M.rewrite_spef_folded(SPEF, folded, "anchor")
    g = M.net_grounded_totals(text)
    # *2 grounded 0.2 + folded 0.1 = 0.3
    assert abs(g["*2"] - 0.3) < 1e-9


def test_rewrite_banner_present():
    text, _ = M.rewrite_spef_folded(SPEF, {"*1": 0.2, "*2": 0.2}, "setup")
    assert "SI-BOUNDED SPEF (SETUP corner)" in text
    assert "NOT silicon-proven" in text


# --------------------------------------------------------------------------
# net_grounded_totals / count_coupling_caps on the raw SPEF
# --------------------------------------------------------------------------
def test_grounded_totals_and_coupling_count_raw():
    assert M.count_coupling_caps(SPEF) == 1
    g = M.net_grounded_totals(SPEF)
    assert abs(g["*1"] - 0.2) < 1e-9
    assert abs(g["*2"] - 0.2) < 1e-9


# --------------------------------------------------------------------------
# independent_recount  (the GATE's false-clean-proof)
# --------------------------------------------------------------------------
def _windows_overlap_dict():
    return {"*1": (0.0, 1.0), "*2": (0.5, 1.5)}


def test_recount_self_consistent_setup_passes():
    windows = _windows_overlap_dict()
    folded, _ = M.victim_folded_caps(M.coupling_pairs(SPEF), windows, "setup")
    bounded, _ = M.rewrite_spef_folded(SPEF, folded, "setup")
    rc = M.independent_recount(SPEF, bounded, windows, "setup")
    assert rc["ok"] is True
    assert rc["nets_checked"] == 2
    assert rc["residual_coupling_caps"] == 0


def test_recount_false_clean_dropped_fold_fails():
    # CHEAT: drop coupling but fold NOTHING (bounded stays at plain grounded)
    windows = _windows_overlap_dict()
    cheat, _ = M.rewrite_spef_folded(SPEF, {"*1": 0.0, "*2": 0.0}, "setup")
    rc = M.independent_recount(SPEF, cheat, windows, "setup")
    assert rc["ok"] is False
    assert any(v["reason"] == "UNDER_APPLIED_MCF" for v in rc["violations"])


def test_recount_residual_coupling_fails():
    # bounded == original (coupling caps never folded to ground) -> must FAIL
    windows = _windows_overlap_dict()
    rc = M.independent_recount(SPEF, SPEF, windows, "setup")
    assert rc["ok"] is False
    assert rc["residual_coupling_caps"] == 1


def test_recount_over_applied_fails():
    # inflate the fold beyond the MCF=2 ceiling (0.1*2=0.2); apply 0.5
    windows = _windows_overlap_dict()
    over, _ = M.rewrite_spef_folded(SPEF, {"*1": 0.5, "*2": 0.5}, "setup")
    rc = M.independent_recount(SPEF, over, windows, "setup")
    assert rc["ok"] is False
    assert any(v["reason"] == "OVER_APPLIED_MCF" for v in rc["violations"])


def test_recount_floor_mode_catches_dropped_fold_without_windows():
    # gate path when the timing-window JSON is unavailable: use the MCF>=1 floor
    expected = M.floor_folded_caps(M.coupling_pairs(SPEF), "setup")
    cheat, _ = M.rewrite_spef_folded(SPEF, {"*1": 0.0, "*2": 0.0}, "setup")
    rc = M.independent_recount(SPEF, cheat, {}, "setup", expected=expected)
    assert rc["ok"] is False


# --------------------------------------------------------------------------
# worst_setup_hold
# --------------------------------------------------------------------------
def test_worst_setup_hold_parse():
    rpt = "worst slack max 7.3675\nworst slack min 0.3934\n"
    assert M.worst_setup_hold(rpt) == (7.3675, 0.3934)


def test_worst_setup_hold_missing():
    assert M.worst_setup_hold("no slack here") == (None, None)
