#!/usr/bin/env python3
"""ORGANIC #293 — a route promoted on its OWN re-measurement must be
corroborated by the sign-off report it claims to improve.

Field evidence: `signoff_spef_repair` promoted a repaired route because its own
in-session numbers read 330 -> 178 violations. The real multi-corner OCV
sign-off — `sta_mcorner_ocv.rpt`, the report the acceptance gate actually reads
— went 4 -> 219, and the reroute merged a spare-tie net into an unrelated
signal net, breaking LVS. The step was disabled in v1.5.65.

The encoded lesson: fixing your own internal re-measurement is not fixing the
downstream gate's measurement. "Passes its own test" is not "actually better" —
and this regression came from a change whose whole purpose was to stop false
certificates.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
import drv_promotion_corroboration_check as G  # noqa: E402


def _project(tmp_path, promoted=False, claimed=None, signoff_viols=None):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    if promoted:
        (pnr / "routed_base_prerepair.def").write_text("DESIGN x ;\n")
    if claimed is not None:
        (pnr / "signoff_spef_repair.log").write_text(
            f"Found 330 slew violations.\nFound {claimed} slew violations.\n")
    if signoff_viols is not None:
        rpt = tmp_path / "reports" / "phase3"
        rpt.mkdir(parents=True, exist_ok=True)
        rows = "\n".join(f"_{i}_/A    0.750    1.200   -0.450"
                         for i in range(signoff_viols))
        (rpt / "sta_mcorner_ocv.rpt").write_text(
            "=== SETUP corner: process=SS ===\nmax slew\n\n"
            "Pin      Limit   Slew   Slack\n-----\n" + rows + "\n")
    return tmp_path


def test_293_no_promotion_is_vacuous_pass(tmp_path):
    """The gate must not police runs that never promoted anything."""
    r = G.check(_project(tmp_path))
    assert r["verdict"] == "VACUOUS_PASS" and r["rc"] == 0


def test_293_reproduces_the_landed_regression(tmp_path):
    """THE case: the promotion's own transcript says 178, the sign-off report
    says 219. The route must not ship."""
    r = G.check(_project(tmp_path, promoted=True, claimed=178,
                         signoff_viols=219))
    assert r["verdict"] == "FAIL" and r["rc"] == 1
    assert r["signoff_drv_violations"] == 219
    assert r["claimed_drv_after"] == 178


def test_293_uncorroborated_promotion_fails(tmp_path):
    """A promotion with NO sign-off report to check it against is exactly the
    failure mode — absence of evidence must not read as PASS."""
    r = G.check(_project(tmp_path, promoted=True, claimed=178))
    assert r["verdict"] == "FAIL" and r["rc"] == 1


def test_293_corroborated_promotion_passes(tmp_path):
    """No false FAIL: when the sign-off agrees, the promotion stands."""
    r = G.check(_project(tmp_path, promoted=True, claimed=178,
                         signoff_viols=0))
    assert r["verdict"] == "PASS" and r["rc"] == 0


def test_293_equal_counts_are_not_a_regression(tmp_path):
    """Only WORSE-than-claimed is a failure; equal is corroboration."""
    r = G.check(_project(tmp_path, promoted=True, claimed=5, signoff_viols=5))
    assert r["verdict"] == "PASS"


def test_293_real_converged_reports_show_zero_drv_violations():
    """Non-vacuity + no-false-positive on real artefacts: the three committed
    converged spm cells must parse to 0 DRV violations, not to a spurious
    count that would make every promotion look like a regression."""
    root = _PROGRAMS.parents[3] / "benchmark-data" / "ic" / "spm"
    seen = 0
    for cell in ("v1.5.58_ihp-sg13g2", "v1.5.65_sky130A", "v1.9.96_gf180mcuD"):
        rpt = root / cell / "reports" / "phase3" / "sta_mcorner_ocv.rpt"
        if not rpt.is_file():
            continue
        seen += 1
        assert G.signoff_drv_violations(rpt.read_text(errors="replace")) == 0
    if seen == 0:
        import pytest
        pytest.skip("converged spm sign-off reports not present in this tree")
