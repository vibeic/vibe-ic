"""Unit tests for `phase2_verify_aggregate.py`."""
import importlib
import json
import subprocess
import sys
from pathlib import Path
import pytest

from _shipped_version import shipped_plugin_version  # noqa: E402  (#800)
mod = importlib.import_module("phase2_verify_aggregate")


class TestArtifactScan:
    def test_missing_returns_false(self, tmp_path):
        out = mod.scan_artifacts(tmp_path)
        assert all(not a.present for a in out)

    def test_present_returns_true(self, tmp_path):
        d = tmp_path / "phase2" / "stage1" / "rtl"
        d.mkdir(parents=True)
        (d / "core.v").write_text("module core; endmodule\n")
        out = mod.scan_artifacts(tmp_path)
        rtl = [a for a in out if a.name == "rtl"][0]
        assert rtl.present


class TestAggregator:
    def _c(self, name, ec):
        return mod.CheckResult(name=name, exit_code=ec, stdout_tail="")

    def _a(self, name, present):
        return mod.ArtifactPresence(name=name, path=f"/x/{name}",
                                      present=present)

    def test_clean_run(self):
        artifacts = [self._a("rtl", True), self._a("sof", True), self._a("tb", True)]
        rep = mod.aggregate(mod.Path("/x"), artifacts, [self._c("a", 0)])
        assert rep.verdict == "PASS"

    def test_missing_artifact_fails(self):
        artifacts = [self._a("rtl", False), self._a("sof", True), self._a("tb", True)]
        rep = mod.aggregate(mod.Path("/x"), artifacts, [self._c("a", 0)])
        assert rep.verdict == "FAIL"

    def test_failed_check_fails(self):
        artifacts = [self._a("rtl", True), self._a("sof", True), self._a("tb", True)]
        rep = mod.aggregate(mod.Path("/x"), artifacts, [self._c("a", 1)])
        assert rep.verdict == "FAIL"

    def test_attribution(self):
        rep = mod.aggregate(mod.Path("/x"), [], [])
        d = rep.as_dict()
        assert d["emitted_by"] == \
            f"phase2_verify_aggregate v{shipped_plugin_version()}"


def _native_project(tmp_path):
    from programs.tests._route_fixture import stage_owner_route
    project = tmp_path / "project"
    stage_owner_route(project, "ic")
    for rel in ("phase2/stage1/rtl", "phase2/stage2/synth",
                "phase2/stage1/sim_full_stack", "phase1/generated_docs"):
        (project / rel).mkdir(parents=True, exist_ok=True)
    rtl = "module core(input wire clk, output wire gpio); assign gpio=clk; endmodule\n"
    (project / "phase2/stage1/rtl/core.v").write_text(rtl)
    (project / "phase2/stage2/synth/core_synth.v").write_text(rtl)
    (project / "phase2/stage1/sim_full_stack/tb_core.v").write_text(
        "module tb_core; reg clk; wire gpio; core dut(clk,gpio); endmodule\n")
    (project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "core", "ports": [
            {"name": "clk", "direction": "input", "width": 1},
            {"name": "gpio", "direction": "output", "width": 1}]}))
    return project


def _native_aggregate(project, *extra):
    output = project / "aggregate.json"
    result = subprocess.run([sys.executable, mod.__file__, str(project),
                             "--out-json", str(output), "--strict", *extra],
                            capture_output=True, text=True, timeout=180)
    assert output.is_file(), result.stdout + result.stderr
    return result, json.loads(output.read_text())


def test_public_ic_aggregate_uses_real_child_clis_and_current_artifacts(tmp_path):
    result, doc = _native_aggregate(_native_project(tmp_path))
    assert result.returncode == 0 and doc["verdict"] == "PASS", doc
    assert doc["verification_target"] == "ic"
    assert all(row["exit_code"] == 0 for row in doc["checks"]), doc
    for row in doc["checks"]:
        assert row["argv"] and "stderr_tail" in row
    assert not any("sof" in row["path"] for row in doc["artifacts"])


@pytest.mark.parametrize("kind", ["netlist", "tb", "empty_rtl", "spec_mismatch", "lint"])
def test_native_aggregate_preserves_real_missing_and_checker_failures(tmp_path, kind):
    project = _native_project(tmp_path)
    if kind == "netlist":
        (project / "phase2/stage2/synth/core_synth.v").unlink()
    elif kind == "tb":
        (project / "phase2/stage1/sim_full_stack/tb_core.v").unlink()
    elif kind == "empty_rtl":
        (project / "phase2/stage1/rtl/core.v").unlink()
    elif kind == "spec_mismatch":
        path = project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
        doc = json.loads(path.read_text())
        doc["ports"].append({"name": "required", "direction": "input", "width": 1})
        path.write_text(json.dumps(doc))
    else:
        path = project / "phase2/stage1/rtl/core.v"
        path.write_text('module core(input wire clk, output wire gpio);\n'
                        'wire undriven;\nassign gpio=undriven;\nendmodule\n')
    result, doc = _native_aggregate(project)
    assert result.returncode == 1 and doc["verdict"] == "FAIL", doc
    if kind in ("spec_mismatch", "lint"):
        check = "spec_conformance" if kind == "spec_mismatch" else "rtl_hygiene_lint"
        row = next(row for row in doc["checks"] if row["name"] == check)
        assert row["exit_code"] == 1 and row["reason_class"] == "CHECK_FAILED", row
    else:
        assert any(not row["present"] for row in doc["artifacts"]), doc


def test_fpga_artifact_is_required_only_for_explicit_fpga_review(tmp_path):
    project = _native_project(tmp_path)
    result, doc = _native_aggregate(project, "--target", "fpga")
    assert result.returncode == 1 and any(not a["present"] and a["name"] == "sof"
                                        for a in doc["artifacts"]), doc
    bitstream = project / "phase2/stage1/fpga/output_files/core.sof"
    bitstream.parent.mkdir(parents=True)
    bitstream.write_bytes(b"fixture-bitstream-artifact")
    result, doc = _native_aggregate(project, "--target", "fpga")
    assert result.returncode == 0, doc
    assert doc["verification_target"] == "fpga"


def test_child_usage_failure_retains_actual_argv_and_stderr(tmp_path, monkeypatch):
    project = _native_project(tmp_path)
    observed = []
    def usage(argv, **kwargs):
        observed.append(argv)
        return subprocess.CompletedProcess(argv, 2, "", "usage: required --spec")
    monkeypatch.setattr(mod.subprocess, "run", usage)
    row = mod._run_check("spec_conformance", "spec_conformance_check.py", [], project)
    assert row.exit_code == 2 and row.argv == observed[0]
    assert "required --spec" in row.stderr_tail
    assert row.reason_class == "INVOCATION_ERROR"
