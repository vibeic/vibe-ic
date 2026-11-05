import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import flow_engine_frontend as frontend


def test_native_phase1_calls_document_owner_without_submission_admission(tmp_path):
    import phase1_one_shot_runner as owner
    argv = ["phase1_one_shot_runner.py", str(tmp_path), "--route", "ip",
            "--pdk", "sky130A", "--engine", "native"]
    with patch.object(sys, "argv", argv), \
            patch.object(owner, "_run_docs_mode", return_value=0) as extract, \
            patch.object(owner, "_run_step_0_5ic", side_effect=AssertionError("admission reached")):
        assert owner.main_recorded() == 0
    extract.assert_called_once_with(tmp_path.resolve(), "UNNAMED_CHIP", ["--pdk", "sky130A"])
    report = json.loads((tmp_path / "reports/orchestrator/phase1_one_shot.json").read_text())
    assert report["expert_review"] == "PENDING"


def test_native_benchmark_argv_preserves_router_window_without_old_manifest(tmp_path, monkeypatch):
    import benchmark_dispatch as dispatcher
    import flow109
    monkeypatch.setenv("VIBEIC_FLOW_ENGINE", "native")
    with patch.object(flow109, "resolve_task_manifest", side_effect=AssertionError("old manifest reached")):
        command = dispatcher._solver_argv(Path("vibe_ic_one_shot_runner.py"), tmp_path,
                                          "1", "2", "ip", "original", "rtl")
    for flag, value in (("--entry-step", "1"), ("--exit-step", "2"),
                        ("--rtl-input", "original"), ("--engine", "native")):
        assert command[command.index(flag) + 1] == value
    assert not (tmp_path / "input/flow109-manifest.json").exists()


def test_public_native_entry_forwards_the_selected_bounded_window(tmp_path):
    observed = []
    engine = SimpleNamespace(run=lambda project, **kwargs:
                             observed.append((project, kwargs)) or {"fail": 0, "not_measured": 0})
    args = SimpleNamespace(project=tmp_path, entry_step="1", exit_step="2",
                           rtl_input="original", delivery_target="rtl", route="ip")
    with patch.dict(sys.modules, {"flow_engine": engine}):
        assert frontend.run_public(args) == 0
    assert observed == [(tmp_path.resolve(), {"route": {
        "entry_step": "1", "verify_through": "2", "input_contract": "original",
        "delivery_target": "rtl"}})]
