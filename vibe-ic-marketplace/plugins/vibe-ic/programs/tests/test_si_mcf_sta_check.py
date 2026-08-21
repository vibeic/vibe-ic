#!/usr/bin/env python3
"""Gate tests for si_mcf_sta_check.py — the MCF-bounded SI-STA false-clean-proof.

Builds a synthetic project (original coupling SPEF + genuine / cheated bounded
SPEFs + a si_mcf_sta.json report) and asserts:
  * a genuinely-folded bounded SPEF PASSES the gate,
  * a bounded SPEF whose Cc*MCF was silently DROPPED FAILS (false-clean caught),
  * a report claiming the SI-bounded slack IMPROVED over nominal FAILS
    (monotonicity — a conservative bound can only degrade slack).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import si_mcf_sta as M          # noqa: E402
import si_mcf_sta_check as G    # noqa: E402

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


def _mk_project(tmp_path: Path, *, setup_bounded_text: str,
                hold_bounded_text: str, setup_after=7.36, hold_after=0.39):
    """Write a synthetic project tree + si_mcf_sta.json; return the report path."""
    proj = tmp_path / "proj"
    (proj / "reports" / "phase3").mkdir(parents=True)
    spef = proj / "spm.spef"
    spef.write_text(SPEF)
    sb = proj / "spm.mcf_setup.spef"
    sb.write_text(setup_bounded_text)
    hb = proj / "spm.mcf_hold.spef"
    hb.write_text(hold_bounded_text)
    report = {
        "program": "si_mcf_sta", "spef": str(spef),
        "overlap_guard_ns": 0.0,
        # no windows_json => gate uses the window-independent floor
        "nominal": {"worst_setup_slack_ns": 7.37, "worst_hold_slack_ns": 0.39},
        "corners": {
            "setup": {"bounded_spef": str(sb),
                      "worst_slack_before_ns": 7.37,
                      "worst_slack_after_ns": setup_after},
            "hold": {"bounded_spef": str(hb),
                     "worst_slack_before_ns": 0.39,
                     "worst_slack_after_ns": hold_after},
        },
    }
    rp = proj / "reports" / "phase3" / "si_mcf_sta.json"
    rp.write_text(json.dumps(report))
    return proj, rp


def _genuine_bounded():
    pairs = M.coupling_pairs(SPEF)
    setup_fold = M.floor_folded_caps(pairs, "setup")   # floor == MCF=1 lower bound
    # apply the true worst-case MCF=2 fold (>= floor), so the gate's floor check passes
    setup_fold = {k: v * 2 for k, v in setup_fold.items()}
    s, _ = M.rewrite_spef_folded(SPEF, setup_fold, "setup")
    h, _ = M.rewrite_spef_folded(SPEF, {"*1": 0.0, "*2": 0.0}, "hold")
    return s, h


def test_gate_passes_on_genuine_fold(tmp_path):
    s, h = _genuine_bounded()
    proj, rp = _mk_project(tmp_path, setup_bounded_text=s, hold_bounded_text=h)
    findings, stats = G.audit(proj, rp)
    rep = G.build_report(findings, stats, str(proj))
    assert rep["verdict"] == "PASS", rep["findings"]
    assert rep["summary"]["errors_count"] == 0


def test_gate_fails_false_clean_dropped_fold(tmp_path):
    # CHEAT: setup bounded drops coupling but folds nothing
    cheat, _ = M.rewrite_spef_folded(SPEF, {"*1": 0.0, "*2": 0.0}, "setup")
    _, h = _genuine_bounded()
    proj, rp = _mk_project(tmp_path, setup_bounded_text=cheat, hold_bounded_text=h)
    findings, stats = G.audit(proj, rp)
    rep = G.build_report(findings, stats, str(proj))
    assert rep["verdict"] == "FAIL"
    assert any(f["category"] == "FOLD_NOT_APPLIED" for f in rep["findings"])


def test_gate_fails_residual_coupling(tmp_path):
    # setup bounded == original (coupling never folded to ground)
    _, h = _genuine_bounded()
    proj, rp = _mk_project(tmp_path, setup_bounded_text=SPEF, hold_bounded_text=h)
    findings, stats = G.audit(proj, rp)
    rep = G.build_report(findings, stats, str(proj))
    assert rep["verdict"] == "FAIL"


def test_gate_fails_slack_better_than_bound(tmp_path):
    # genuine fold, but the report claims setup IMPROVED (after > before)
    s, h = _genuine_bounded()
    proj, rp = _mk_project(tmp_path, setup_bounded_text=s, hold_bounded_text=h,
                           setup_after=7.50)          # 7.50 > 7.37 nominal
    findings, stats = G.audit(proj, rp)
    rep = G.build_report(findings, stats, str(proj))
    assert rep["verdict"] == "FAIL"
    assert any(f["category"] == "SLACK_BETTER_THAN_BOUND" for f in rep["findings"])


def test_gate_missing_report(tmp_path):
    """#506 — a gate that could not obtain its input is NOT_RUN, not FAIL.

    This assertion read `verdict == "FAIL"` until #506 split the ERROR set:
    `NO_REPORT` means the gate never got to look, and reporting that as a
    design failure is how a report with an unreadable `spef` path came to say
    "FAIL" and "Read this as NOT CHECKED" in the same file. THE EXIT CODE DOES
    NOT MOVE — `NOT_RUN` is still rc 1, so nothing got quieter; only the answer
    got true. Pinned end-to-end (not just on the token) in
    `test_si_mcf_not_run_is_not_a_design_failure.py`."""
    proj = tmp_path / "empty"
    (proj / "reports" / "phase3").mkdir(parents=True)
    findings, stats = G.audit(proj)
    rep = G.build_report(findings, stats, str(proj))
    assert rep["verdict"] == "NOT_RUN"
    assert rep["summary"]["vacuous"] is True
    assert rep["summary"]["pass"] is False
    assert any(f["category"] == "NO_REPORT" for f in rep["findings"])
