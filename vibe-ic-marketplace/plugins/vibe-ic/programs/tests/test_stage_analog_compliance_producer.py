#!/usr/bin/env python3
"""Regression: the top runner must produce the stage-analog audit before Step 14.

The final compliance audit is a judge, not a producer belonging to the run.
If it is the first process to write ``stage_analog_compliance.json``, Step 14
correctly excludes that file as ``audit_created`` and cannot credit it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))


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

    calls: list[tuple[str, str, list[str]]] = []

    def record(label, program, args, env=None):
        name = Path(program).stem
        calls.append((label, name, list(args)))
        if name == "flow_compliance_check":
            out = Path(args[args.index("--json") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps({"verdict": "FAIL"}) + "\n")
            return 1
        return 0

    monkeypatch.setattr(runner, "_run_phase", record)
    monkeypatch.setattr(runner, "_capture_container_image", lambda *_: {})
    monkeypatch.setattr(runner, "_capture_pdk_revision", lambda *_: {})
    monkeypatch.setattr(sys, "argv", [
        "vibe_ic_one_shot_runner", str(project), "--skip-phase1",
        "--no-dashboard",
    ])

    assert runner.main() == 0
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
