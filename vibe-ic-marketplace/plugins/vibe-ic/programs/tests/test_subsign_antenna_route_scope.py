"""Antenna sign-off reads reports for the shipped route and tool output only."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eda_report_audit import _check_antenna


def _tool_report(root: Path, *, clean: bool) -> None:
    out = root / "reports" / "phase3"
    out.mkdir(parents=True)
    n = 0 if clean else 2
    (out / "antenna.rpt").write_text(
        "# OpenROAD check_antennas tool output\n"
        f"antenna check: {n} net violations, {n} pin violations\n"
        f"antenna clean: {'YES' if clean else 'NO'}\n" + "# data\n" * 40)




def test_rollback_metadata_is_not_an_antenna_tool_report(tmp_path):
    _tool_report(tmp_path, clean=True)
    out = tmp_path / "reports" / "phase3"
    (out / "antenna_repair_transaction.json").write_text(json.dumps({
        "program": "phase3_one_shot_runner:_pnr_rollback_refused_antenna_repair",
        "status": "ROLLED_BACK", "route_verified_at_ship": True,
        "note": "this is runner metadata, not a tool report" * 10,
    }))
    r = _check_antenna(tmp_path)
    assert r.passed, [f.rule for f in r.findings]
    assert r.summary["files_found"] == 1


def test_real_shipped_route_antenna_violation_still_fails(tmp_path):
    _tool_report(tmp_path, clean=False)
    r = _check_antenna(tmp_path)
    assert not r.passed
    assert r.summary["violations"] == 4
