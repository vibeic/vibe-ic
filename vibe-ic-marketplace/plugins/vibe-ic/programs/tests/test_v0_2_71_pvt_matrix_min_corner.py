"""v0.2.71 — #442: PVT matrix substance + single-corner disclosure.

Pins:
  * pvt_matrix.json with corners=[] FAILs pvt_matrix_check (an empty
    list is not a PVT matrix);
  * exactly 1 corner → exit 0 with verdict SINGLE_CORNER_ONLY (honest,
    never presented as multi-corner);
  * a self-contradictory multi_corner:true claim with <2 corners FAILs;
  * the runner stamps corner_count / multi_corner / coverage into the
    emitted matrix (source pin);
  * eda_report_audit STA mode discloses STA_SINGLE_CORNER_ONLY when no
    >=2-distinct per-corner evidence exists (advisory, not a FAIL).

chip-AGNOSTIC: structural JSON shape only.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import eda_report_audit as ERA   # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent.parent










def test_sta_single_corner_disclosure(tmp_path):
    sta = tmp_path / "phase3" / "stage3" / "sta"
    sta.mkdir(parents=True)
    (sta / "post_route_timing.rpt").write_text(
        "Startpoint: a\nPath Type: max\nslack (MET)\nOpenSTA\n")
    r = ERA._check_sta(tmp_path)
    assert r.summary["multi_corner_executed"] is False
    disc = [f for f in r.findings if f.rule == "STA_SINGLE_CORNER_ONLY"]
    assert disc and disc[0].severity == "WARNING"  # advisory, not ERROR
    assert r.summary["multi_corner_claim_not_broken"] is True  # no broken claim


def test_sta_two_distinct_corners_no_disclosure(tmp_path):
    sta = tmp_path / "phase3" / "stage3" / "sta"
    pc = sta / "per_corner"
    pc.mkdir(parents=True)
    (sta / "post_route_timing.rpt").write_text(
        "Startpoint: a\nPath Type: max\nslack (MET)\nOpenSTA\n")
    (pc / "sta_SS.rpt").write_text("Path Type: max\nslack (MET) 1.2\n")
    (pc / "sta_FF.rpt").write_text("Path Type: max\nslack (MET) 3.4\n")
    r = ERA._check_sta(tmp_path)
    assert r.summary["multi_corner_executed"] is True
    assert not any(f.rule == "STA_SINGLE_CORNER_ONLY" for f in r.findings)
