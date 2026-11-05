"""FRONT-I1: current source obligations require a current native JSON binding.

Native execution is substituted only at subprocess.run with checked-in Yosys
output. Production discovery, fingerprinting, publication, and the actual
Step-3 CLI consumers execute; no Docker/EDA/native rerun is claimed.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _cdc_netlist as cn
import clock_domain_reg_crossing_check as crossing
import test_t91_step3_cdc_netlist_front_end as fixtures


def _fresh(tmp_path):
    return fixtures._project(tmp_path, "fresh", fixtures.FIX / "clean_sync.v",
                             None, fixtures.FIX / "clean_sync.json")


def _manifest(project):
    path = project / cn.NETLIST_MANIFEST_REL
    return path, json.loads(path.read_text())


def _rules(result):
    return {row.rule for row in result.findings if row.severity == "ERROR"}


def test_fresh_captured_native_json_passes_the_default_consumer(tmp_path):
    project = _fresh(tmp_path)
    rc, doc = fixtures._run("clock_domain_reg_crossing_check", str(project))
    assert rc == 0 and doc["passed"] is True, doc
    assert doc["summary"]["front_end"] == "netlist"
    assert doc["summary"]["netlist_input_fingerprint"]
    _path, rec = _manifest(project)
    assert rec["producer"]["step"] == "Yosys.JsonHeader"
    assert rec["producer"]["exit_code"] == 0
    assert rec["input"]["files"]


@pytest.mark.parametrize("change", ["changed", "deleted", "added", "header"],
                         ids=["changed-source", "deleted-source", "added-source", "added-header"])
def test_immutable_clean_json_cannot_hide_a_changed_source_population(tmp_path, change):
    project = _fresh(tmp_path)
    path = project / cn.NETLIST_REL
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    source = next((project / "phase2/stage1/rtl").glob("*.v"))
    if change == "changed":
        source.write_text(source.read_text() + "\n// current source changed\n")
    elif change == "deleted":
        source.unlink()
    elif change == "added":
        (source.parent / "extra.v").write_text("module extra; endmodule\n")
    else:
        (source.parent / "options.vh").write_text("`define SELECTED_FEATURE 1\n")
    result = crossing.audit(str(project))
    assert not result.passed, result.summary
    assert _rules(result) & {"CDC_NETLIST_STALE", "CDC_NETLIST_NO_RTL"}
    assert result.summary["netlist_read"] is False
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("change", ["missing", "partial", "options", "top", "run", "output", "log"],
                         ids=["missing-binding", "partial-read", "wrong-options", "wrong-top",
                              "wrong-producer-run", "changed-json", "changed-log"])
def test_missing_or_inconsistent_native_binding_refuses_without_regex_fallback(tmp_path, change):
    project = _fresh(tmp_path)
    path, rec = _manifest(project)
    if change == "missing":
        path.unlink()
    elif change == "partial":
        rec["input"]["files"] = []
    elif change == "options":
        rec["input"]["options"]["sv"] = False
    elif change == "top":
        rec["input"]["options"]["requested_top"] = "other_top"
    elif change == "run":
        rec["producer"]["argv"] = ["yosys", "-q", "-p", "different read"]
    elif change == "output":
        output = project / cn.NETLIST_REL
        output.write_text(output.read_text() + "\n")
    else:
        (project / cn.NETLIST_LOG_REL).write_text("changed native invocation\n")
    if change not in ("missing", "output", "log"):
        path.write_text(json.dumps(rec))
    result = crossing.audit(str(project))
    assert not result.passed and result.summary["netlist_read"] is False
    assert _rules(result) & {"CDC_NETLIST_STALE", "CDC_NETLIST_UNBOUND", "CDC_NETLIST_TOP_MISMATCH"}
    assert "front_end_comparison" not in result.summary


def test_current_declared_top_and_switch_options_invalidate_a_prior_binding(tmp_path):
    project = _fresh(tmp_path)
    docs = project / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"top_module": "other_top"}))
    result = crossing.audit(str(project))
    assert not result.passed and "CDC_NETLIST_STALE" in _rules(result)
    project = _fresh(tmp_path / "switch")
    (project / "phase3").mkdir()
    (project / "phase3/librelane_switch.json").write_text(json.dumps(
        {"steps": {"3": "librelane"}, "image": "changed-declared-image"}))
    assert "CDC_NETLIST_STALE" in _rules(crossing.audit(str(project)))


def test_partial_native_read_refuses_before_any_tool_dispatch(tmp_path, monkeypatch):
    project = _fresh(tmp_path)
    (project / "phase2/stage1/rtl/added.v").write_text("module added; endmodule\n")
    def unexpected(*args, **kwargs):
        pytest.fail("a partial read must refuse before native dispatch")
    monkeypatch.setattr(cn.subprocess, "run", unexpected)
    with pytest.raises(cn.Refusal, match="CDC_NETLIST_PARTIAL_SOURCES"):
        cn.build(project, [project / "phase2/stage1/rtl/clean_sync.v"], "clean_sync")
    assert not (project / cn.NETLIST_REL).exists()
    assert not (project / cn.NETLIST_MANIFEST_REL).exists()


@pytest.mark.parametrize("failure", ["native-failed", "source-changed-during-run"])
def test_unsuccessful_producer_cannot_leave_prior_admission(tmp_path, monkeypatch, failure):
    project = _fresh(tmp_path)
    source = project / "phase2/stage1/rtl/clean_sync.v"
    captured = fixtures._captured_tool(fixtures.FIX / "clean_sync.json")

    def run(argv, **kwargs):
        if failure == "native-failed":
            return subprocess.CompletedProcess(argv, 1, "", "captured native failure\n")
        result = captured(argv, **kwargs)
        source.write_text(source.read_text() + "\n// changed during producer\n")
        return result

    monkeypatch.setattr(cn.shutil, "which", lambda _tool: "/captured/yosys")
    monkeypatch.setattr(cn.subprocess, "run", run)
    expected = "CDC_NETLIST_BUILD_FAILED" if failure == "native-failed" else "CDC_NETLIST_STALE"
    with pytest.raises(cn.Refusal, match=expected):
        cn.build(project, [source], "clean_sync")
    assert not (project / cn.NETLIST_REL).exists()
    assert not (project / cn.NETLIST_MANIFEST_REL).exists()
    result = crossing.audit(str(project))
    assert not result.passed and result.summary["netlist_read"] is False
