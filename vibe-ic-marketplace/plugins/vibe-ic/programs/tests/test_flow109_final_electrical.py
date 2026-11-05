"""Native final-electrical observations survive later missing acquisitions."""
import pytest

import flow109_final_electrical as electrical


@pytest.mark.parametrize("first_status,expected", [("FAIL", "FAIL"), ("PASS", "NOT_MEASURED")])
def test_scan_timing_keeps_observed_result_when_later_mode_is_missing(
        tmp_path, monkeypatch, first_status, expected):
    for name in ("layout.def", "layout.odb", "netlist.v", "rc.spef", "shift.sdc", "cells.lib"):
        (tmp_path / name).write_text("native input\n")
    state = {"def": "layout.def", "odb": "layout.odb", "nl": "netlist.v",
             "spef": {"nom": "rc.spef"}}
    groups = [{"mode": mode, "scenarios": [{"corner": "nom"}],
               "libraries": ["cells.lib"], "sdc": sdc}
              for mode, sdc in (("shift", "shift.sdc"), ("capture", "missing.sdc"))]
    monkeypatch.setattr(electrical.signoff, "run", lambda *args, **kwargs: {"sta": str(tmp_path)})
    monkeypatch.setattr(electrical.signoff, "corner_timing", lambda folder: {"nom": {}})
    monkeypatch.setattr(electrical.signoff, "judge_timing", lambda rows: {"verdict": first_status})
    result = electrical._scan_timing(tmp_path, groups,
                                    {"image": "native", "pdk_root": str(tmp_path), "pdk": "neutral"}, state)
    assert result["status"] == expected
    assert result["modes"]["shift"][0]["status"] == first_status
    assert result["modes"]["capture"][0]["status"] == "NOT_MEASURED"


@pytest.mark.parametrize("drop_pct,ir_status", [(5.0, "PASS"), (5.0001, "FAIL")])
def test_native_ir_uses_original_inclusive_five_percent_limit(drop_pct, ir_status):
    report = ("=== PSM_NET supply ===\nWorstcase IR drop: 0.09 V\n"
              f"Percentage drop : {drop_pct} %\nWorst utilization : 10 %\n"
              "Violations : 0\nNo J-limit (skipped): 0\nVerdict : PASS\n")
    observed = electrical.judge_ir_em(report, ["supply"])["supply"]
    assert observed["ir_status"] == ir_status
    assert observed["em_status"] == "PASS"


def test_missing_native_psm_measurement_is_unmeasured():
    observed = electrical.judge_ir_em("", ["supply"])["supply"]
    assert observed["ir_status"] == observed["em_status"] == "NOT_MEASURED"
