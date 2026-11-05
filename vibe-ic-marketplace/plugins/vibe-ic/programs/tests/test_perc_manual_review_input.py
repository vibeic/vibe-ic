"""Owner review is separate from native PERC measurements and binds current files."""
import json

import pytest



def _write(project, relative, value):
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if not isinstance(value, str) else value)
    return path


@pytest.fixture
def project(tmp_path):
    _write(tmp_path, "reports/phase3/perc_equivalent.json", {
        "verdict": "PERC_EQUIV_PASS", "categories": [
            {"category": "Measured electrical rule", "status": "AUTOMATED", "result": "PASS"},
            {"category": "Device review", "status": "MANUAL_REVIEW", "result": "MANUAL_REVIEW",
             "checklist": [{"item": "Rated device", "confirmed": None},
                           {"item": "Rated connections", "confirmed": None}]}]})
    _write(tmp_path, "reports/phase3/perc_equivalent.rpt", "OVERALL VERDICT: PERC_EQUIV_PASS\n")
    _write(tmp_path, "reports/phase3/PERC_SIGNOFF_MEMO.md", "**Overall verdict:** `PERC_EQUIV_PASS`\n")
    _write(tmp_path, "reports/phase3/native-device.rpt", "native device and connection evidence\n")
    return tmp_path






























def test_writer_directs_manual_review_to_the_input_not_its_generated_report(tmp_path):
    from _hostpaths import require_repo
    from test_phase3_signoff_chain_organic import (
        TestPercEquivalent, _mk_project, _DEF_PADRING, _fake_pdk, runner)

    registry = json.loads(require_repo("vibe-ic-marketplace", "plugins", "vibe-ic",
                                     "flow", "flow109.json").read_text())
    row = next(row for row in registry["rows"] if row["id"] == "D66")
    output = next(p for p in row["profiles"][0]["dispatch"]["native_required_outputs"]
                  if p.endswith("perc_equivalent.json"))
    project = _mk_project(tmp_path, _DEF_PADRING)
    TestPercEquivalent()._seed_subreports(project)
    assert runner._emit_perc_equivalent(project, "chip_top", _fake_pdk(), "", [])
    doc = json.loads((project / output).read_text())
    criteria = [cat["review_criteria"] for cat in doc["categories"] if cat.get("review_criteria")]
    assert criteria
    assert all("input/perc_manual_review.json" in c["record_to"] for c in criteria)
    assert all(item["confirmed"] is None for cat in doc["categories"]
               for item in cat.get("checklist", []))
