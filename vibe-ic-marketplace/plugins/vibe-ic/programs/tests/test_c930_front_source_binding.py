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
    _path, rec = _manifest(project)
    assert rec["producer"]["step"] == "Yosys.JsonHeader"
    assert rec["producer"]["exit_code"] == 0
    assert rec["input"]["files"]








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
