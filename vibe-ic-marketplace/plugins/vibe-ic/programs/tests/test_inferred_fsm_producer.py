"""Normal L6 production of source-bound AI proposals, not a synthetic signer.

The checked-in incomplete FSM source stays FAIL without author input. CLI facts
exercise typed projection and the real RTL-author handoff; no fixture asserts
that an AI-proposed behavior is functionally correct or independently reviewed.
"""
from __future__ import annotations

import json
from pathlib import Path


import phase1_doc_one_shot_runner as phase1
import l6_fsm_scaffold_actionable_check as gate


PLUGIN = Path(phase1.__file__).resolve().parent.parent
SOURCE = (PLUGIN / "programs/tests/fixtures/fsm_source_contract/incomplete_detector.md").read_text()
INTERFACE = """
## Interface
| Signal | Direction | Width | Description |
| --- | --- | --- | --- |
| bit_in | input | 1 | Received bit |
| wave | output | 5 | Output word |
"""


def _l6(project):
    return json.loads((project / "phase1/generated_docs/L6_CONTROL_LOGIC.json").read_text())


def _produce(project):
    extracted = {p.name: p.read_text() for p in sorted((project / "input/docs").glob("*.md"))}
    phase1.gen_l1_datasheet(project, extracted)
    phase1.gen_l6_control_logic(project, extracted)
    return _l6(project)


def _source(project, extra=""):
    path = project / "input/docs/control.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SOURCE + INTERFACE + extra)
    return _produce(project)








def test_no_proposal_preserves_source_document_and_missing_behavior_failure(tmp_path):
    original = _source(tmp_path)
    first = (tmp_path / "phase1/generated_docs/L6_CONTROL_LOGIC.json").read_bytes()
    assert gate.evaluate(tmp_path)["verdict"] == "FAIL"
    assert not any(s.get("transitions") for s in original["fsm_states"])
    (tmp_path / "phase1/unrelated.json").write_text('{"fsm_transitions": []}')
    _produce(tmp_path)
    assert (tmp_path / "phase1/generated_docs/L6_CONTROL_LOGIC.json").read_bytes() == first

































def test_original_input_handoff_excludes_stale_l6_proposal(tmp_path):
    import _path_layout as layout
    from design_one_shot_runner import _stage_author_knowledge_digests

    prompt = tmp_path / "input/phase1_prompt.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("Module name: neutral_select\nImplement a combinational selector.\n")
    l6 = tmp_path / "phase1/generated_docs/L6_CONTROL_LOGIC.json"
    l6.parent.mkdir(parents=True)
    l6.write_text(json.dumps({
        "behavioral_refinement": {"source": "inferred", "status": "proposed",
                                  "source_text_sha256": "old-source-identity"},
        "fsm_transitions": [{"from": "OLD_A", "to": "OLD_B",
                             "guard": {"port": "old_port", "op": "==", "value": 1}}],
    }))
    before = l6.read_bytes()
    previous = layout._RTL_INPUT
    try:
        layout.select_rtl_input(tmp_path, "original", "1", "2")
        hint, extras = _stage_author_knowledge_digests(tmp_path)
    finally:
        layout._RTL_INPUT = previous
    assert extras["input_authority"] == "original"
    assert extras["read_prompt_from"] == str(prompt)
    assert "behavioral_refinement" not in extras
    assert "BEHAVIORAL PROPOSAL" not in hint
    assert l6.read_bytes() == before
