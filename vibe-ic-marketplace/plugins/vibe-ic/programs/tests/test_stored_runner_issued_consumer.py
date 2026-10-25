"""Historical measurements name their issuer, never a later auditor revision.

Use the existing actual native report writer and invocation seam. Different
auditor bytes do not reattribute the producer or make a new gate measurement.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

import benchmark_dispatch as current
import test_runner_report_generation as report_fixture


def load_dispatch(path, suffix=""):
    path.write_bytes(Path(current.__file__).read_bytes() + suffix.encode())
    name = "test_issued_consumer_" + hashlib.sha256(str(path).encode()).hexdigest()
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def measured(tmp_path):
    issuer = load_dispatch(tmp_path / "issued_dispatch.py")
    auditor = load_dispatch(tmp_path / "auditor_dispatch.py", "\n# next neutral audit revision\n")
    project, runner = report_fixture._fixture(tmp_path)
    argv = [sys.executable, str(runner), str(project), "fresh"]
    process = issuer._RunnerBudget(1, 1, 1).run(argv)
    collected = issuer._collect_runner_result(process, argv, "neutral", "neutral", project)
    assert process.rc == 1 and not process.error and collected["ok"], collected
    assert process.invocation["source_before"] == process.invocation["source_after"]
    return issuer, auditor, project, runner, argv, process


def test_different_auditor_revalidates_actual_issuer_without_rebinding(tmp_path):
    issuer, auditor, project, runner, argv, process = measured(tmp_path)
    old = Path(process.receipt_path).read_bytes()
    binding = json.loads((project / "reports/orchestrator/phase2_one_shot.json").read_text())["runner_binding"]
    diagnostic = auditor._stored_runner_diagnostics(process.invocation)
    (tmp_path / "stored-diagnostic.json").write_text(json.dumps(diagnostic, indent=2))
    assert diagnostic["status"] == "REPORTS_AVAILABLE", diagnostic
    assert not diagnostic.get("reason")
    assert binding["source"]["consumer"]["path"] == issuer.__file__
    assert Path(issuer.__file__).read_bytes() != Path(auditor.__file__).read_bytes()
    assert Path(process.receipt_path).read_bytes() == old
    # The same different auditor is NOT the issuer of this live process.
    live = auditor._runner_diagnostics(process, argv, project)
    assert live["status"] == "SOURCE_MISMATCH", live
    assert live["reason_class"] == "RUNNER_SOURCE_UNBOUND"


@pytest.mark.parametrize("damage", [
    "issuer_changed", "issuer_missing", "runner_changed", "runner_missing",
    "argv", "receipt", "report", "material", "issuer_path_missing",
])
def test_stored_issuer_selection_preserves_source_and_material_refusals(tmp_path, damage):
    issuer, auditor, project, runner, argv, process = measured(tmp_path)
    invocation = copy.deepcopy(process.invocation)
    if damage == "issuer_changed":
        path = Path(issuer.__file__)
        path.write_text(path.read_text() + "\n# issuer drift\n")
    elif damage == "issuer_missing":
        Path(issuer.__file__).unlink()
    elif damage == "runner_changed":
        runner.write_text(runner.read_text() + "\n# runner drift\n")
    elif damage == "runner_missing":
        runner.unlink()
    elif damage == "argv":
        invocation["argv"].append("--not-issued")
    elif damage == "receipt":
        path = Path(process.receipt_path)
        content = json.loads(path.read_text())
        content["rc"] = 0
        path.write_text(json.dumps(content))
    elif damage == "report":
        report = project / "reports/orchestrator/phase2_one_shot.json"
        report.write_text(report.read_text() + "\n")
    elif damage == "material":
        prompt = project / "input/phase1_prompt.md"
        prompt.write_text(prompt.read_text() + "Changed public requirement.\n")
    else:
        del invocation["source_before"]["consumer"]["path"]
        Path(process.receipt_path).write_text(json.dumps(invocation))
    try:
        diagnostic = auditor._stored_runner_diagnostics(invocation)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        assert damage in {"argv", "receipt", "issuer_path_missing"}, str(exc)
    else:
        assert diagnostic.get("reason"), diagnostic
        assert diagnostic["status"] in {
            "SOURCE_MISMATCH", "INVOCATION_MISMATCH", "MATERIAL_MISMATCH"}, diagnostic
        if damage in {"issuer_changed", "runner_changed"}:
            assert diagnostic["reason_class"] == "RUNNER_SOURCE_UNBOUND"
        if damage == "material":
            assert diagnostic["reason_class"] == "RUNNER_MATERIAL_UNBOUND"
