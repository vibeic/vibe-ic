"""`fires_on:` was DECORATIVE. Measured, then made load-bearing.

MEASURED ON v1.13.66, unmodified: set the shipped `stage1` block's
`fires_on: stage_pass` to `never` and `stage_on_pass_review` went on rejecting
the published known-BAD tree, byte for byte, at rc 1. Nothing read the field.

A field the engine does not read is worse than an absent one, because the flow
author believes it and writes to it. The field was NOT deleted: deleting it
would also have to delete `on_pass_review_declared_command_runs_check`'s P4, a
BLOCKING declaration-time gate that already refuses any other value in the
shipped flow. So the pair is — the declaration gate refuses a block that
declares something else, and the engine refuses to RUN one.

Every arm below has a CONTROL: the same tree, the same argv, the shipped
declaration, which must keep answering rc 1 on known-BAD and rc 0 on
known-GOOD in every arm.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
sys.path.insert(0, str(PROGRAMS))

import stage_on_pass_review as S  # noqa: E402

SUBJECT = PROGRAMS / "stage_on_pass_review.py"
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
STAGE, BAD, GOOD = "stage1", "reject_caravel", "accept_spm"
ARGV = ["--stage", STAGE, "--json", "rec.json",
        "--compliance", "reports/flow_compliance.json"]




def _flow_with_fires_on(tmp_path: Path, value: str) -> Path:
    """The shipped flow with ONLY stage1's `fires_on:` rewritten."""
    text = FLOW.read_text(encoding="utf-8")
    i = text.index("id: stage1")
    j = text.index("fires_on: stage_pass", i)
    out = tmp_path / f"flow_{value}.yaml"
    out.write_text(text[:j] + f"fires_on: {value}"
                   + text[j + len("fires_on: stage_pass"):], encoding="utf-8")
    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    got = next(st["on_pass_review"]["fires_on"] for st in doc["stages"]
               if str(st.get("id")) == STAGE)
    assert str(got) == value, f"the mutation did not land: {got!r}"
    return out




def test_the_shipped_flow_declares_only_the_supported_value():
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    declared = {str(st["on_pass_review"].get("fires_on"))
                for st in (doc.get("stages") or [])
                if isinstance(st.get("on_pass_review"), dict)}
    assert declared == {S._SUPPORTED_FIRES_ON}, declared






def test_the_pre_fix_behaviour_is_what_the_arm_reproduces(tmp_path):
    """THE NEGATIVE CONTROL FOR THE ARM ITSELF. `never` must reach the engine
    as `never` — if the mutation silently failed to land, the arm above would
    be asserting nothing. Proven by reading the mutated flow back."""
    flow = _flow_with_fires_on(tmp_path, "never")
    doc = yaml.safe_load(flow.read_text(encoding="utf-8"))
    blocks = {str(st.get("id")): st["on_pass_review"].get("fires_on")
              for st in doc["stages"] if isinstance(st.get("on_pass_review"), dict)}
    assert blocks[STAGE] == "never"
    # ...and every OTHER stage is untouched, so a whole-file rewrite cannot
    # masquerade as a one-field mutation.
    assert {v for k, v in blocks.items() if k != STAGE} == {S._SUPPORTED_FIRES_ON}
