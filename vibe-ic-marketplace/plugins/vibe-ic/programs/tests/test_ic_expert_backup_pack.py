#!/usr/bin/env python3
r"""test_ic_expert_backup_pack.py — the IC-Expert-Agent AI-backup context pack.

Verifies the general-core assembler that lets the AI act AS the IC Expert Agent
using its two expert assets (expert-SKILLS digest + class-matched expert-DB):
  * assemble() writes lessons.md (skills), ic_expert_db.md (DB), contract.v
    (interface), and a hand-off JSON naming the vibe-ic:ic-expert-agent subagent;
  * the expert-DB retrieval returns the RELEVANT design classes for the prompt;
  * the interface contract is header-only (ports, no behaviour);
  * assembly reads ONLY the supplied prompt/interface (no oracle).

Run: python3 -m pytest programs/tests/test_ic_expert_backup_pack.py -q
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
_spec = importlib.util.spec_from_file_location(
    "ic_expert_backup_pack", _PROGRAMS / "ic_expert_backup_pack.py")
P = importlib.util.module_from_spec(_spec)
sys.modules["ic_expert_backup_pack"] = P
_spec.loader.exec_module(P)


def test_iface_to_contract_v_header_only():
    v = P.iface_to_contract_v(
        [{"name": "clk", "dir": "input", "width": 1},
         {"name": "d", "dir": "input", "width": 8},
         {"name": "q", "dir": "output", "width": 8}], "foo")
    assert "module foo (" in v
    assert "input [7:0] d" in v
    assert "output [7:0] q" in v
    assert v.rstrip().endswith("endmodule")


def test_assemble_writes_dual_track_pack_and_handoff(tmp_path):
    prompt = ("Design a sequential multiplier: shift-add signed multiply over "
              "N cycles with a valid/done handshake.")
    iface = [{"name": "clk", "dir": "input", "width": 1},
             {"name": "a", "dir": "input", "width": 16},
             {"name": "product", "dir": "output", "width": 32}]
    h = P.assemble(prompt, iface, "seqmul",
                   ["spec-to-rtl", "rtl-repair"],
                   ["spec_conformance_check.py"], tmp_path)
    # the hand-off names the IC Expert Agent subagent
    assert h["subagent_type"] == "vibe-ic:ic-expert-agent"
    assert h["expert_skills"] == ["spec-to-rtl", "rtl-repair"]
    assert h["interface_contract"] == "contract.v"
    # both expert assets rendered
    assert (tmp_path / "lessons.md").is_file()           # expert-SKILLS
    assert (tmp_path / "ic_expert_db.md").is_file()      # expert-DB
    assert (tmp_path / "contract.v").is_file()
    assert (tmp_path / "ic_expert_agent_handoff.json").is_file()
    assert h["dual_track"]["track1_general_blind"]["n_skills"] > 0
    assert h["dual_track"]["track2_db_informed"]["n_db_lessons"] > 0


def test_expert_db_matches_relevant_classes(tmp_path):
    h = P.assemble(
        "A 2-read 1-write register file with byte enables.",
        None, None, [], [], tmp_path)
    classes = [c["ic_class"] for c in h["db_classes"]]
    # the register-file craft must surface for a register-file prompt
    assert any("register-file" in c or "register" in c for c in classes), classes


def test_assemble_is_input_only(tmp_path):
    # nothing but the prompt/interface goes in; assert no stray oracle leaks into
    # the emitted pack.
    P.assemble("Fix the SECRET_ORACLE bug in module m.", None, None,
               [], [], tmp_path)
    hj = json.loads((tmp_path / "ic_expert_agent_handoff.json").read_text())
    assert hj["prompt_is_input_only"] is True


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
