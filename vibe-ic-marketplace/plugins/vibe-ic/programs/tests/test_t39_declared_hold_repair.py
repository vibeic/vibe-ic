"""The repair must see every hold view judged by declared process sign-off."""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import postroute_timing_repair_decision as decision


def _project(tmp_path, ss_slack="-0.50"):
    pnr = tmp_path / "phase3/stage3/pnr"
    sta = tmp_path / "phase3/stage3/sta"
    pnr.mkdir(parents=True)
    sta.mkdir(parents=True)
    (pnr / "routed.def").write_text("VERSION 5.8 ;\n")
    (sta / "post_route_timing.rpt").write_text(
        "# post_route_timing.rpt — SPEF-BASED post-route STA (canonical, #527).\n"
        "=== HOLD corner: process=FF ===\n"
        "STA_BASIS: POST_ROUTE_SPEF\nworst slack min 0.48\n"
        "=== SETUP corner: process=SS ===\nworst slack max 3.24\n"
        "=== HOLD corner: process=SS ===\n"
        f"STA_BASIS: POST_ROUTE_SPEF\nworst slack min {ss_slack}\n"
        "=== HOLD corner: process=TT ===\n"
        "STA_BASIS: POST_ROUTE_SPEF\nworst slack min 0.78\n")
    return tmp_path


def _stance():
    return {"multi_process_corner": True, "report": "sta_mcorner_ocv.rpt",
            "setup_worst_slack_ns": 2.4, "hold_worst_slack_ns": 0.48,
            "violated_corners": []}


def test_ss_nominal_hold_fires_repair_when_ff_min_is_clean(tmp_path):
    project = _project(tmp_path)
    result = decision.decide(_stance(), True, project=project)
    assert result["timing_repair_needed"] is True
    assert result["hold_worst_slack_ns"] == -0.50
    assert "hold:SS" in result["violated_corners"]
    assert result["declared_hold_violations"][0]["report"].endswith(
        "post_route_timing.rpt")


def test_spef_basis_after_a_long_report_header_still_fires(tmp_path):
    project = _project(tmp_path)
    report = project / "phase3/stage3/sta/post_route_timing.rpt"
    report.write_text("# generated report header\n" * 25 + report.read_text())
    assert report.read_text().index("SPEF-BASED post-route STA") > 400
    result = decision.decide(_stance(), True, project=project)
    assert result["timing_repair_needed"] is True
    assert "hold:SS" in result["violated_corners"]


def test_met_and_old_reports_do_not_create_false_trigger(tmp_path):
    project = _project(tmp_path, "0.12")
    assert decision.decide(_stance(), True, project=project)["repair_needed"] is False
    report = project / "phase3/stage3/sta/post_route_timing.rpt"
    report.write_text(report.read_text().replace("0.12", "-0.50"))
    routed = project / "phase3/stage3/pnr/routed.def"
    import os
    os.utime(routed, (report.stat().st_mtime + 2,) * 2)
    assert decision.decide(_stance(), True, project=project)["repair_needed"] is False
