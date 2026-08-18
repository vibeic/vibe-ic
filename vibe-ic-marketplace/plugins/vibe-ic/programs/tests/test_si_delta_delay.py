#!/usr/bin/env python3
"""TAPEOUT-SIGNOFF P1 — si_signoff_timing_aware.score_delta_delay.

The coupling-based DELTA-DELAY screen must emit a GENUINE PASS/FAIL/ADVISORY
verdict (a net whose coupled delta-delay pushes a path negative is a REAL
finding), NOT the forced 0 the legacy floating-noise advisory carried.

§4.05 coverage:
  * FAIL     — a proven push-negative (delta_t > victim slack) surfaces.
  * PASS     — a slack basis exists AND covers the worst modelled delta-delay.
  * ADVISORY — no slack basis (cannot prove) -> honest, never a silent PASS,
               never a fabricated FAIL.
  * decoupled — non-overlapping switching windows => coupling event impossible
               => conclusively SAFE (not counted as a finding).
  * the TCL emitter now captures per-pin slack (report_required) so the live
    runner path can produce a real FAIL.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import si_signoff_timing_aware as S  # noqa: E402


# A coupled pair victim=*1 / aggressor=*2, high coupling (Cc=0.9, Cg=0.1 => ratio
# 0.9). Built as a pre-parsed SPEF dict (score_delta_delay accepts that shape).
def _spef():
    return {
        "name_map": {"*1": "vic", "*2": "agg"},
        "cg": {"*1": 0.1, "*2": 0.1},
        "cc": {"*1": 0.9, "*2": 0.9},
        "pair_cc": {frozenset(("*1", "*2")): 0.9},
        "net_driver_pins": {"*1": ["vic_drv/X"], "*2": ["agg_drv/X"]},
        "net_load_pins": {"*1": ["ff/D"], "*2": ["ff2/D"]},
        "node_net": {}, "c_unit_pf": 1.0, "delimiter": ":",
    }


def _timing(vic_slack=None, ff2_slack=5.0, overlap=True):
    agg_arr = (1.2, 2.2) if overlap else (10.0, 11.0)
    pins = {
        "vic_drv/X": {"arr_rise_min": 1.0, "arr_rise_max": 2.0,
                      "arr_fall_min": 1.0, "arr_fall_max": 2.0,
                      "slew_rise_max": 0.5, "slew_fall_max": 0.5},
        "agg_drv/X": {"arr_rise_min": agg_arr[0], "arr_rise_max": agg_arr[1],
                      "arr_fall_min": agg_arr[0], "arr_fall_max": agg_arr[1],
                      "slew_rise_max": 0.5, "slew_fall_max": 0.5},
        "ff/D": {"arr_rise_max": 2.0, "arr_fall_max": 2.0},
        "ff2/D": {"arr_rise_max": 2.2, "arr_fall_max": 2.2},
    }
    if vic_slack is not None:
        pins["ff/D"]["slack_max"] = vic_slack
    if ff2_slack is not None:
        pins["ff2/D"]["slack_max"] = ff2_slack
    return {"tool": "OpenSTA", "pins": pins}


# ---------------------------------------------------------------------------
def test_delta_delay_fail_when_push_negative():
    # ratio 0.9, slew 0.5, MF 2 => delta_t = 1*0.9*0.5 = 0.45 ns.
    # victim slack 0.3 < 0.45 => path pushed to -0.15 => FAIL.
    r = S.score_delta_delay(_spef(), _timing(vic_slack=0.3, ff2_slack=5.0))
    assert r["delta_delay_verdict"] == "FAIL", r
    assert r["violations_count"] >= 1
    v = r["violations"][0]
    assert v["status"] == "push_negative"
    assert v["post_coupling_slack_ns"] < 0.0
    assert abs(r["max_delta_delay_ns"] - 0.45) < 1e-6


def test_delta_delay_pass_when_slack_covers():
    # widen both victims' slack so delta-delay is safely covered => PASS.
    r = S.score_delta_delay(_spef(), _timing(vic_slack=2.0, ff2_slack=5.0))
    assert r["delta_delay_verdict"] == "PASS", r
    assert r["violations_count"] == 0
    assert r["pairs_slack_checked"] >= 1


def test_delta_delay_advisory_when_no_slack_basis():
    # No pin carries a slack => cannot prove push-negative => ADVISORY (never a
    # silent PASS, never a fabricated FAIL). §4.05.
    r = S.score_delta_delay(_spef(), _timing(vic_slack=None, ff2_slack=None))
    assert r["delta_delay_verdict"] == "ADVISORY", r
    assert r["pairs_slack_checked"] == 0
    assert r["violations_count"] == 0


def test_delta_delay_decoupled_is_safe():
    # non-overlapping windows => coupling event timing-impossible => the pair is
    # decoupled-safe and never becomes a finding even with tiny slack.
    r = S.score_delta_delay(_spef(), _timing(vic_slack=0.01, ff2_slack=0.01,
                                             overlap=False))
    assert r["pairs_decoupled_by_window"] >= 1
    assert r["pairs_overlapping"] == 0
    assert r["violations_count"] == 0
    # with no overlapping pair slack-checked, the verdict is ADVISORY (nothing
    # was provable) — NOT a PASS masquerading over unevaluated risk.
    assert r["delta_delay_verdict"] == "ADVISORY"


def test_delta_delay_not_a_forced_zero():
    # The whole point: violations_count is COMPUTED, not hardcoded 0. A tight
    # slack MUST raise it above 0.
    fail = S.score_delta_delay(_spef(), _timing(vic_slack=0.1, ff2_slack=0.1))
    assert fail["violations_count"] > 0
    assert fail["delta_delay_verdict"] == "FAIL"


def test_delta_delay_verdict_scope_is_honest():
    r = S.score_delta_delay(_spef(), _timing(vic_slack=2.0))
    for token in ("delta-delay", "push", "ADVISORY", "not a full RLC"):
        assert token.lower() in r["scope"].lower(), token


def test_run_public_api_merges_delta_delay(tmp_path):
    # run_si_signoff_timing_aware must attach the delta_delay block + verdict.
    import json
    # minimal SPEF text (real dialect) with one coupling pair
    spef = tmp_path / "d.spef"
    spef.write_text(
        '*SPEF "ieee 1481-1999"\n*DELIMITER :\n*C_UNIT 1 PF\n'
        "*NAME_MAP\n*1 vic\n*2 agg\n*10 u0\n*11 u1\n"
        "*D_NET *1 1.0\n*CONN\n*I *10:Q O *D dfxtp\n*I *11:D I *D dfxtp\n"
        "*CAP\n1 vic 0.1\n2 vic *2:Q 0.9\n*END\n"
        "*D_NET *2 1.0\n*CONN\n*I *11:Q O *D dfxtp\n*CAP\n1 agg 0.1\n*END\n")
    timing = tmp_path / "t.json"
    timing.write_text(json.dumps({"tool": "OpenSTA", "pins": {
        "u0/Q": {"arr_rise_max": 2.0, "arr_fall_max": 2.0,
                 "slew_rise_max": 0.5, "slew_fall_max": 0.5, "slack_max": 5.0},
        "u1/Q": {"arr_rise_max": 2.1, "arr_fall_max": 2.1,
                 "slew_rise_max": 0.5, "slew_fall_max": 0.5, "slack_max": 5.0},
    }}))
    v = S.run_si_signoff_timing_aware(spef, timing)
    assert "delta_delay" in v
    assert v["delta_delay_verdict"] in ("PASS", "FAIL", "ADVISORY")


def test_tcl_emitter_captures_slack():
    # The SI timing-JSON TCL must now capture per-pin slack (report_required)
    # AND emit slack_max in each pin record — the live FAIL basis.
    tcl = S.build_opensta_si_tcl(
        "lib.lib", "n.v", "top", "c.sdc", "s.spef", "out.json")
    assert "report_required" in tcl
    assert "slack_max" in tcl
    # documented shape now carries slack_max
    assert "slack_max" in S.TIMING_JSON_SHAPE["pins"]["<pin_full_name>"]


def test_cli_strict_delta_exit_code(tmp_path):
    import json
    import subprocess
    spef = tmp_path / "d.spef"
    spef.write_text(
        '*SPEF "ieee 1481-1999"\n*DELIMITER :\n*C_UNIT 1 PF\n'
        "*NAME_MAP\n*1 vic\n*2 agg\n*10 u0\n*11 u1\n"
        "*D_NET *1 1.0\n*CONN\n*I *10:Q O *D dfxtp\n*I *11:D I *D dfxtp\n"
        "*CAP\n1 vic 0.1\n2 vic *2:Q 0.9\n*END\n"
        "*D_NET *2 1.0\n*CONN\n*I *11:Q O *D dfxtp\n*CAP\n1 agg 0.1\n*END\n")
    timing = tmp_path / "t.json"
    # tight slack on the victim endpoint => delta-delay FAIL
    timing.write_text(json.dumps({"tool": "OpenSTA", "pins": {
        "u0/Q": {"arr_rise_max": 2.0, "arr_fall_max": 2.0,
                 "slew_rise_max": 0.6, "slew_fall_max": 0.6, "slack_max": 0.1},
        "u1/D": {"arr_rise_max": 2.0, "arr_fall_max": 2.0, "slack_max": 0.1},
        "u1/Q": {"arr_rise_max": 2.1, "arr_fall_max": 2.1,
                 "slew_rise_max": 0.6, "slew_fall_max": 0.6, "slack_max": 5.0},
    }}))
    prog = _PROGRAMS / "si_signoff_timing_aware.py"
    # default (advisory) => exit 0 even with a delta-delay FAIL
    r0 = subprocess.run([sys.executable, str(prog), "score", str(spef),
                         str(timing)], capture_output=True, text=True)
    assert r0.returncode == 0
    # --strict-delta => exit 1 on a proven push-negative
    r1 = subprocess.run([sys.executable, str(prog), "score", "--strict-delta",
                         str(spef), str(timing)], capture_output=True, text=True)
    assert r1.returncode == 1, r1.stdout
