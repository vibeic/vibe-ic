"""A measured DRC input is identified by report binding, hash and GDS top, not stem."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import drc_report_check as check
from test_digital_hardmacro_check import build_gds


@pytest.mark.parametrize("case", ["recorded", "wrong_top", "wrong_layout_hash", "wrong_report_hash", "missing_layout", "unbound", "failed_invocation", "legacy"])
def test_signoff_uses_bound_layout_identity(tmp_path, case):
    name = "physical_cell" if case == "legacy" else "payload"
    rel = f"phase3/stage3/pnr/{name}.gds"
    gds = tmp_path / rel
    gds.parent.mkdir(parents=True)
    gds.write_bytes(build_gds("other_cell" if case == "wrong_top" else "physical_cell"))
    report_rel = "reports/phase3/drc_signoff.rpt"
    report = tmp_path / report_rel
    report.parent.mkdir(parents=True)
    report.write_text("native report fixture\n")
    sha = lambda p: "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()
    entry = {"record": "invocation", "tool": "klayout", "measured": True,
             "exit_code": 0, "inputs": {rel: sha(gds)},
             "outputs": {report_rel: sha(report)}}
    if case == "wrong_layout_hash":
        entry["inputs"][rel] = "sha256:" + "0" * 64
    if case == "wrong_report_hash":
        entry["outputs"][report_rel] = "sha256:" + "0" * 64
    if case == "missing_layout":
        gds.unlink()
    if case == "unbound":
        entry["outputs"] = {"reports/phase3/unrelated.rpt": sha(report)}
    if case == "failed_invocation":
        entry["exit_code"] = 1
    if case != "legacy":
        (tmp_path / "provenance.jsonl").write_text(json.dumps(entry) + "\n")
    payload = {"summary": {"producers": [{"file": report_rel, "producer": "klayout",
               "deck": "/pdk/rules.drc", "is_signoff_deck": True, "top_cell": "physical_cell"}]}}
    findings, summary = check.signoff_verdict(payload, str(tmp_path))
    errors = [f for f in findings if f.get("severity") == "ERROR"]
    if case in ("recorded", "legacy"):
        assert errors == [], (findings, summary)
        assert summary["layout_topcell_match"] is True
    else:
        assert errors, summary
