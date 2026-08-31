#!/usr/bin/env python3
"""A SPEF escape character must not decide a design's SI verdict.

The SI-aware STA chooses each aggressor's Miller factor from whether its
switching window can overlap the victim's, and an UNKNOWN window
conservatively assumes overlap -- the worst case. That default is correct and
is not touched here. What was wrong is how often it fired: the driver-pin
lookup compared the SPEF's IEEE-1481 ESCAPED spelling of a pin against the
timing tool's PLAIN spelling, so every hierarchical pin missed and its net was
promoted to the worst-case Miller factor by a backslash.

MEASURED on a routed gf180 core before the fix: 1093 of 1558 coupling nets
(70.2%) resolved no window, and in 1093 of 1093 cases the unescaped spelling
WAS present in the window report. Un-escaping recovered 1065 (coverage
29.8% -> 98.2%); the residual 28 are genuinely absent and keep the
conservative default.

These tests pin BOTH directions:
  * the escaped name now resolves, and the recovered window really does
    de-escalate a pair from MCF=2 to MCF=1 (the whole point);
  * un-escaping never INVENTS a window -- a name that matches nothing is still
    None, and the unknown-window conservatism is untouched;
  * the coverage that was previously invisible is now stated, and the checker
    says so out loud when it is partial -- as a WARNING, because unresolved
    nets degrade in the conservative direction and must never silently flip a
    verdict.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import si_mcf_sta as M  # noqa: E402
import si_mcf_sta_check as C  # noqa: E402


# --------------------------------------------------------------------------
# unescape_spef_name -- pure
# --------------------------------------------------------------------------
def test_unescape_strips_the_escape_not_the_character():
    assert M.unescape_spef_name(r"__uuf__\._1811_/Q") == "__uuf__._1811_/Q"


def test_unescape_leaves_an_unescaped_name_alone():
    for name in ("_378_/ZN", "ANTENNA_1/I", "top/u0/Z"):
        assert M.unescape_spef_name(name) == name


def test_unescape_handles_every_escaped_character_not_just_the_dot():
    assert M.unescape_spef_name(r"a\.b\[3\]\/c") == "a.b[3]/c"


def test_unescape_is_idempotent_on_an_already_plain_name():
    once = M.unescape_spef_name(r"x\.y")
    assert M.unescape_spef_name(once) == once


# --------------------------------------------------------------------------
# the lookup: recovers a real window, invents none
# --------------------------------------------------------------------------
_PLAIN_WINDOWS = {"pins": {
    "u_core._1811_/Q": {"arr_rise_min": 1.0, "arr_rise_max": 1.2,
                        "arr_fall_min": 0.9, "arr_fall_max": 1.1,
                        "slew_rise_max": 0.1, "slew_fall_max": 0.05},
}}


def test_escaped_spef_driver_pin_resolves_against_a_plain_window_report():
    w = M.net_windows_from_timing(
        _PLAIN_WINDOWS, {"*1": [r"u_core\._1811_/Q"]})
    assert w["*1"] == (0.9, 1.3)


def test_the_unescaped_lookup_never_invents_a_window():
    # A name absent under BOTH spellings must stay None, so the conservative
    # assume-overlap default still governs it.
    w = M.net_windows_from_timing(
        _PLAIN_WINDOWS, {"*1": [r"somewhere\.else/Z"]})
    assert w["*1"] is None


def test_a_plain_name_still_wins_directly():
    # The escaped retry is a FALLBACK; an exact hit must not be disturbed.
    timing = {"pins": {r"lit\eral/Z": {"arr_rise_min": 2.0,
                                       "arr_rise_max": 2.0}}}
    w = M.net_windows_from_timing(timing, {"*1": [r"lit\eral/Z"]})
    assert w["*1"] == (2.0, 2.0)


# --------------------------------------------------------------------------
# THE POINT: the recovered window de-escalates the Miller factor
# --------------------------------------------------------------------------
def test_recovered_windows_demote_a_pair_from_worst_case_to_quiet():
    # Victim switches early, aggressor late -- provably NON-overlapping, so the
    # setup MCF must be 1.0 (quiet), not the 2.0 an unknown window forces.
    timing = {"pins": {
        "core._v_/Q": {"arr_rise_min": 0.0, "arr_rise_max": 0.1,
                       "slew_rise_max": 0.0},
        "core._a_/Q": {"arr_rise_min": 9.0, "arr_rise_max": 9.1,
                       "slew_rise_max": 0.0},
    }}
    drivers = {"*1": [r"core\._v_/Q"], "*2": [r"core\._a_/Q"]}
    windows = M.net_windows_from_timing(timing, drivers)
    assert windows["*1"] is not None and windows["*2"] is not None
    assert M.mcf_for_pair(windows["*1"], windows["*2"], "setup") == M.MCF_QUIET

    # ... and with the windows unresolved (the pre-fix state) the SAME pair is
    # folded at the worst case. This is the defect, stated as an assertion.
    unresolved = {"*1": None, "*2": None}
    assert M.mcf_for_pair(unresolved["*1"], unresolved["*2"],
                          "setup") == M.MCF_SETUP_WORST


def test_the_fold_shrinks_when_the_windows_are_actually_read():
    pairs = {("*1", "*2"): 0.1}
    timing = {"pins": {
        "core._v_/Q": {"arr_rise_min": 0.0, "arr_rise_max": 0.1,
                       "slew_rise_max": 0.0},
        "core._a_/Q": {"arr_rise_min": 9.0, "arr_rise_max": 9.1,
                       "slew_rise_max": 0.0},
    }}
    drivers = {"*1": [r"core\._v_/Q"], "*2": [r"core\._a_/Q"]}
    resolved, _ = M.victim_folded_caps(
        pairs, M.net_windows_from_timing(timing, drivers), "setup")
    blind, _ = M.victim_folded_caps(pairs, {"*1": None, "*2": None}, "setup")
    assert sum(resolved.values()) < sum(blind.values())


# --------------------------------------------------------------------------
# the conservatism itself is UNCHANGED
# --------------------------------------------------------------------------
def test_unknown_window_still_conservatively_assumes_overlap():
    assert M.windows_overlap(None, (1.0, 2.0)) is True
    assert M.windows_overlap((1.0, 2.0), None) is True
    assert M.mcf_for_pair(None, None, "setup") == M.MCF_SETUP_WORST
    assert M.mcf_for_pair(None, None, "hold") == M.MCF_HOLD_WORST


def test_the_mcf_model_constants_are_untouched():
    assert (M.MCF_QUIET, M.MCF_SETUP_WORST, M.MCF_HOLD_WORST) == (1.0, 2.0, 0.0)


# --------------------------------------------------------------------------
# coverage is STATED, and partial coverage is said out loud (but not fatal)
# --------------------------------------------------------------------------
def _fixture(tmp_path, escaped: bool):
    """A 2-net coupling SPEF + a PLAIN-spelled window report, written to disk so
    the checker's real audit() runs over them. `escaped=True` spells the driver
    pins the way a SPEF does."""
    v = r"core\._v_/Q" if escaped else "core._v_/Q"
    a = r"core\._a_/Q" if escaped else "core._a_/Q"
    spef = tmp_path / "c.spef"
    spef.write_text(
        '*SPEF "ieee 1481-1999"\n*DESIGN "t"\n*VERSION "1.0"\n'
        "*DIVIDER /\n*DELIMITER :\n*BUS_DELIMITER []\n"
        "*T_UNIT 1 NS\n*C_UNIT 1 PF\n*R_UNIT 1 OHM\n*L_UNIT 1 HENRY\n\n"
        "*NAME_MAP\n*1 vic\n*2 agg\n\n"
        f"*D_NET *1 0.3\n*CONN\n*I {v} O *D BUF\n*CAP\n"
        "1 *1 *2 0.1\n2 *1 0.2\n*END\n\n"
        f"*D_NET *2 0.3\n*CONN\n*I {a} O *D BUF\n*CAP\n"
        "1 *2 0.3\n*END\n")
    win = tmp_path / "w.json"
    win.write_text(json.dumps({"pins": {
        "core._v_/Q": {"arr_rise_min": 0.0, "arr_rise_max": 0.1,
                       "slew_rise_max": 0.0},
        "core._a_/Q": {"arr_rise_min": 9.0, "arr_rise_max": 9.1,
                       "slew_rise_max": 0.0}}}))
    rep = tmp_path / "si_mcf_sta.json"
    rep.write_text(json.dumps({
        "spef": str(spef), "windows_json": str(win),
        "coupling_pairs": 1, "overlap_guard_ns": 0.0, "corners": {}}))
    return rep


def test_audit_states_full_coverage_and_raises_no_coverage_warning(tmp_path):
    findings, stats = C.audit(tmp_path, _fixture(tmp_path, escaped=True))
    assert stats["windows_total"] == 2
    assert stats["windows_resolved"] == 2
    assert stats["windows_coverage"] == 1.0
    assert not [f for f in findings if f.category == "WINDOW_COVERAGE_PARTIAL"]


def test_audit_states_partial_coverage_out_loud_as_a_non_fatal_warning(tmp_path):
    # Same fixture, but the window report no longer knows one of the pins --
    # the state that used to be invisible behind `windows_exact: true`.
    rep = _fixture(tmp_path, escaped=True)
    doc = json.loads(rep.read_text())
    w = json.loads(Path(doc["windows_json"]).read_text())
    del w["pins"]["core._a_/Q"]
    Path(doc["windows_json"]).write_text(json.dumps(w))

    findings, stats = C.audit(tmp_path, rep)
    assert stats["windows_total"] == 2
    assert stats["windows_resolved"] == 1
    assert stats["windows_coverage"] == 0.5
    hits = [f for f in findings if f.category == "WINDOW_COVERAGE_PARTIAL"]
    assert len(hits) == 1
    # Loud, but never a verdict: the unresolved net degrades in the
    # CONSERVATIVE direction, so it may overstate crosstalk and never hide it.
    assert hits[0].severity == "WARNING"
    assert sum(1 for f in findings
               if f.category == "WINDOW_COVERAGE_PARTIAL"
               and f.severity == "ERROR") == 0
