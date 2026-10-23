#!/usr/bin/env python3
"""Regression: the top runner must produce the stage-analog audit before Step 14.

The final compliance audit is a judge, not a producer belonging to the run.
If it is the first process to write ``stage_analog_compliance.json``, Step 14
correctly excludes that file as ``audit_created`` and cannot credit it.
"""
from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest


PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))


@pytest.fixture(autouse=True)
def _restore_process_runtime_tree_state():
    """The front door normally exits after activating its retained tree.

    This test calls ``main`` in-process, so restore the process state that an
    actual CLI process would discard on exit.  In particular, do not let its
    retained modules answer later live-source identity tests.
    """
    before_path = list(sys.path)
    before_env = dict(os.environ)
    before_modules = dict(sys.modules)
    before_dont_write = sys.dont_write_bytecode
    runner_before = sys.modules.get("vibe_ic_one_shot_runner")
    runner_state = None
    if runner_before is not None:
        runner_state = {
            name: getattr(runner_before, name)
            for name in ("PROGRAMS_DIR", "_RUNTIME_PROGRAM_TREE", "__file__")
        }
    yield
    sys.path[:] = before_path
    os.environ.clear()
    os.environ.update(before_env)
    sys.dont_write_bytecode = before_dont_write
    for name in set(sys.modules) - set(before_modules):
        module = sys.modules.get(name)
        path = str(getattr(module, "__file__", "") or "")
        if "/.vibeic/runtime-program-trees/" in path:
            sys.modules.pop(name, None)
    for name, module in before_modules.items():
        if sys.modules.get(name) is not module:
            sys.modules[name] = module
    if runner_before is not None and runner_state is not None:
        for name, value in runner_state.items():
            setattr(runner_before, name, value)


def test_runner_produces_scoped_analog_audit_after_analog(tmp_path, monkeypatch):
    import vibe_ic_one_shot_runner as runner

    project = tmp_path / "project"
    analog = project / "phase3" / "analog"
    analog.mkdir(parents=True)
    (analog / "analog_block_list.json").write_text(
        json.dumps({"blocks": [{"name": "converter"}]}) + "\n")
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "chip_top.v").write_text("module chip_top(); endmodule\n")
    # owner route rule 2026-09-28 (ICROUTE)
    from _route_fixture import stage_owner_route
    stage_owner_route(project, "ic")

    from test_the_front_door_rollup_edges import _report, _save_complete_acceptance
    calls: list[tuple[str, str, list[str]]] = []
    native_subprocess = runner.subprocess.run

    def record(argv, **kwargs):
        name = Path(argv[1]).stem if len(argv) > 1 else ""
        phase_names = {
            "analog_one_shot_runner", "phase2_one_shot_runner",
            "design_one_shot_runner", "phase3_one_shot_runner",
            "flow_compliance_check", "analog_acceptance_tb_gen",
        }
        if name not in phase_names:
            return native_subprocess(argv, **kwargs)
        args = list(argv[2:])
        calls.append(("controlled phase", name, args))
        if name == "analog_one_shot_runner":
            _report(project, "analog_one_shot.json", {"verdict": "PASS"})
            _save_complete_acceptance(project, "A2", "PASS", runner=name)
        elif name in {"phase2_one_shot_runner", "design_one_shot_runner"}:
            _report(project, "phase2_one_shot.json", {"verdict": "PASS"})
            _save_complete_acceptance(project, "13", "PASS",
                                      runner="design_one_shot_runner")
        elif name == "flow_compliance_check":
            out = Path(args[args.index("--json") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({"verdict": "FAIL"}) + "\n")
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    # Keep the real _run_phase retention seam. Control only child outcomes.
    monkeypatch.setattr(runner.subprocess, "run", record)
    monkeypatch.setattr(runner, "_capture_container_image", lambda *_: {})
    monkeypatch.setattr(runner, "_capture_pdk_revision", lambda *_: {})
    monkeypatch.setattr(sys, "argv", [
        "vibe_ic_one_shot_runner", str(project), "--route", "ic",
        "--skip-phase1",
        "--no-dashboard",
    ])

    # Analog and Phase 2 have current accepted control reports. Phase 3
    # deliberately writes none: its zero exit cannot create a whole-flow PASS.
    rc = runner.main()
    _doc = json.loads(
        (project / "reports" / "orchestrator" / "vibe_ic_one_shot.json").read_text())
    assert _doc["verdict"] == "NOT_MEASURED", (_doc["verdict"], _doc.get("verdict_reasons"))
    assert rc != 0, rc
    _why = " | ".join(_doc.get("verdict_reasons") or [])
    assert "phase3 NOT_MEASURED" in _why, _why
    phases = {row["name"]: row for row in _doc["phases"]}
    assert phases["phase2"]["verdict"] == "PASS", phases
    assert "completion audit is not a pass" in _why, _why

    names = [name for _label, name, _args in calls]
    analog_i = names.index("analog_one_shot_runner")
    audit_i = names.index("flow_compliance_check")
    assert analog_i < audit_i

    args = calls[audit_i][2]
    assert args[:1] == [str(project)]
    assert "--strict" in args
    assert args[args.index("--stage-id") + 1] == "stage_analog"
    assert Path(args[args.index("--json") + 1]) == (
        project / "reports" / "analog" / "stage_analog_compliance.json")

    written = json.loads(next(
        (project / "steps").glob("phase2/stage2/14_*/written.json")
    ).read_text())
    assert any(
        item["rel"] == "reports/analog/stage_analog_compliance.json"
        for item in written["produced"]
    ), written
    assert not any(
        finding.get("spec") == "reports/analog/stage_analog_compliance.json"
        for finding in written["findings"]
    ), written
