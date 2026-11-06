"""Issue #3380: L10 unit-oracle recovery has an exact existing owner."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[2]
ROUTING = PLUGIN / "benchmark" / "CAPTURE_ROUTING.json"
SKILL = PLUGIN / "skills" / "testbench-gen" / "SKILL.md"
STEP = "phase2.l10_unit_tb.testbench_gen.run_unit_tbs"


def test_l10_unit_oracle_route_names_existing_program_receipt_and_skill():
    route = json.loads(ROUTING.read_text())["steps"][STEP]
    assert route["bucket_A_program"] == "programs/testbench_gen.py"
    assert route["bucket_A_related"] == [
        "programs/_l10_execution.py",
        "programs/l10_tb_conformance_check.py",
    ]
    assert route["bucket_B_skill_file"] == "skills/testbench-gen/SKILL.md"
    assert all((PLUGIN / rel).is_file() for rel in (
        route["bucket_A_program"],
        *route["bucket_A_related"],
        route["bucket_B_skill_file"],
    ))


def test_skill_keeps_unit_and_full_stack_owners_distinct():
    text = SKILL.read_text()
    assert STEP in text
    assert "testbench_gen.py" in text
    assert "_l10_execution.py" in text
    assert "Do not borrow the full-stack route" in text
    assert "wrong expected value" in text
