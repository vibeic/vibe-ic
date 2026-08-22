"""v0.2.89 — #454: cross-design byte-identity gate.

The 4-IC canned reports were only caught by a manual md5 sweep; #436
fixed the emitters but nothing prevented recurrence. Pins:

  * report-class artifacts byte-identical across DIFFERENT designs →
    CROSS_DESIGN_IDENTICAL_ARTIFACT ERROR (the canned shape);
  * legit verdict-wrapper exemption is CONDITIONAL: an allowlisted
    basename is exempt ONLY when its evidence pointer targets differ
    per design — a wrapper whose targets do NOT differ is canned too;
  * per-design content (differs) → clean; shared inputs exempt;
  * < 2 projects → vacuous rc 2.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import cross_design_identity_check as CDI  # noqa: E402


def _proj(tmp_path, name, coverage_text, wrapper_evidence_body):
    p = tmp_path / name
    rpt = p / "reports" / "phase2" / "coverage"
    rpt.mkdir(parents=True)
    (rpt / "coverage_actual.json").write_text(coverage_text)
    r3 = p / "reports" / "phase3"
    r3.mkdir(parents=True)
    (r3 / "ir_drop.rpt").write_text(wrapper_evidence_body)
    (r3 / "ir_drop.json").write_text(json.dumps({
        "tool": "psm", "verdict": "PASS",
        "source": "reports/phase3/ir_drop.rpt"}))
    return p


def test_canned_report_across_designs_fails(tmp_path):
    a = _proj(tmp_path, "alpha", '{"scenarios": ["GET_ID"]}', "ir A")
    b = _proj(tmp_path, "beta", '{"scenarios": ["GET_ID"]}', "ir B")
    rep = CDI.audit([a, b], allow={"ir_drop.json"})
    assert rep["rc"] == 1
    assert any(f["rule"] == "CROSS_DESIGN_IDENTICAL_ARTIFACT"
               and "coverage_actual.json" in f["message"]
               for f in rep["findings"])


def test_wrapper_with_differing_targets_is_exempt(tmp_path):
    # ir_drop.json byte-identical, but each design's ir_drop.rpt differs
    a = _proj(tmp_path, "alpha", '{"s": "a"}', "ir body ALPHA")
    b = _proj(tmp_path, "beta", '{"s": "b"}', "ir body BETA")
    rep = CDI.audit([a, b], allow={"ir_drop.json"})
    assert rep["rc"] == 0, rep["findings"]
    assert any(w["path"].endswith("ir_drop.json")
               for w in rep["allowlisted_wrappers_ok"])


def test_wrapper_with_same_targets_is_not_exempt(tmp_path):
    a = _proj(tmp_path, "alpha", '{"s": "a"}', "same ir body")
    b = _proj(tmp_path, "beta", '{"s": "b"}', "same ir body")
    rep = CDI.audit([a, b], allow={"ir_drop.json"})
    assert rep["rc"] == 1
    assert any(f["rule"] == "CROSS_DESIGN_WRAPPER_NOT_EXEMPT"
               for f in rep["findings"])


def test_per_design_content_clean(tmp_path):
    a = _proj(tmp_path, "alpha", '{"scenarios": ["A1"]}', "ir A")
    b = _proj(tmp_path, "beta", '{"scenarios": ["B1"]}', "ir B")
    rep = CDI.audit([a, b], allow={"ir_drop.json"})
    assert rep["rc"] == 0


def test_fewer_than_two_projects_vacuous(tmp_path):
    a = _proj(tmp_path, "alpha", "{}", "x")
    assert CDI.audit([a], allow=set())["rc"] == 2
