# Write the one-gate aggregate hygiene record for this stub arm.
import json
import os
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path.cwd() / "vibe-ic-marketplace/plugins/vibe-ic" / "programs"))
import gate_process_attestation as attest

# THE TWO ARMS MUST AGREE ON THE DAY. `hygiene_finding_delta.delta` refuses a
# pair measured on different days, because `exemption_expired` is computed
# against it and a promise coming due is the calendar's doing rather than the
# branch's. A stub that read the clock could straddle midnight between the arms
# and turn this file's whole battery red for a reason no test is about.
TODAY = "2026-08-15"
LABEL = "stub gate"
ARGV = ["python3", "stub_gate.py", LABEL]
OUTPUT = {"PASS": "[PASS] checked\n",
          "FAIL": "[FAIL] named finding\n",
          "NOT_CHECKED": "[NOT_CHECKED] unavailable\n"}
RETURNCODE = {"PASS": 0, "FAIL": 1, "NOT_CHECKED": 2}

state = os.environ.get("ARM_HYGIENE_STATE") or "PASS"
gate = {"label": LABEL, "state": state, "seconds": 1, "corpus": None,
        "exempt_until": None, "exempt_reason": None,
        "exemption_expired": False, "scope": None}
record = {
    "shard": None, "today": TODAY, "listed_only": False,
    "declared": 1, "ran": 1,
    "decided": int(state in ("PASS", "FAIL")),
    "passed": int(state == "PASS"),
    "failed": int(state == "FAIL"),
    "not_checked": int(state == "NOT_CHECKED"),
    "wrote_corpus": int(state == "WROTE_CORPUS"),
    "deferred": 0, "other_shard": 0, "out_of_scope": 0,
    "not_checked_unexempted": [LABEL] if state == "NOT_CHECKED" else [],
    "exemptions_expired": [], "wiring_errors": [], "corpora": [],
    "gates": [gate],
    "process_attestations": [attest.process_attestation(
        LABEL, OUTPUT[state], RETURNCODE[state], ARGV, state=state)],
}
Path(sys.argv[1]).write_text(json.dumps(record), encoding="utf-8")
