"""Process attestations are complete, structured, and emitted by real dispatch."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
ROOT = PROGRAMS.parents[3]
DISPATCH = ROOT / "tools" / "ci" / "_gate_dispatch.sh"
HELPER = PROGRAMS / "gate_process_attestation.py"

sys.path.insert(0, str(PROGRAMS))
















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
