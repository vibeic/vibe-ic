"""Recorded identity must tolerate append-only history and optional producer top."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import drc_report_check as drc
from test_digital_hardmacro_check import build_gds


@pytest.mark.parametrize("case", ["new_valid", "new_invalid", "no_report_top", "python310_hash_api"])
def test_recorded_binding_compatibility(tmp_path, monkeypatch, case):
    layout = tmp_path / "phase3/stage3/pnr/payload.gds"
    report = tmp_path / "reports/phase3/drc_signoff.rpt"
    layout.parent.mkdir(parents=True)
    report.parent.mkdir(parents=True)
    layout.write_bytes(build_gds("physical_cell"))
    report.write_text("current report\n")
    sha = lambda p: "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()
    rel = str(report.relative_to(tmp_path))
    row = {"record": "invocation", "measured": True, "exit_code": 0,
           "tool": "magic" if case == "no_report_top" else "klayout",
           "inputs": {str(layout.relative_to(tmp_path)): sha(layout)},
           "outputs": {rel: sha(report)}}
    rows = []
    if case in ("new_valid", "new_invalid"):
        old = dict(row, outputs={rel: "sha256:" + "0" * 64})
        rows = [old]
    if case == "new_invalid":
        rows = [row]
        row = dict(row, outputs={rel: "sha256:" + "0" * 64})
    rows.append(row)
    (tmp_path / "provenance.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    if case == "python310_hash_api":
        monkeypatch.delattr(hashlib, "file_digest", raising=False)
    try:
        result = drc.signoff_verdict({"summary": {"producers": [{"file": rel,
            "producer": row["tool"], "deck": "/pdk/rules.drc", "is_signoff_deck": True,
            "top_cell": None if case == "no_report_top" else "physical_cell"}]}}, str(tmp_path))
    except AttributeError as exc:
        result = str(exc)
    assert isinstance(result, tuple), result
    findings, summary = result
    errors = [f for f in findings if f["severity"] == "ERROR"]
    if case == "new_invalid":
        assert errors and summary["layout_evidence_tier"] == "none"
    else:
        assert errors == [], (findings, summary)
        assert summary["layout_evidence_tier"] == "invocation"
        assert summary["layout_topcell_match"] is (None if case == "no_report_top" else True)
