"""sta_corner_record_completeness_check — per_corner PRE_LAYOUT basis contamination.

The measured defect (a post-route run whose per_corner/ also held Step-10
pre-layout evidence): this gate is the
POST-ROUTE sign-off completeness gate, but its per_corner sweep read
`phase3/stage3/sta/per_corner/sta_*.rpt` and folded every slack into the
PROCESS-axis sign-off corner WITHOUT reading `STA_BASIS`. The same directory
also holds Step-10's PRE-layout multi-corner evidence (stamped
`STA_BASIS: PRE_LAYOUT_ESTIMATE` by `_emit_multi_corner_sta`). Because
`_merge_slack` keeps the WORST datapoint per corner, a genuine pre-layout
SS -0.57 MASKED the true post-route SS -0.08 the OCV report recorded — and on
a design PnR lifts past zero it would FALSE-FAIL a passing sign-off. This is the
#778 basis-contamination disease in a reader #778 never reached.

These tests exercise the PUBLIC contract only (`main(argv)` exit code + verdict
JSON), so the gate stays free to be refactored.

Bidirectional negative control:
  * A  PRE_LAYOUT per_corner report present, post-route sign-off MET
       -> PASS (post-fix). FAILS against the byte-identical pre-fix file.
  * B1 POST_ROUTE per_corner report, MET (regression control)
       -> PASS, unchanged by the fix.
  * B2 POST_ROUTE per_corner report, VIOLATED (anti-swallow control)
       -> FAIL, still caught — the fix excludes ONLY pre-layout, never a real
          post-route per_corner violation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import sta_corner_record_completeness_check as G  # noqa: E402

_DRV_OK = ("SIGNOFF_CHECK_TYPES_REPORTED recovery removal max_slew "
           "min_pulse_width max_capacitance\n")
_LIB_TT = "/pdk/lib/cells__tt_025C_1v80.lib"
_LIB_SS = "/pdk/lib/cells__ss_100C_1v60.lib"
_LIB_FF = "/pdk/lib/cells__ff_n40C_1v95.lib"


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def _declare(run: Path, *, primary: str = "TT") -> None:
    _write(run / "reports/phase3/multi_corner_spef_stance.json", json.dumps({
        "signoff_dimension": "multi_corner_spef",
        "corners_extracted": ["max", "min", "nom"],
        "corner_count": 3, "multi_corner": True,
        "setup_corner": "max", "hold_corner": "min",
        "corner_library_resolution": {
            "axis": "rc_parasitic",
            "liberty_by_corner": {"max": _LIB_TT, "min": _LIB_TT},
            "distinct_library_count": 1, "reported_corner_count": 2,
            "collapsed": True, "unresolved_corners": [],
            "unresolved_reason": "the RC axis varies parasitics only",
            "degradation_disclosure": "RC characterisation, not multi-process.",
        },
    }))
    _write(run / "reports/phase3/mcorner_ocv_stance.json", json.dumps({
        "signoff_dimension": "multi_corner_ocv_process",
        "setup_process_corner": "SS", "hold_process_corner": "FF",
        "multi_process_corner": True,
        "corner_library_resolution": {
            "axis": "process",
            "liberty_by_corner": {"SS": _LIB_SS, "FF": _LIB_FF},
            "distinct_library_count": 2, "reported_corner_count": 2,
            "collapsed": False, "unresolved_corners": [],
            "unresolved_reason": None, "degradation_disclosure": None,
        },
    }))
    _write(run / "phase2/stage2/constraints/pvt_matrix.json", json.dumps({
        "version": "1.0", "primary_corner": primary, "corner_count": 3,
        "multi_corner": True,
        "corners": [
            {"name": "lib__ss_100C_1v40", "label": "SS"},
            {"name": "lib__tt_025C_1v80", "label": "TT"},
            {"name": "lib__ff_n40C_1v95", "label": "FF"},
        ],
    }))


def _multicorner(setup_slack: float, hold_slack: float) -> str:
    return (
        "# Multi-corner SPEF STA (TAPEOUT-SIGNOFF P1)\n"
        "# SETUP corner: max-RC   HOLD corner: min-RC\n"
        "# corners_available: max,min,nom\n"
        f"# corner_liberty: max={_LIB_TT}\n"
        f"# corner_liberty: min={_LIB_TT}\n"
        "# distinct_corner_libraries: 1 across 2 reported corner(s)\n"
        f"=== SETUP (max-RC corner, SPEF=max, liberty={_LIB_TT}) ===\n"
        f"worst slack max {setup_slack}\n"
        "tns max 0.00\n"
        + _DRV_OK +
        f"=== HOLD (min-RC corner, SPEF=min, liberty={_LIB_TT}) ===\n"
        f"worst slack min {hold_slack}\n"
        "tns max 0.00\n"
        + _DRV_OK
    )


def _mcorner_ocv(setup_slack: float, hold_slack: float) -> str:
    return (
        f"=== SETUP corner: process=SS liberty={_LIB_SS}, "
        "SPEF=design.max.spef ===\n"
        "OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV\n"
        f"worst slack max {setup_slack}\n"
        "tns max 0.00\n"
        + _DRV_OK +
        f"=== HOLD corner: process=FF liberty={_LIB_FF}, "
        "SPEF=design.min.spef ===\n"
        "OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV\n"
        f"worst slack min {hold_slack}\n"
        "tns max 0.00\n"
        + _DRV_OK
    )


def _per_corner_ss(setup_slack: float, basis: str) -> str:
    """A single-corner SS per_corner report as _emit_multi_corner_sta writes it:
    report_checks/tns/wns + a STA_BASIS stamp in the body."""
    return (
        f"Startpoint: reg_a (rising edge clocked by clk)\n"
        f"Endpoint: reg_b (rising edge clocked by clk)\n"
        f"                          {setup_slack}   slack "
        f"({'VIOLATED' if setup_slack < 0 else 'MET'})\n"
        f"worst slack max {setup_slack}\n"
        f"tns max 0.00\n"
        + _DRV_OK +
        f"STA_BASIS: {basis}\n"
        f"STA_BASIS_NOTE: fixture\n"
    )


def _nominal(setup_slack: float) -> str:
    return f"worst slack max {setup_slack}\ntns max 0.00\n"


def _run(tmp: Path, name: str) -> Path:
    d = tmp / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _judge(run: Path, tmp: Path):
    out = tmp / f"{run.name}.json"
    rc = G.main([str(run), "--json", str(out)])
    return rc, json.loads(out.read_text())


# ── A: the defect — a PRE_LAYOUT per_corner report must NOT contaminate ──────
def test_pre_layout_per_corner_does_not_contaminate_post_route_signoff(tmp_path):
    """Post-route sign-off is MET (SS +0.10, FF +0.30). A pre-layout SS -0.57
    sharing per_corner/ is Step-10 evidence, not a sign-off corner — it must be
    excluded, so the run PASSES. Against the byte-identical PRE-fix file this
    test FAILS (the -0.57 is folded in and the run false-FAILs)."""
    run = _run(tmp_path, "prelayout_contamination")
    _declare(run)
    _write(run / "phase3/stage3/sta/sta_spef_multicorner.rpt",
           _multicorner(0.10, 0.30))
    _write(run / "phase3/stage3/sta/sta_mcorner_ocv.rpt",
           _mcorner_ocv(0.10, 0.30))
    _write(run / "phase3/stage3/sta/sta_spef_based.rpt", _nominal(0.10))
    # Step-10 pre-layout evidence in the shared dir — the setup-worst corner.
    _write(run / "phase3/stage3/sta/per_corner/sta_SS.rpt",
           _per_corner_ss(-0.57, "PRE_LAYOUT_ESTIMATE"))

    rc, res = _judge(run, tmp_path)

    assert rc == 0, f"expected PASS, got rc={rc}: {res.get('reasons')}"
    assert res["verdict"] == "PASS"
    assert "R3_SIGNOFF_CORNER_VIOLATION" not in res["rules_violated"]
    # The exclusion is surfaced, never a silent drop.
    excluded = res.get("pre_layout_per_corner_excluded") or []
    assert any("per_corner/sta_SS.rpt" in e for e in excluded), excluded


# ── B1: regression control — a healthy POST_ROUTE per_corner still passes ────
def test_post_route_per_corner_met_still_passes(tmp_path):
    """A legitimate POST_ROUTE per_corner report (MET) is read exactly as
    before — the fix touches only PRE_LAYOUT-stamped reports."""
    run = _run(tmp_path, "postroute_met")
    _declare(run)
    _write(run / "phase3/stage3/sta/sta_spef_multicorner.rpt",
           _multicorner(0.10, 0.30))
    _write(run / "phase3/stage3/sta/sta_mcorner_ocv.rpt",
           _mcorner_ocv(0.10, 0.30))
    _write(run / "phase3/stage3/sta/sta_spef_based.rpt", _nominal(0.10))
    _write(run / "phase3/stage3/sta/per_corner/sta_SS.rpt",
           _per_corner_ss(0.20, "POST_ROUTE_SPEF"))

    rc, res = _judge(run, tmp_path)

    assert rc == 0, f"expected PASS, got rc={rc}: {res.get('reasons')}"
    assert res["verdict"] == "PASS"
    assert not (res.get("pre_layout_per_corner_excluded") or [])


# ── B2: anti-swallow control — a real POST_ROUTE per_corner violation FAILS ──
def test_post_route_per_corner_violation_is_still_caught(tmp_path):
    """The over-tightening trap: the fix must NOT swallow a genuine post-route
    per_corner violation. A POST_ROUTE SS -0.80 must STILL FAIL."""
    run = _run(tmp_path, "postroute_violation")
    _declare(run)
    _write(run / "phase3/stage3/sta/sta_spef_multicorner.rpt",
           _multicorner(0.10, 0.30))
    _write(run / "phase3/stage3/sta/sta_mcorner_ocv.rpt",
           _mcorner_ocv(0.10, 0.30))
    _write(run / "phase3/stage3/sta/sta_spef_based.rpt", _nominal(0.10))
    _write(run / "phase3/stage3/sta/per_corner/sta_SS.rpt",
           _per_corner_ss(-0.80, "POST_ROUTE_SPEF"))

    rc, res = _judge(run, tmp_path)

    assert rc == 1, f"expected FAIL, got rc={rc}: {res.get('reasons')}"
    assert res["verdict"] == "FAIL"
    assert "R3_SIGNOFF_CORNER_VIOLATION" in res["rules_violated"]
    assert not (res.get("pre_layout_per_corner_excluded") or [])
