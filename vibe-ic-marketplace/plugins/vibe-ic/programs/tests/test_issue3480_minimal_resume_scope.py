"""Issue #3480: ordinary recovery selects evidence-bounded existing entries."""
from __future__ import annotations

import os
import sys
from pathlib import Path


PROGRAMS = Path(os.environ.get(
    "VIBEIC_TEST_PROGRAMS", Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(PROGRAMS))



ORDER = ["7", "8", "9", "15", "16", "17", "18", "32"]








































































def test_loop2converge_ordinary_guidance_uses_same_program_decision():
    text = (PROGRAMS.parent / "skills/loop2converge/SKILL.md").read_text()
    section = text.split("### 1.2 — Establish the smallest necessary continuation", 1)[1]
    section = section.split("## 2 —", 1)[0]
    assert "Route every ordinary recovery" in section
    assert "--resume-request <json>" in section
    assert "minimal_resume_plan-<timestamp>.json" in section
    assert "Program enforcement of this continuation selection is tracked separately" not in section
