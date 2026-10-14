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


def test_named_signal_advice_follows_authoring_target_and_source_roles(tmp_path):
    import os
    import shutil
    from test_spec_named_signal_detect import MIXED_ROLES
    for target in ['rtl.sv', 'l_doc_expectations.json', 'review_notes.md']:
        dest = tmp_path / target.replace('.', '_')
        h = P.assemble(MIXED_ROLES, None, None, [], [], dest,
                       output_target=target)
        saved = json.loads((dest / 'ic_expert_agent_handoff.json').read_text())
        assert saved == h
        advice = next(r for r in h['spec_requirements']
                      if r['kind'] == 'preserve_named_signals')
        text = advice['requirement']
        artifact_dir = os.environ.get('C60_ARTIFACT_DIR')
        if artifact_dir:
            shutil.copytree(dest, Path(artifact_dir) / ('pack-' + target), dirs_exist_ok=True)
        if target != 'rtl.sv':
            assert 'Declare EACH' not in text
            assert target in text
        else:
            assert 'Declare EACH' in text
        assert set(advice['named_signals']) == {
            'ingress_valid', 'egress_ready', 'stage_cursor', 'beat_remaining'}
        assert advice['signal_evidence']
        assert 'neutral_cells_a' not in text and 'serial_order' not in text
        assert h['output_target'] == target
        assert h['subagent_type'] == 'vibe-ic:ic-expert-agent'
        assert h['dual_track']['track1_general_blind']['n_skills'] > 0
        assert h['dual_track']['track2_db_informed']['n_db_lessons'] > 0


def test_phase1_ai_subtrack_handoff_keeps_expectation_authoring_scope(tmp_path):
    import os
    import shutil
    import phase1_expert_parse_track as track
    from test_spec_named_signal_detect import MIXED_ROLES
    dest = tmp_path / 'pack'
    status = track.ai_subtrack(tmp_path, MIXED_ROLES, dest)
    h = json.loads((dest / 'ic_expert_agent_handoff.json').read_text())
    artifact_dir = os.environ.get('C60_ARTIFACT_DIR')
    if artifact_dir:
        shutil.copytree(dest, Path(artifact_dir) / 'phase1-consumer', dirs_exist_ok=True)
        (Path(artifact_dir) / 'phase1-status.json').write_text(json.dumps(status, indent=2))
    assert status['status'] == 'HANDOFF_EMITTED'
    assert h['output_target'] == 'l_doc_expectations.json'
    advice = next(r for r in h['spec_requirements'] if r['kind'] == 'preserve_named_signals')
    assert 'Declare EACH' not in advice['requirement']
    assert set(advice['named_signals']) == {
        'ingress_valid', 'egress_ready', 'stage_cursor', 'beat_remaining'}
    assert (dest / h['read_design_input_from']).read_text() == MIXED_ROLES


import subprocess
import pytest

_PUBLIC_ROLE_CASES = json.loads((Path(__file__).parent / "fixtures" /
    "issue3088_advisory_roles.json").read_text())["cases"]


@pytest.mark.parametrize("surface", ["assemble-phase1", "normal-cli"])
@pytest.mark.parametrize("label", _PUBLIC_ROLE_CASES)
def test_public_3088_advisory_reaches_normal_producer(tmp_path, label, surface):
    case = _PUBLIC_ROLE_CASES[label]
    prompt = case["prompt"]
    dest = tmp_path / "pack"
    if surface == "assemble-phase1":
        actual = P.assemble(prompt, None, None, [], [], dest,
                            output_target="l_doc_expectations.json")
    else:
        source = tmp_path / "public-prompt.txt"
        source.write_text(prompt)
        argv = [sys.executable, str(_PROGRAMS / "ic_expert_backup_pack.py"),
                "--prompt", "@" + str(source), "--out", str(dest)]
        run = subprocess.run(argv, capture_output=True, text=True)
        (tmp_path / "CLI_RECEIPT.json").write_text(json.dumps({
            "argv": argv, "exit_code": run.returncode,
            "stdout": run.stdout, "stderr": run.stderr,
        }, indent=2) + "\n")
        assert run.returncode == 0, (run.stdout, run.stderr)
        actual = json.loads(run.stdout)
    saved = json.loads((dest / "ic_expert_agent_handoff.json").read_text())
    assert saved == actual
    if surface == "assemble-phase1":
        assert (dest / saved["read_design_input_from"]).read_text() == prompt
    else:
        assert source.read_text() == prompt
        assert saved["output_target"] == "rtl.sv"
    advice = [r for r in saved["spec_requirements"] if r["kind"] == "self_tb_coverage"]
    shapes = [shape for row in advice for shape in row["shapes"]]
    text = " ".join(row["requirement"] for row in advice)
    assert ("handshake_fsm" in shapes) is case["handshake"], advice
    assert ("consecutive_arithmetic" in shapes) is case["consecutive"], advice
    if case["handshake"]:
        assert "BACK-TO-BACK" in text, advice
    else:
        assert "start/valid" not in text and "ready/done" not in text, advice
    if case["consecutive"]:
        assert "arithmetic result" in text, advice
