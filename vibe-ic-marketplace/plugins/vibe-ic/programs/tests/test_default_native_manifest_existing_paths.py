"""Existing-directory/native metadata controls; no native EDA or IC data."""
import hashlib
import json
from pathlib import Path

import pytest

import execution_adapters_backend as adapters
import execution_backend_producers as backend
import execution_backend_worker as worker
import execution_policy as policy
import test_default_native_input_manifest as caller


FOLDER = "phase3/librelane/02-yosys-synthesis"
LOCK = FOLDER + "/vibeic_abc_tmp/yosys-liberty-scl-cache-1000/cache.scl.lock"
FSM = FOLDER + "/fsm_encoding.enc"


def _write(root, raw, value):
    path = root / raw
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)
    return path


def _native_checkpoint(root):
    """Synthetic existing run_chain shape, using no real design corpus."""
    folder = root / FOLDER
    netlist = _write(root, FOLDER + "/neutral.nl.v", "module neutral; endmodule\n")
    prior = _write(root, "phase3/librelane/01-yosys-jsonheader/neutral.h.json", "{}\n")
    config_input = _write(root, "phase2/stage1/rtl/neutral.v", "module neutral; endmodule\n")
    for name in ("config.json", "reports/stat.json", "input_fingerprint.json", "pdk_root.json"):
        _write(root, FOLDER + "/" + name, "{}\n")
    _write(root, FOLDER + "/state_out.json", json.dumps({"nl": str(netlist.resolve())}))
    files = [p for p in folder.rglob("*") if p.is_file()]
    receipt = {"input": {
        "state_files": {str(prior.resolve()): worker.sha(prior)},
        "config_files": {str(config_input.resolve()): worker.sha(config_input)}},
        "sha256": {str(p.relative_to(folder)): worker.sha(p) for p in files}}
    _write(root, FOLDER + "/vibeic_receipt.json", json.dumps(receipt))
    _write(root, "phase2/stage2/synth/synth_inputs.json", json.dumps({
        "librelane_synthesis": {"folder": FOLDER, "mapped": "phase2/stage2/synth/netlist.v"}}))
    _write(root, "phase3/librelane/synthesis_resolved.json", "{}\n")
    # Neither file is consumed or named in the synthesis receipt closure.
    _write(root, FSM, "")
    _write(root, LOCK, "")
    (root / "phase2/stage1/sim/tb").mkdir(parents=True)
    return receipt


@pytest.mark.parametrize("case", ["current", "directory", "updated_route", "missing", "changed", "measured_fail"])
def test_existing_native_checkpoint_uses_full_default_caller(tmp_path, monkeypatch, case):
    original_project = caller._project

    def project_with_existing_paths(path):
        root = original_project(path)
        _native_checkpoint(root)
        if case == "directory":
            # An empty descendant is still a byte identity, not an absent
            # directory or a claim that its semantic content passed a gate.
            _write(root, "phase2/stage1/sim/tb/native_metadata", "")
        return root

    monkeypatch.setattr(caller, "_project", project_with_existing_paths)
    original_produce = backend.produce

    def mutate_unconsumed_cache(root, params):
        (root / LOCK).write_text("unrelated mutable tool cache\n")
        return original_produce(root, params)

    monkeypatch.setattr(backend, "produce", mutate_unconsumed_cache)
    caller.test_default_current_native_manifest_reaches_the_consumer(tmp_path, monkeypatch, case)
    observation = json.loads((tmp_path / "project/API_OBSERVATION.json").read_text())
    if case != "missing":
        files = observation["seen"]["manifest"]["files"]
        assert FSM not in files and LOCK not in files
        assert FOLDER not in observation["seen"]["manifest"]["declarations"]
        for name in ("vibeic_receipt.json", "state_out.json", "config.json", "reports/stat.json",
                     "input_fingerprint.json", "pdk_root.json", "neutral.nl.v"):
            assert FOLDER + "/" + name in files
        assert "phase3/librelane/01-yosys-jsonheader/neutral.h.json" in files
        assert "phase2/stage1/rtl/neutral.v" in files
        if case == "directory":
            assert files["phase2/stage1/sim/tb/native_metadata"] == hashlib.sha256(b"").hexdigest()


def test_synthesis_closure_missing_members_are_aggregate_pretool_inputs(tmp_path):
    root = caller._project(tmp_path)
    _native_checkpoint(root)
    _write(root, "input/step_0_5ic_answers.json", "{}\n")
    _write(root, "input/submission_template/neutral.json", "{}\n")
    missing = [FOLDER + "/reports/stat.json", "phase3/librelane/01-yosys-jsonheader/neutral.h.json"]
    for raw in missing:
        (root / raw).unlink()
    params = {}
    policy._fixed_inputs({"project": root}, "32", parameters=params)
    manifest = params["resolved_input_manifest"]
    assert set(missing) <= set(manifest["missing"])
    assert FSM not in manifest["files"] and LOCK not in manifest["files"]


def test_all_backend_rows_use_the_same_receipt_closure(tmp_path):
    from execution_provider_catalog import BACKEND_IDS
    root = caller._project(tmp_path)
    receipt = _native_checkpoint(root)
    _write(root, "input/step_0_5ic_answers.json", "{}\n")
    _write(root, "input/submission_template/neutral.json", "{}\n")
    observed = {}
    for sid in BACKEND_IDS:
        params = {}
        policy._fixed_inputs({"project": root, "parameters": {"top": "neutral"}}, sid, parameters=params)
        manifest = params["resolved_input_manifest"]
        observed[sid] = manifest
        assert FSM not in manifest["files"] and LOCK not in manifest["files"]
        assert "phase2/stage1/sim/tb" not in manifest["missing"]
        assert all(FOLDER + "/" + raw in manifest["files"] for raw in receipt["sha256"])
    (root / "ALL_BACKEND_PREFLIGHT.json").write_text(json.dumps(observed, indent=2))
