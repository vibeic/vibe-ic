"""CR-3: core utilization and placement density have distinct consumers."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as p3  # noqa: E402






@pytest.mark.parametrize("local", [False, True])
def test_pinned_image_default_is_read_at_runtime(tmp_path, monkeypatch, local):
    project = tmp_path / "project"
    reports = project / "reports"
    reports.mkdir(parents=True)
    (reports / "container_image.json").write_text(json.dumps({"container": "pinned-eda"}))
    seen = []

    def run(argv, **kwargs):
        seen.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "37\n", "")

    monkeypatch.setattr(p3._cex, "docker_exec_argv",
                        lambda container, *rest: ["docker", "exec", container, *rest])
    monkeypatch.setattr(p3._cex, "local_exec_mode", lambda _tag: local)
    monkeypatch.setattr(p3.subprocess, "run", run)
    value, source = p3._flow_default_core_util(project)
    assert value == pytest.approx(0.37)
    assert "pinned image" in source and "FP_CORE_UTIL" in source
    assert len(seen) == 1
    assert ("pinned-eda" in seen[0][0]) is (not local)
    assert "Floorplan.config_vars" in " ".join(seen[0][0])


def test_unreadable_image_is_not_read_not_a_number(tmp_path):
    value, source = p3._flow_default_core_util(tmp_path)
    assert value is None
    assert source.startswith("NOT_READ:")


def test_wrong_pinned_image_is_disclosed_not_read(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "container_image.json").write_text(json.dumps({"container": "wrong-eda"}))

    def refuse(*_args):
        raise p3._cex.ContainerImageMismatch("image identity differs")

    monkeypatch.setattr(p3._cex, "docker_exec_argv", refuse)
    monkeypatch.setattr(p3._cex, "local_exec_mode", lambda _tag: False)
    value, source = p3._flow_default_core_util(tmp_path)
    assert value is None
    assert source.startswith("NOT_READ:")
