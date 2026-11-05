"""Focused controls for the ordinary A1-A5/A9 Registry producer lane."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(PROGRAMS.parent))
import execution_analog_front_worker as worker
import analog_one_shot_runner as runner
from programs.tests._analog_producer_fixture import block, make_project


_RUNTIME_TREE_ENVS = (
    "VIBEIC_RETAINED_PLUGIN_ROOT", "VIBEIC_RETAINED_PLUGIN_MANIFEST")


def _runtime_tree_path(value) -> bool:
    return ".vibeic/runtime-program-trees/" in str(value or "").replace("\\", "/")


@pytest.fixture(autouse=True)
def isolated_runtime_program_imports():
    """A prior in-process front door cannot choose this test's modules.

    Backend entry controls in this module intentionally call ``main`` and
    activate a project-retained program tree.  That invocation-local path and
    its imported modules must not survive into the next independent project.
    """
    def reset():
        sys.path[:] = [entry for entry in sys.path
                       if not _runtime_tree_path(entry)]
        programs = str(PROGRAMS)
        sys.path[:] = [entry for entry in sys.path if str(entry) != programs]
        sys.path.insert(0, programs)
        for name, module in list(sys.modules.items()):
            if _runtime_tree_path(getattr(module, "__file__", "")):
                sys.modules.pop(name, None)
        for name in _RUNTIME_TREE_ENVS:
            os.environ.pop(name, None)

    reset()
    yield
    reset()


def _project(root: Path, names=("alpha", "beta")) -> Path:
    blocks = [block(name, "amplifier", specs=[{
        "name": "vout", "target": 1.0, "units": "V", "source": "doc_alpha.md"}])
        for name in names]
    make_project(root, blocks)
    docs = root / "phase1/generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L1_DATASHEET.json").write_text(json.dumps({"electrical_specs": []}))
    return root










@pytest.mark.parametrize("cause", ["image", "pdk_root"])
def test_phase3_backend_binding_preserves_runtime_refusal(tmp_path, monkeypatch, cause):
    import phase3_one_shot_runner as backend
    import librelane_contract as contract

    def refused(*args, **kwargs):
        raise contract.Refusal("LL_RUNTIME_UNAVAILABLE", cause)

    monkeypatch.setattr(contract, "resolve_image",
                        refused if cause == "image" else lambda p: "test-image")
    monkeypatch.setattr(contract, "pdk_root_resolution", refused)
    with pytest.raises(contract.Refusal, match="LL_RUNTIME_UNAVAILABLE"):
        backend._backend_parameter_values(tmp_path, SimpleNamespace(name="synthetic_process"))






def test_measured_fail_precedes_missing_sibling_and_missing_outputs_stay_nm(tmp_path, monkeypatch):
    project = _project(tmp_path / "input")
    monkeypatch.setenv("VIBEIC_EXECUTION_BINDING", json.dumps({"step_id": "A4"}))
    calls = []

    def fail_then_missing(root, row, name, args=None):
        calls.append(row["name"])
        if row["name"] == "alpha":
            target = root / "phase3/analog/alpha/corner_results.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('{"verdict":"FAIL"}\n')
            return SimpleNamespace(status="FAIL", detail="measured corner failure",
                                    reason_class="", output_files=[str(target.relative_to(root))])
        return SimpleNamespace(status="NOT_MEASURED", detail="simulator absent",
                               reason_class="", output_files=[])

    monkeypatch.setattr(runner, "step_for_block", fail_then_missing)
    result = worker.execute("A4", project, tmp_path / "fail-output")
    assert calls == ["alpha", "beta"]
    assert result["verdict"] == "FAIL"
    assert result["block_outputs"]["beta"] == []

    monkeypatch.setattr(runner, "step_for_block", lambda *a, **k:
                        SimpleNamespace(status="NOT_MEASURED", detail="tool absent",
                                        reason_class="", output_files=[]))
    absent = worker.execute("A4", project, tmp_path / "nm-output")
    assert absent["verdict"] == "NOT_MEASURED"
    assert not absent["outputs"]
