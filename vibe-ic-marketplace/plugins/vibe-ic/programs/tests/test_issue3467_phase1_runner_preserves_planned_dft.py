"""Executable exact-fixture control for issue #3467."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


INPUT = """The pre-DFT wrapper is functional only.
DFT remains planned and unmeasured.
Preserve any known scan/test-access interface.
The final producer must reconcile the actual mapped/DFT pad roster.
"""


def test_phase1_runner_preserves_planned_unmeasured_dft(tmp_path):
    programs = Path(os.environ.get(
        "VIBEIC_PROGRAMS_UNDER_TEST", Path(__file__).resolve().parents[1]))
    src = tmp_path / "input" / "docs" / "spec.md"
    src.parent.mkdir(parents=True)
    src.write_text(INPUT)
    cp = subprocess.run(
        [sys.executable, str(programs / "phase1_doc_one_shot_runner.py"),
         str(tmp_path), "--ic-name", "planned_dft_probe", "--pdk", "sky130A"],
        text=True, capture_output=True,
        env={**os.environ, "PYTHONPATH": str(programs)},
    )
    assert cp.returncode == 0, cp.stdout + cp.stderr
    doc = json.loads((tmp_path / "phase1" / "generated_docs" /
                      "L20_DFT_SCAN_TOPOLOGY.json").read_text())
    fields = doc["fields"]
    assert doc["extraction_status"] == "PARTIALLY_EXTRACTED"
    assert fields["dft_present"] is None
    assert fields["dft_intent_status"] == "PLANNED_UNMEASURED"
    assert fields["scan_chains"] == []
    assert len(fields["planned_obligations"]) == 2
    assert doc["source_documents"] == ["input/docs/spec.md"]
