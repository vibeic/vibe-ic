"""Controls for producer stamps and contradictions hidden by matching filenames."""
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import digital_hardmacro_gen as gen
import drc_report_check as drc
from test_digital_hardmacro_check import build_gds
from test_r0915_87_hardmacro_liberty_carries_the_runs_own_timing import _inputs, _fake_sta, ETM


@pytest.mark.parametrize("case", ["postroute", "prelayout", "banner_disagreement"])
def test_setup_stamps_select_the_recorded_inputs(tmp_path, monkeypatch, case):
    _inputs(tmp_path)
    pnr = tmp_path / "phase3/stage3/pnr"
    spef = tmp_path / "phase3/stage3/extracted/spef_corners"
    (pnr / "d_pnr.v").rename(pnr / "payload_repaired.v")
    (spef / "d.max.spef").rename(spef / "payload.max.spef")
    basis = "PRE_LAYOUT_ESTIMATE" if case == "prelayout" else "POST_ROUTE_SPEF"
    stated = "different.max.spef" if case == "banner_disagreement" else "payload.max.spef"
    (tmp_path / "reports/phase3/sta_mcorner_ocv.rpt").write_text(
        "=== SETUP corner: process=SS liberty=/pdk/ss.lib, SPEF=payload.max.spef ===\n"
        f"STA_BASIS: {basis}\nSTA_BASIS_NETLIST: payload_repaired.v\nSTA_BASIS_SPEF: {stated}\nSTA_BASIS_CORNER: max\n"
        "=== HOLD corner: process=FF liberty=/pdk/ff.lib, SPEF=payload.min.spef ===\n"
        "STA_BASIS: POST_ROUTE_SPEF\nSTA_BASIS_NETLIST: payload_repaired.v\nSTA_BASIS_SPEF: payload.min.spef\nSTA_BASIS_CORNER: min\n")
    calls = []
    fake = _fake_sta(ETM)
    def invoke(argv):
        script = Path(argv[-1].split()[-1]).read_text()
        calls.append(script)
        assert f"read_verilog {pnr / 'payload_repaired.v'}" in script
        assert f"read_spef {spef / 'payload.max.spef'}" in script
        assert "link_design d" in script
        return fake(argv)
    monkeypatch.setattr(gen, "_sh", invoke)
    monkeypatch.setattr(gen.shutil, "which", lambda _: "/fixture/sta")
    text, rec = gen.characterise_liberty(tmp_path, "d", "", tmp_path / "hm")
    if case == "postroute":
        assert text and rec["characterised"] is True, rec
        assert len(calls) == 1
    else:
        assert text is None and not rec["characterised"] and not calls


@pytest.mark.parametrize("case", ["layout_hash", "report_hash", "wrong_top", "not_measured"])
def test_matching_filename_cannot_override_recorded_contradiction(tmp_path, case):
    gds = tmp_path / "phase3/stage3/pnr/physical_cell.gds"
    report = tmp_path / "reports/phase3/drc_signoff.rpt"
    gds.parent.mkdir(parents=True)
    report.parent.mkdir(parents=True)
    gds.write_bytes(build_gds("wrong_cell" if case == "wrong_top" else "physical_cell"))
    report.write_text("native fixture\n")
    sha = lambda p: "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()
    row = {"record": "invocation", "tool": "klayout", "measured": case != "not_measured", "exit_code": 0,
           "inputs": {str(gds.relative_to(tmp_path)): "sha256:" + "0" * 64 if case == "layout_hash" else sha(gds)},
           "outputs": {str(report.relative_to(tmp_path)): "sha256:" + "0" * 64 if case == "report_hash" else sha(report)}}
    (tmp_path / "provenance.jsonl").write_text(json.dumps(row) + "\n")
    findings, summary = drc.signoff_verdict({"summary": {"producers": [{
        "file": str(report.relative_to(tmp_path)), "producer": "klayout", "deck": "/pdk/rules.drc",
        "top_cell": "physical_cell", "is_signoff_deck": True}]}}, str(tmp_path))
    assert any(f["severity"] == "ERROR" for f in findings), summary
    assert summary["layout_evidence_tier"] == "none"
