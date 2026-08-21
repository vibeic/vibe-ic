"""Process attestations are complete, structured, and emitted by real dispatch."""
from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
ROOT = PROGRAMS.parents[3]
DISPATCH = ROOT / "tools" / "ci" / "_gate_dispatch.sh"
HELPER = PROGRAMS / "gate_process_attestation.py"

sys.path.insert(0, str(PROGRAMS))
import gate_process_attestation as A  # noqa: E402


def test_same_count_with_different_failure_names_has_different_identity():
    left = A.semantic_record("[FAIL] ALPHA\n[FAIL] 1 finding\n", 1)
    right = A.semantic_record("[FAIL] BETA\n[FAIL] 1 finding\n", 1)
    assert left["verdict_line"] == right["verdict_line"]
    assert left["semantic_sha256"] != right["semantic_sha256"]


def test_pytest_wall_clock_is_normalized_without_erasing_outcomes():
    left = A.semantic_record("108 passed in 1.25s\n", 0)
    right = A.semantic_record("108 passed in 9.75s\n", 0)
    red = A.semantic_record("107 passed, 1 failed in 9.75s\n", 1)
    assert left["semantic_sha256"] == right["semantic_sha256"]
    assert red["semantic_sha256"] != left["semantic_sha256"]


def test_parenthesized_pytest_minute_clock_is_normalized_too():
    left = A.semantic_record("108 passed in 64.11s (0:01:04)\n", 0)
    right = A.semantic_record("108 passed in 66.28s (0:01:06)\n", 0)
    red = A.semantic_record("107 passed, 1 failed in 66.28s (0:01:06)\n", 1)
    assert left["verdict_line"] == right["verdict_line"] == "108 passed in <TIME>s"
    assert left["semantic_sha256"] == right["semantic_sha256"]
    assert red["semantic_sha256"] != left["semantic_sha256"]


def test_loader_refuses_a_record_whose_claim_and_digest_disagree(tmp_path):
    record = A.process_attestation(
        "gate", "[FAIL] real finding\n", 1, ["python3", "gate.py"])
    record["returncode"] = 0
    path = tmp_path / "forged.jsonl"
    path.write_text(json.dumps(record) + "\n")
    try:
        A.load_jsonl(path)
    except ValueError as exc:
        assert "digest mismatch" in str(exc)
    else:
        raise AssertionError("a self-contradictory attestation was accepted")


def test_real_dispatch_writes_owner_only_records_into_its_summary(tmp_path):
    repo = tmp_path / "repo"
    (repo / "benchmark-data").mkdir(parents=True)
    script = tmp_path / "gates.sh"
    jsonl = tmp_path / "progress.jsonl"
    summary = tmp_path / "summary.json"
    script.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        f"ROOT={str(repo)!r}\n"
        f"GATE_DISPATCH_ATTESTATION_FILE={str(jsonl)!r}\n"
        f"GATE_DISPATCH_ATTESTATION_HELPER={str(HELPER)!r}\n"
        "export ROOT GATE_DISPATCH_ATTESTATION_FILE "
        "GATE_DISPATCH_ATTESTATION_HELPER\n"
        f". {str(DISPATCH)!r}\n"
        "gate_dispatch_init \"$@\"\n"
        "run 'green gate' \"$ROOT\" python3 -c \"print('[PASS] 1 item')\"\n"
        "run 'red gate' \"$ROOT\" python3 -c \"print('[FAIL] named-red'); "
        "raise SystemExit(1)\"\n"
        "gate_dispatch_finish\n")

    proc = subprocess.run(
        ["bash", str(script), "--summary-json", str(summary)],
        capture_output=True, text=True)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    records = A.load_jsonl(jsonl)
    assert [r["label"] for r in records] == ["green gate", "red gate"]
    assert stat.S_IMODE(jsonl.stat().st_mode) == 0o600
    doc = json.loads(summary.read_text())
    assert doc["process_attestations"] == records
    assert records[1]["finding_identities"] == ["[FAIL] named-red"]


def test_real_dispatch_mirrors_each_complete_record_to_live_progress(tmp_path):
    repo = tmp_path / "repo"
    (repo / "benchmark-data").mkdir(parents=True)
    script = tmp_path / "gates.sh"
    attested = tmp_path / "shard.jsonl"
    progress = tmp_path / "live.jsonl"
    summary = tmp_path / "summary.json"
    script.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        f"ROOT={str(repo)!r}\n"
        f"GATE_DISPATCH_ATTESTATION_FILE={str(attested)!r}\n"
        f"GATE_DISPATCH_PROGRESS_FILE={str(progress)!r}\n"
        f"GATE_DISPATCH_ATTESTATION_HELPER={str(HELPER)!r}\n"
        "export ROOT GATE_DISPATCH_ATTESTATION_FILE "
        "GATE_DISPATCH_PROGRESS_FILE GATE_DISPATCH_ATTESTATION_HELPER\n"
        f". {str(DISPATCH)!r}\n"
        "gate_dispatch_init \"$@\"\n"
        "run 'observable gate' \"$ROOT\" python3 -c "
        "\"print('[PASS] observed')\"\n"
        "gate_dispatch_finish\n")

    proc = subprocess.run(
        ["bash", str(script), "--summary-json", str(summary)],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert A.load_jsonl(progress) == A.load_jsonl(attested)
    assert stat.S_IMODE(progress.stat().st_mode) == 0o600


def test_a_live_progress_mirror_that_cannot_be_written_refuses(tmp_path):
    repo = tmp_path / "repo"
    (repo / "benchmark-data").mkdir(parents=True)
    script = tmp_path / "gates.sh"
    attested = tmp_path / "shard.jsonl"
    progress_directory = tmp_path / "not-a-jsonl"
    progress_directory.mkdir()
    summary = tmp_path / "summary.json"
    script.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        f"ROOT={str(repo)!r}\n"
        f"GATE_DISPATCH_ATTESTATION_FILE={str(attested)!r}\n"
        f"GATE_DISPATCH_PROGRESS_FILE={str(progress_directory)!r}\n"
        f"GATE_DISPATCH_ATTESTATION_HELPER={str(HELPER)!r}\n"
        "export ROOT GATE_DISPATCH_ATTESTATION_FILE "
        "GATE_DISPATCH_PROGRESS_FILE GATE_DISPATCH_ATTESTATION_HELPER\n"
        f". {str(DISPATCH)!r}\n"
        "gate_dispatch_init \"$@\"\n"
        "run 'green but unobservable' \"$ROOT\" python3 -c "
        "\"print('[PASS] observed')\"\n"
        "gate_dispatch_finish\n")

    proc = subprocess.run(
        ["bash", str(script), "--summary-json", str(summary)],
        capture_output=True, text=True)
    output = proc.stdout + proc.stderr
    assert proc.returncode == 2, output
    assert "PROCESS PROGRESS MIRROR FAILED" in output
    doc = json.loads(summary.read_text())
    assert any("machine attestation" in item
               for item in doc["wiring_errors"])


def test_requested_attestation_with_missing_helper_refuses_the_run(tmp_path):
    repo = tmp_path / "repo"
    (repo / "benchmark-data").mkdir(parents=True)
    script = tmp_path / "gates.sh"
    jsonl = tmp_path / "progress.jsonl"
    summary = tmp_path / "summary.json"
    missing = tmp_path / "missing-attestation-helper.py"
    script.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        f"ROOT={str(repo)!r}\n"
        f"GATE_DISPATCH_ATTESTATION_FILE={str(jsonl)!r}\n"
        f"GATE_DISPATCH_ATTESTATION_HELPER={str(missing)!r}\n"
        "export ROOT GATE_DISPATCH_ATTESTATION_FILE "
        "GATE_DISPATCH_ATTESTATION_HELPER\n"
        f". {str(DISPATCH)!r}\n"
        "gate_dispatch_init \"$@\"\n"
        "run 'green but unattested' \"$ROOT\" "
        "python3 -c \"print('[PASS] 1 item')\"\n"
        "gate_dispatch_finish\n")

    proc = subprocess.run(
        ["bash", str(script), "--summary-json", str(summary)],
        capture_output=True, text=True)
    output = proc.stdout + proc.stderr
    assert proc.returncode == 2, output
    assert "PROCESS ATTESTATION FAILED: green but unattested" in output
    assert "completed without a machine attestation" in output
    doc = json.loads(summary.read_text())
    assert doc["process_attestations"] == []
    assert any("machine attestation" in item
               for item in doc["wiring_errors"])
