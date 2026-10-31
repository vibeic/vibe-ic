"""Actual LOCAL output-mount admission; neutral ledger, no EDA dispatch."""
import copy
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest
import canonical_run_admission as cra
import librelane_contract as contract


def no_native_replay(event, args):
    if event == "subprocess.Popen":
        if list(map(str, args[1]))[:2] == ["docker", "inspect"]:
            return  # existing image metadata lookup; never an EDA invocation
        raise AssertionError("No EDA/native/preflight process belongs in mount admission controls")


sys.addaudithook(no_native_replay)


PROJECT = os.environ.get("OUTPUT_MOUNT_CONTROL_PROJECT")
pytestmark = pytest.mark.skipif(not PROJECT, reason="requires genuine current-CID LOCAL receipt")


def invoke():
    return cra.admit_span(Path(PROJECT), "phase2", Path(cra.__file__).parent, "",
                          {"entry_step": "14", "exit_step": "14", "top_name": "neutral"})


def test_actual_seed_then_unchanged_duplicate():
    got = invoke()
    assert got.admitted and got.reason == "ADMITTED", got
    assert invoke().reason == "DUPLICATE_NO_NEW_EVIDENCE"


def test_actual_current_mounts_admit_change_once_and_reject_duplicate():
    got = invoke()
    assert got.reason == os.environ["OUTPUT_MOUNT_EXPECT"], got
    runtime = got.identity["dispatch_config"]["local_runtime_conditions"]
    access = runtime["producer_output_access"]
    expected = os.environ["OUTPUT_MOUNT_ACCESS"] == "rw"
    gates = [v for k, v in access.items() if k.startswith("reports/phase2/gates/")]
    assert len(gates) == 3 and all(v is expected for v in gates), access
    assert access["reports/analog/stage_analog_compliance.json"] is True
    again = invoke()
    assert again.reason == "DUPLICATE_NO_NEW_EVIDENCE", again
    assert again.identity_sha256 == got.identity_sha256
    print("ACTUAL_CONSUMER", json.dumps({"first": got.reason,
        "second": again.reason, "identity_sha256": got.identity_sha256,
        "output_access": access}, sort_keys=True))


@pytest.mark.parametrize("damage", ["missing_mounts", "malformed_rw", "duplicate_mount",
    "forged_access", "foreign_cid", "missing_receipt", "malformed_receipt", "changed_receipt"])
def test_actual_consumer_refuses_unbound_or_forged_access(tmp_path, monkeypatch, damage):
    original = Path(os.environ[contract.LOCAL_ATTESTATION_ENV])
    document = json.loads(original.read_text())
    path = tmp_path / "negative-launch.json"
    mount = next(m for m in document["container_inspect"]["Mounts"]
                 if m["Destination"] == str(Path(PROJECT) / "reports/phase2/gates/yosys_hilomap.json"))
    if damage == "missing_mounts":
        del document["container_inspect"]["Mounts"]
    elif damage == "malformed_rw":
        mount["RW"] = "true"
    elif damage == "duplicate_mount":
        document["container_inspect"]["Mounts"].append(copy.deepcopy(mount))
    elif damage == "forged_access":
        mount["RW"] = not mount["RW"]
    elif damage == "foreign_cid":
        document["cid"] = "f" * 64
    path.write_text(json.dumps(document))
    monkeypatch.setenv(contract.LOCAL_ATTESTATION_ENV, str(path))
    if damage == "missing_receipt":
        path.unlink()
    elif damage == "malformed_receipt":
        path.write_text("{")
    elif damage == "changed_receipt":
        validator = contract.local_image_attestation
        def changing():
            accepted = validator()
            path.write_text(path.read_text() + " ")
            return accepted
        monkeypatch.setattr(contract, "local_image_attestation", changing)
    ledger = cra.ledger_path(Path(PROJECT))
    before = ledger.read_bytes()
    got = invoke()
    assert got.reason == "LOCAL_RUNTIME_UNATTESTED", got
    assert not got.admitted
    assert ledger.read_bytes() == before
