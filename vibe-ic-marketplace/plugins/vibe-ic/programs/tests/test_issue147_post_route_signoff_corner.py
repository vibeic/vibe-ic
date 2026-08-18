"""#147 — Step-23 multi-corner sign-off SLACK gate.

Step 23 derived its verdict only from the NOMINAL corner + the SI/crosstalk MCF
check, so a slow-corner (max-RC) setup violation in the TAPEOUT-SIGNOFF
multicorner report shipped as a PASS. `post_route_signoff_corner_check` parses
the multicorner report and FAILs on a negative worst-slack at any sign-off
corner.

§4.05 no-leak: a nominal-only-clean design with a violated sign-off corner now
FAILs; an all-corner-clean design PASSes; a design with no multicorner report is
NOT_APPLICABLE (backward-compatible).
"""
from __future__ import annotations

import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import post_route_signoff_corner_check as G  # noqa: E402

_VIOLATED = """# Multi-corner SPEF STA (TAPEOUT-SIGNOFF P1)
# SETUP corner: max-RC   HOLD corner: min-RC
# corners_available: max,min,nom
=== SETUP (max-RC corner, SPEF=max) ===
worst slack max -1.71
tns max -10.91
=== HOLD (min-RC corner, SPEF=min) ===
worst slack min 0.54
tns max -1.82
"""

_CLEAN = """# Multi-corner SPEF STA (TAPEOUT-SIGNOFF P1)
# SETUP corner: max-RC   HOLD corner: min-RC
# corners_available: max,min,nom
=== SETUP (max-RC corner, SPEF=max) ===
worst slack max 0.42
tns max 0.00
=== HOLD (min-RC corner, SPEF=min) ===
worst slack min 0.54
tns max 0.00
"""

_HOLD_VIOLATED = """# Multi-corner SPEF STA (TAPEOUT-SIGNOFF P1)
=== SETUP (max-RC corner, SPEF=max) ===
worst slack max 0.30
=== HOLD (min-RC corner, SPEF=min) ===
worst slack min -0.22
"""


def _mk(tmp: Path, body: str) -> Path:
    sta = tmp / "phase3" / "stage3" / "sta"
    sta.mkdir(parents=True)
    (sta / "sta_spef_multicorner.rpt").write_text(body)
    return tmp


# ── pure evaluator ────────────────────────────────────────────────────────
def test_setup_violation_fails():
    res = G.evaluate(_VIOLATED)
    assert res["verdict"] == "FAIL"
    assert res["setup_worst_slack_ns"] == -1.71
    assert res["hold_worst_slack_ns"] == 0.54
    assert res["governing_worst_slack_ns"] == -1.71


def test_all_corners_clean_passes():
    res = G.evaluate(_CLEAN)
    assert res["verdict"] == "PASS"
    assert res["governing_worst_slack_ns"] == 0.42


def test_hold_violation_fails():
    res = G.evaluate(_HOLD_VIOLATED)
    assert res["verdict"] == "FAIL"
    assert res["hold_worst_slack_ns"] == -0.22


def test_no_slack_lines_not_applicable():
    res = G.evaluate("# Multi-corner SPEF STA (TAPEOUT-SIGNOFF P1)\n"
                     "Warning 503: something deprecated\n")
    assert res["verdict"] == "NOT_APPLICABLE"


def test_float_noise_within_tol_passes():
    body = ("=== SETUP (max-RC corner, SPEF=max) ===\nworst slack max -0.0005\n"
            "=== HOLD (min-RC corner, SPEF=min) ===\nworst slack min 0.10\n")
    assert G.evaluate(body)["verdict"] == "PASS"      # 0.5 ps < 1 ps tol


# ── CLI / exit codes ──────────────────────────────────────────────────────
def test_cli_fail_on_violation(tmp_path):
    proj = _mk(tmp_path, _VIOLATED)
    rc = G.main([str(proj), "--json", str(tmp_path / "out.json")])
    assert rc == 1


def test_cli_pass_on_clean(tmp_path):
    proj = _mk(tmp_path, _CLEAN)
    assert G.main([str(proj)]) == 0


def test_cli_not_applicable_when_report_absent(tmp_path):
    # backward-compatible: a design that produced no multicorner report is not
    # judged here (the step's nominal gate still applies).
    assert G.main([str(tmp_path)]) == 0
