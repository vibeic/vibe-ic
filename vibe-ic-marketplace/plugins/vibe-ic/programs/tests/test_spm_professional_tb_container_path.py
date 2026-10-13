"""Regression for the native SPM professional-TB container path.

The producer creates the bundle using the host project path.  A container
consumer must receive that path after the runner's bind-mount translation;
passing the host spelling makes ``cd`` fail before cocotb starts.  A genuinely
missing generated bundle remains an explicit refusal and is never dispatched.
"""
from __future__ import annotations

import json
import shlex
import sys
import types
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import design_one_shot_runner as D  # noqa: E402


_PASS_XML = (
    '<testsuites><testsuite name="spm" tests="1" failures="0" '
    'errors="0" skipped="0"><testcase name="professional"/>'
    '</testsuite></testsuites>'
)


def _install_bundle_generator(monkeypatch, out: Path, *, rtl_files=1):
    gen = {
        "status": "PASS",
        "ic_class": "digital_arithmetic_primitive",
        "dut_kind": "serial_stream",
        "reference_model_tier": "streaming_bounded_latency",
        "out_dir": str(out),
        "rtl_files": rtl_files,
        "files": ["tb_spm.py", "Makefile"],
    }
    monkeypatch.setitem(
        sys.modules, "professional_tb_gen",
        types.SimpleNamespace(generate=lambda _project: gen),
    )


def test_container_dispatch_consumes_the_mount_translated_bundle_path(
        tmp_path, monkeypatch):
    """The native failure's host path must not reach the container shell."""
    project = tmp_path / "host-project"
    out = project / "phase2/stage1/sim_professional/spm"
    out.mkdir(parents=True)
    _install_bundle_generator(monkeypatch, out)

    container_root = "/foss/designs/spmcanonical1006r2"
    monkeypatch.setattr(
        D, "_container_mounts",
        lambda _container: [(str(project), container_root)],
    )
    monkeypatch.setattr(D, "_professional_tb_exec_site", lambda _c: "container")
    monkeypatch.setattr(D, "_professional_tb_sim_differential",
                        lambda *_args: None)
    calls = {}

    def _docker_exec(container, cmd, timeout=600, *, marker=None, log_path=None):
        calls.update(container=container, cmd=cmd, timeout=timeout,
                     marker=marker, log_path=log_path)
        (out / "results.xml").write_text(_PASS_XML)
        return 0, "PROFESSIONAL_TB PASS 208/208", ""

    monkeypatch.setattr(D, "_docker_exec", _docker_exec)
    step = D.step_professional_tb_gen(project, "spm", "vibeic-eda")

    expected = f"{container_root}/phase2/stage1/sim_professional/spm"
    assert step.status == "PASS", step.detail
    assert calls["container"] == "vibeic-eda"
    assert calls["cmd"] == f"cd {shlex.quote(expected)} && make -B SIM=icarus"
    assert str(out) not in calls["cmd"]
    assert calls["marker"] == expected
    assert calls["log_path"] == str(out / "cocotb_run.log")


def test_missing_generated_bundle_is_refused_without_dispatch(
        tmp_path, monkeypatch):
    """A producer path that is truly absent stays named NOT_MEASURED."""
    project = tmp_path / "project"
    project.mkdir()
    missing = project / "phase2/stage1/sim_professional/spm"
    _install_bundle_generator(monkeypatch, missing)
    dispatched = []
    monkeypatch.setattr(
        D, "_professional_tb_exec_site",
        lambda _container: dispatched.append(True) or "container",
    )

    step = D.step_professional_tb_gen(project, "spm", "vibeic-eda")
    report = json.loads(
        (project / "reports/phase2/gates/professional_tb.json").read_text()
    )
    assert step.status == "NOT_MEASURED"
    assert "not a directory" in report["reason"]
    assert dispatched == []
