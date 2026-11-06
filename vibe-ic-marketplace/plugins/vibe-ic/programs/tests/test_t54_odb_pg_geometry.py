"""Via metal enclosing a PSM edge supplies its real EM cross section."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import em_current_density_check as E  # noqa: E402
import phase3_one_shot_runner as R  # noqa: E402


def test_via_metal_geometry_changes_width_basis_but_keeps_true_failure(tmp_path):
    csv = tmp_path / "em_segments.csv"
    csv.write_text(
        "Node0 Layer,Node0 X location,Node0 Y location,Node1 Layer,"
        "Node1 X location,Node1 Y location,Current\n"
        "M3,10,5,M3,10,8,0.002589\n")
    jmax = tmp_path / "jmax.json"
    jmax.write_text(json.dumps({"layers": {"M3": {
        "kind": "routing", "width_um": 0.28,
        "jmax_mA_per_um": 0.67}}}))
    geometry = tmp_path / "em_pg_geometry.tsv"
    geometry.write_text(
        "net\tlayer\tx0_um\ty0_um\tx1_um\ty1_um\tsource\n"
        "SUP\tM3\t9.29\t4.5\t10.71\t8.5\tvia_metal\n")
    verdict, report = E.evaluate(
        csv, jmax, None, 0.1, 2.0, "SUP", 20,
        pg_geometry_path=geometry)
    assert verdict == "FAIL"
    assert report["summary"]["odb_pg_geometry_width_uses"] == 1
    assert report["offenders"][0]["width_source"] == "odb_pg_metal_geometry"
    assert report["offenders"][0]["width_um"] == pytest.approx(1.42)
    assert report["offenders"][0]["utilization"] > 1






def test_em_ab_refuses_empty_tool_pass_and_discloses_utilization_difference(tmp_path):
    rpt = R._pl.reports_phase3_dir(tmp_path)
    rpt.mkdir(parents=True)
    subject = {"subject_def_sha256": "abc"}
    gate = {"jmax_screen": {"verdict": "PASS", "offender_count": 0,
                            "summary": {"worst_utilization": 0.01}}}
    (rpt / "em.json").write_text(json.dumps(subject))
    (rpt / "em_current_authority.json").write_text(json.dumps(gate))
    tool = {"def_sha256": "abc", "verdict": "MEASURED",
            "nets": {"VPWR": {"checked": 0, "no_limit": 1,
                               "violated": 0, "worst_ratio": None}}}
    (rpt / "em_openroad_density.json").write_text(json.dumps(tool))
    E.emit_openroad_ab(tmp_path, [])
    assert json.loads((rpt / "em_openroad_ab.json").read_text())["verdict"] == "NOT_MEASURED"
    tool["nets"]["VPWR"] = {"checked": 1, "no_limit": 0,
                              "violated": 0, "worst_ratio": 0.13}
    (rpt / "em_openroad_density.json").write_text(json.dumps(tool))
    notes = []
    E.emit_openroad_ab(tmp_path, notes)
    ab = json.loads((rpt / "em_openroad_ab.json").read_text())
    assert ab["verdict"] == "MEASURED"
    assert ab["offender_count_agrees"] is True
    assert ab["utilization_agrees"] is False
    assert notes
